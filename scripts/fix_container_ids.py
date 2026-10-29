#!/usr/bin/env python3
"""Set the image ID of imported container images from what hosts run.

Run it from the directory that has manage.py (/app in the container):

    python scripts/fix_container_ids.py           # dry run: only print the changes
    python scripts/fix_container_ids.py --apply   # write the changes

Add ``--export FILE`` (with or without --apply) to also write the changes to a
text file, one "old ID<TAB>new ID<TAB>tags" line per image, for cscan's
``just fix-from-file FILE``: it gives cscan's records on disk exactly the IDs
the database gets, so importing them later adds no second row for an image.
Export before applying: once applied, the old IDs are gone from the database.

Imported container images (ContainerBase.cid) were stored with the registry
manifest digest, while hosts report the image config digest of their running
containers, so the two never match. For the latest container scan of every
host, this finds the imported images with the same name:tag and sets their cid
to the image ID the host reports, together with the other tags imported with
the same digest (the same image).

A tag can have several imported builds (e.g. "latest" scanned at different
times). The registry tells which build a host runs: the build whose manifest
has the host's image ID as its config digest. When the registry cannot tell
(manifest gone, or not a docker.sunet.se image), a tag with a single imported
build is still updated and marked "unverified"; otherwise it is skipped.
"""

import argparse
import functools
import json
import os
import sys
import urllib.error
import urllib.request

REGISTRY = "docker.sunet.se"
MANIFEST_ACCEPT = (
    "application/vnd.docker.distribution.manifest.v2+json, "
    "application/vnd.oci.image.manifest.v1+json"
)


def registry_config_digest(image, manifest_digest):
    """Config digest of image@manifest_digest from docker.sunet.se, or None."""
    name = image.rsplit(":", 1)[0]
    if not name.startswith(REGISTRY + "/"):
        return None
    repo = name[len(REGISTRY) + 1 :]
    url = f"https://{REGISTRY}/v2/{repo}/manifests/{manifest_digest}"
    request = urllib.request.Request(url, headers={"Accept": MANIFEST_ACCEPT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            manifest = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None
    return (manifest.get("config") or {}).get("digest")


def full_tag(image):
    "docker.sunet.se/foo -> docker.sunet.se/foo:latest, as the tags are stored."
    if ":" not in image.rsplit("/", 1)[-1]:
        return image + ":latest"
    return image


def plan(config_digest=registry_config_digest):
    """Returns (changes, notes).

    changes is a list of (ContainerBase, new_cid, how) and notes a list of
    messages about running images that were skipped.
    """
    from django.db.models import OuterRef, Subquery

    from containers.models import ContainerBase
    from servers.models import ContainerImage, Host, HostContainers, HostContainersThrough

    latest_hc_ids = Host.objects.annotate(
        latest_hc=Subquery(
            HostContainers.objects.filter(host=OuterRef("pk"))
            .order_by("-time")
            .values("id")[:1]
        )
    ).values("latest_hc")
    # Every (name:tag, image ID) running on a host, from the latest scans.
    running = set(
        HostContainersThrough.objects.filter(hc_id__in=latest_hc_ids)
        .exclude(container__imageid__in=["", "not_available"])
        .values_list("container__image", "container__imageid")
    )

    # Image IDs hosts have ever reported. A cid among them is already an image
    # ID (a config digest): the manifest digests cscan stored never show up in
    # host data, so such a row is never changed again.
    host_ids = set(ContainerImage.objects.values_list("imageid", flat=True))

    config_digest = functools.cache(config_digest)
    changes, notes = [], []
    planned = {}  # old cid -> new cid
    for image, imageid in sorted(running):
        tag = full_tag(image)
        if imageid in planned.values() or ContainerBase.objects.filter(cid=imageid).exists():
            continue  # already linked, or will be
        rows = list(ContainerBase.objects.filter(tags__fullname=tag).distinct())
        if not rows:
            notes.append(f"{tag}: not imported")
            continue
        candidates = [cb for cb in rows if cb.cid not in host_ids and cb.cid not in planned]
        verified = [cb for cb in candidates if config_digest(tag, cb.cid) == imageid]
        if verified:
            cb, how = verified[0], "verified"
        elif len(rows) == 1 and candidates and config_digest(tag, rows[0].cid) is None:
            cb, how = rows[0], "unverified"
        else:
            notes.append(f"{tag}: none of the {len(rows)} imported build(s) is {imageid}")
            continue
        planned[cb.cid] = imageid
        changes.append((cb, imageid, how))
    return changes, notes


def apply(changes):
    "Writes the changes from plan(). Returns the number of rows updated."
    from django.db import transaction

    from containers.models import ContainerBase

    rows = 0
    with transaction.atomic():
        for cb, new_cid, _ in changes:
            # Also the rows of the other tags imported with the same digest.
            rows += ContainerBase.objects.filter(cid=cb.cid).update(cid=new_cid)
    return rows


def tags_of(cid):
    "Every tag imported with this ID (the same image), comma-separated."
    from containers.models import ContainerTags

    return ",".join(
        ContainerTags.objects.filter(containerbase__cid=cid)
        .distinct()
        .order_by("fullname")
        .values_list("fullname", flat=True)
    )


def export(changes, path):
    "Writes the changes from plan() as old ID<TAB>new ID<TAB>tags lines."
    with open(path, "w") as fobj:
        fobj.writelines(f"{cb.cid}\t{new_cid}\t{tags_of(cb.cid)}\n" for cb, new_cid, _ in changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument(
        "--export", metavar="FILE", help="also write the changes to FILE for cscan"
    )
    args = parser.parse_args()

    # Run from the directory with manage.py, even as scripts/fix_container_ids.py.
    sys.path.insert(0, os.getcwd())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hittade.settings")
    import django

    django.setup()

    changes, notes = plan()
    for note in notes:
        print(f"skip   {note}")
    for cb, new_cid, how in changes:
        print(f"update {tags_of(cb.cid)}: {cb.cid} -> {new_cid} ({how})")
    if args.export:
        # Before apply(): it replaces the old IDs the file is built from.
        export(changes, args.export)
        print(f"\nWrote {len(changes)} change(s) to {args.export}")

    if not args.apply:
        print(
            f"\n{len(changes)} image(s) to update, {len(notes)} skipped. "
            "Dry run: rerun with --apply to write the changes."
        )
        return
    rows = apply(changes)
    print(f"\nUpdated {len(changes)} image(s) ({rows} rows), {len(notes)} skipped.")


if __name__ == "__main__":
    main()
