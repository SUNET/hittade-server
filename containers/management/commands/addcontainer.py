import pathlib

import orjson
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from containers.models import ContainerBase, ContainerPackage, ContainerTags
from containers.utils import update_latest_containers

# DB cache for runtime: "name:version:provider" -> ContainerPackage id
PACKAGES = {}


class Command(BaseCommand):
    help = "Adds container image details to the database."

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)

    def handle(self, *args, **options):
        filename = options["filename"]
        # This is the time data is entered in the database.
        itime = timezone.now()
        # Warm the package cache with everything already in the database, so
        # each file only has to insert the packages we have never seen.
        for pid, name, version, provider in ContainerPackage.objects.values_list(
            "id", "name", "version", "provider"
        ).iterator():
            PACKAGES[f"{name}:{version}:{provider}"] = pid
        p = pathlib.Path(filename)
        if p.is_dir():
            # We have a directory of files.
            for filename in p.rglob("*.json"):
                self.add_container_images(filename, itime)
        else:
            self.add_container_images(filename, itime)

    def add_container_images(self, filename, itime):
        "Parses and stores data on database."
        self.stdout.write(self.style.SUCCESS(f"Parsing {filename}"))

        # Using orjson to faster parsing of the JSON data
        with open(filename, "rb") as fobj:
            try:
                maindata = orjson.loads(fobj.read())
            except orjson.JSONDecodeError:
                self.stderr.write(self.style.ERROR(f"Invalid JSON in file: {filename}"))
                return

        data = next(iter(maindata.values()))

        try:
            image_data = data["inspect_data"][0]
            cid = image_data["Id"]
            # Created is an ISO 8601 string (RFC3339, possibly with a Z suffix).
            # Parse it to an aware datetime; fall back to the ingest time when it
            # is missing or empty (e.g. a record awaiting `cscan scan-backfill`).
            ctime = parse_datetime(image_data.get("Created") or "") or itime
            repotags = image_data["RepoTags"]
        except KeyError:
            self.stderr.write(self.style.ERROR(f"Invalid input in file: {filename}"))
            return
        # The OS details maybe missing in the JSON files.
        #
        os_data = data.get("os_hash", {})
        osname = os_data.get("NAME", "Unknown")
        osversion = os_data.get("VERSION_ID", "Unknown")

        # The first tag defines the container name
        fulltag_1 = repotags[0]
        cname = fulltag_1.split(":")[0]

        itags = ContainerTags.objects.filter(fullname=fulltag_1)

        # Verify if we already saved this data based on container ID and the full name.
        cb = ContainerBase.objects.filter(cid=cid, tags__in=itags).first()
        if cb:
            # We already have this data, so skip
            self.stdout.write(f"Skipping {cid} from file {filename}.")
            return

        # Unique packages of this image, keyed like PACKAGES.
        wanted = {}
        for package_data in data.get("pkg_list", []):
            name = package_data["package"]
            version = package_data["version"]
            if not name or not version:
                continue
            provider = package_data["provider"]
            wanted[f"{name}:{version}:{provider}"] = (name, version, provider)

        # One transaction per file, so a failure never leaves a half-imported image.
        with transaction.atomic():
            # Save the containerbase details
            cb = ContainerBase.objects.create(
                cid=cid, cname=cname, osname=osname, osversionid=osversion, time=itime, ctime=ctime
            )

            tags = []
            # Save the tags
            for fulltag in repotags:
                words = fulltag.split(":")
                tag = words[0]
                ct, _ = ContainerTags.objects.get_or_create(tag=tag, fullname=fulltag)
                tags.append(ct)
            cb.tags.add(*tags)

            # Insert all the packages we have not seen before in one query.
            # ignore_conflicts keeps this safe if another import added some of
            # them meanwhile; it does not return ids, so read them back.
            new_keys = [key for key in wanted if key not in PACKAGES]
            new_ids = {}
            if new_keys:
                ContainerPackage.objects.bulk_create(
                    [
                        ContainerPackage(name=name, version=version, provider=provider)
                        for name, version, provider in (wanted[key] for key in new_keys)
                    ],
                    ignore_conflicts=True,
                )
                names = {wanted[key][0] for key in new_keys}
                for pid, name, version, provider in ContainerPackage.objects.filter(
                    name__in=names
                ).values_list("id", "name", "version", "provider"):
                    key = f"{name}:{version}:{provider}"
                    if key in wanted:
                        new_ids[key] = pid
            cb.packages.add(*(new_ids.get(key) or PACKAGES[key] for key in wanted))

            # Only cache the new ids (and update the warm cache for latest
            # containers) once the rows really exist.
            def after_commit():
                PACKAGES.update(new_ids)
                update_latest_containers(cname, cb.id, cb.ctime)

            transaction.on_commit(after_commit)
        self.stdout.write(self.style.SUCCESS(f"Successfully added {filename}"))
