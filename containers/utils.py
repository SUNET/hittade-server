import re
from collections import defaultdict
from datetime import UTC, datetime

import redis
from django.conf import settings
from django.db.models import Count, Q

from servers.utils import latest_running_containers

from .models import ContainerBase

redis_conf = settings.REDIS

r = redis.Redis(host=redis_conf["host"], port=redis_conf["port"], db=redis_conf["db"])

def update_latest_containers(cname: str, db_id:int, ctime: datetime) -> None:
    "Updates the latest container entry"
    key = f"latest:{cname}"
    time_value = ctime.replace(tzinfo=UTC).timestamp()
    current_latest = r.hget(key, "time")
    if time_value > float(current_latest or 0):
        r.hset(key, "time", time_value)
        r.hset(key, "db_id", db_id)

def latest_containers() -> list:
    "Get the IDs of the latest containers"
    keys = r.keys("latest:*")
    results = []
    for key in keys:
        db_id = int(r.hget(key, "db_id"))
        results.append(db_id)
    return results


def delete_all_container_cache():
    "Deletes the warm cache."
    keys = r.keys("latest:*")
    for key in keys:
        r.delete(key)


def natural_key(text: str) -> list:
    """Sort key that compares the numbers in text as numbers.

    "10.1" splits into ["", "10", ".", "1", ""], so 9.2 sorts before 10.1 and
    12.7 before 12.10. Each part becomes a tuple that orders numbers before
    text, so number and text parts never get compared with each other.
    """
    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"(\d+)", text or "")
    ]


def running_os_versions() -> list[tuple[str, list[tuple[str, int]]]]:
    """[(osname, [(osversionid, images), ...]), ...] of the running images.

    Running images are those in the latest docker ps scan of a host that were
    scanned as container images: a host reports the image ID, which is the
    ContainerBase.cid of the scan. images is the number of such images with
    that OS name and version. Sorted by name, then version (naturally). A
    missing name or version is "".
    """
    groups = defaultdict(list)
    for row in (
        ContainerBase.objects.filter(
            cid__in=latest_running_containers().values("container__imageid")
        )
        .values("osname", "osversionid")
        # One image can be stored once per tag; count it once.
        .annotate(images=Count("cid", distinct=True))
    ):
        groups[row["osname"] or ""].append((row["osversionid"] or "", row["images"]))
    return [
        (osname, sorted(versions, key=lambda v: natural_key(v[0])))
        for osname, versions in sorted(groups.items())
    ]


def running_images_with_os(osname: str, osversionid: str) -> list[dict]:
    """Running images (see running_os_versions) with this OS name and version.

    A list of {"cid", "tags", "hosts"} sorted by tag, one per image ID (an
    image stored once per tag has its tags merged), where hosts is the number
    of hosts running the image.
    """
    running = latest_running_containers()
    images = ContainerBase.objects.filter(cid__in=running.values("container__imageid"))
    # running_os_versions shows a missing name or version as "", so "" here
    # matches an empty value as well as NULL.
    for field, value in (("osname", osname), ("osversionid", osversionid)):
        if value:
            images = images.filter(**{field: value})
        else:
            images = images.filter(Q(**{field: ""}) | Q(**{f"{field}__isnull": True}))
    images = images.prefetch_related("tags")

    # cid -> tags: cscan can store the same image once per tag, as rows with
    # the same cid; they are one image here.
    tags = defaultdict(set)
    for cb in images:
        tags[cb.cid].update(t.fullname for t in cb.tags.all())

    # cid -> number of hosts running it, counted in one query. A host running
    # an image in several containers counts once.
    hosts = dict(
        running.filter(container__imageid__in=tags)
        .values_list("container__imageid")
        .annotate(hosts=Count("hc__host", distinct=True))
    )
    result = [
        {"cid": cid, "tags": sorted(names), "hosts": hosts.get(cid, 0)}
        for cid, names in tags.items()
    ]
    return sorted(result, key=lambda image: (image["tags"], image["cid"]))
