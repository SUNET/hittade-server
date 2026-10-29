import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime

import redis
from django.conf import settings
from django.db.models import OuterRef, Subquery

redis_conf = settings.REDIS

r = redis.Redis(host=redis_conf["host"], port=redis_conf["port"], db=redis_conf["db"])

# local variable:
redis_cache = {}


# Hash of host id -> JSON [hostname, osdetails, hostdetails_id, time] for the
# latest HostDetails of every host. Used by the /servers/ index page. Keyed by
# id because Host.hostname is not unique.
#
# The rule is simple: the cache is rebuilt from the database whenever the app
# starts (docker-entrypoint.sh runs warmservercache before serving), and addhost
# updates it in place. It can go stale until the next app restart if redis
# restarts on its own from an older snapshot, a redis write in addhost fails, or
# addhost imports while a rebuild runs (the swap can replace its update).
LATEST_HOSTS_KEY = "latesthosts"
# Each rebuild fills its own temporary hash, then renames it over the live one.
BUILDING_KEY_PREFIX = "latesthosts:building:"
# A crashed rebuild's temporary hash expires instead of staying forever.
BUILDING_TTL_SECONDS = 3600
# Rows per round trip when filling the temporary hash.
BUILDING_BATCH_SIZE = 1000
# Old keys, only deleted now: the osdetails -> hosts hash, latesth:{hostname},
# and the ready flag, lock and shared building hash of an earlier version.
LEGACY_KEYS = ["osdetails", "latesthosts:ready", "latesthosts:lock", "latesthosts:building"]
LEGACY_LATEST_PATTERN = "latesth:*"

# Sets KEYS[1][ARGV[1]] (the host id) = ARGV[3] if ARGV[2] (the time) is newer
# than the stored entry, atomically, so concurrent imports keep the newest scan.
# Returns 1 if it was updated. Calls pass client= so they run on the current
# module-level client.
_SET_IF_NEWER = r.register_script(
    """
local current = redis.call("HGET", KEYS[1], ARGV[1])
if not current or tonumber(ARGV[2]) > tonumber(cjson.decode(current)[4]) then
    redis.call("HSET", KEYS[1], ARGV[1], ARGV[3])
    return 1
end
return 0
"""
)


def osdetails_name(osname, osrelease) -> str:
    "The OS label hosts are grouped by."
    return f"{osname}-{osrelease}"


def _timestamp(ctime: datetime | None) -> float:
    # Naive times are UTC (USE_TZ with TIME_ZONE = "UTC"); aware ones are
    # converted, not relabelled. No time (a host without details) is oldest.
    if ctime is None:
        return 0.0
    if ctime.tzinfo is None:
        ctime = ctime.replace(tzinfo=UTC)
    return ctime.timestamp()


def _entry(hostname: str, osdetails: str, db_id: int | None, time_value: float) -> str:
    return json.dumps([hostname, osdetails, db_id, time_value])


def update_latest_hosts(
    hostname: str, db_id: int, ctime: datetime, host_id: int, osdetails: str
) -> bool:
    "Updates the latest host entry, if this HostDetails is newer."
    time_value = _timestamp(ctime)
    updated = _SET_IF_NEWER(
        keys=[LATEST_HOSTS_KEY],
        args=[host_id, time_value, _entry(hostname, osdetails, db_id, time_value)],
        client=r,
    )
    return bool(updated)


def get_osdetails() -> dict[str, list[tuple[str, int]]] | None:
    """Returns osdetails -> [(hostname, host_id), ...] from the cache.

    Hosts are ordered newest first (by host id), like the database version.
    Returns None when there is no cache (not built yet, or redis was flushed).
    """
    entries = r.hgetall(LATEST_HOSTS_KEY)
    if not entries:
        return None
    hosts = []
    for host_id, value in entries.items():
        hostname, osdetails, _, _ = json.loads(value)
        hosts.append((int(host_id), hostname, osdetails))
    data: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for host_id, hostname, osdetails in sorted(hosts, reverse=True):
        data[osdetails].append((hostname, host_id))
    return dict(data)


def latest_host_rows():
    """Every host with its latest HostDetails, newest host first, in one query.

    Yields (host_id, hostname, hostdetails_id, time, osname, osrelease); the
    last four are None for a host without any HostDetails.
    """
    from .models import Host, HostDetails

    latest = HostDetails.objects.filter(host=OuterRef("pk")).order_by("-time")
    return (
        Host.objects.order_by("-id")
        .annotate(
            hd_id=Subquery(latest.values("id")[:1]),
            hd_time=Subquery(latest.values("time")[:1]),
            osname=Subquery(latest.values("osname")[:1]),
            osrelease=Subquery(latest.values("osrelease")[:1]),
        )
        .values_list("id", "hostname", "hd_id", "hd_time", "osname", "osrelease")
    )


def osdetails_from_db() -> dict[str, list[tuple[str, int]]]:
    "Same as get_osdetails(), computed from the database in one query."
    data: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for host_id, hostname, _, _, osname, osrelease in latest_host_rows():
        data[osdetails_name(osname, osrelease)].append((hostname, host_id))
    return dict(data)


def rebuild_latest_hosts() -> int:
    """Rebuilds the latest hosts cache from the database. Returns the host count.

    The new cache is built in a hash of its own and swapped in with one RENAME,
    so readers see either the old or the new complete cache, and overlapping
    rebuilds never share or empty each other's data.
    """
    building = f"{BUILDING_KEY_PREFIX}{uuid.uuid4().hex}"
    count = 0
    try:
        pipe = r.pipeline(transaction=False)
        for host_id, hostname, db_id, time, osname, osrelease in latest_host_rows().iterator():
            time_value = _timestamp(time)
            entry = _entry(hostname, osdetails_name(osname, osrelease), db_id, time_value)
            pipe.hset(building, host_id, entry)
            count += 1
            if count % BUILDING_BATCH_SIZE == 0:
                pipe.expire(building, BUILDING_TTL_SECONDS)
                pipe.execute()
        pipe.expire(building, BUILDING_TTL_SECONDS)
        pipe.execute()

        pipe = r.pipeline(transaction=True)
        if count:
            # RENAME keeps the TTL of the temporary hash; the live one must not expire.
            pipe.rename(building, LATEST_HOSTS_KEY)
            pipe.persist(LATEST_HOSTS_KEY)
        else:
            pipe.delete(LATEST_HOSTS_KEY)
        pipe.delete(*LEGACY_KEYS, *r.keys(LEGACY_LATEST_PATTERN))
        pipe.execute()
    finally:
        # Gone after a successful RENAME; removes a partial one after an error.
        r.delete(building)
    return count


def generate_host_configurations_dict(input: list) -> dict:
    "Generate dict of configuration files, for use by frontend."
    configurations = {}

    for configuration in input:
        if configuration.ctype not in configurations:
            configurations[configuration.ctype] = {}

        configurations[configuration.ctype][configuration.name] = configuration.value

    return configurations

def latest_running_containers():
    """HostContainersThrough rows of the latest docker ps scan of every host.

    The latest scan of each host is looked up once per host, not per row.
    """
    from .models import Host, HostContainers, HostContainersThrough

    latest_hc_ids = Host.objects.annotate(
        latest_hc=Subquery(
            HostContainers.objects.filter(host=OuterRef("pk"))
            .order_by("-time")
            .values("id")[:1]
        )
    ).values("latest_hc")
    return HostContainersThrough.objects.filter(hc_id__in=latest_hc_ids)


def image_with_tag(image: str) -> str:
    "docker.sunet.se/foo -> docker.sunet.se/foo:latest; tagged or digest refs unchanged."
    if "@" in image or ":" in image.rsplit("/", 1)[-1]:
        return image
    return f"{image}:latest"


def running_containers_with_package(name: str, version: str = ""):
    """Running containers whose image has a package matching name (and version).

    Only the latest docker ps scan of every host counts, and a container is
    matched through its image ID, which is ContainerBase.cid of an imported
    image. Returns (rows, unknown): rows is a list of dicts with host, name (of
    the container), image, imageid, package and version, sorted by host, and
    unknown is (containers, hosts), the counts of running
    containers whose image was never imported, so their packages are unknown.
    """
    from containers.models import ContainerBase, ContainerPackage

    running = list(
        latest_running_containers()
        .select_related("hc__host", "container")
        .order_by("hc__host__hostname", "name")
    )
    imageids = {hc.container.imageid for hc in running}
    imported = set(
        ContainerBase.objects.filter(cid__in=imageids).values_list("cid", flat=True)
    )

    packages = ContainerPackage.objects.filter(name__icontains=name)
    if version:
        packages = packages.filter(version__icontains=version)
    # imageid -> matching (name, version) of the packages in that image.
    matches = defaultdict(set)
    for cid, pname, pversion in ContainerBase.packages.through.objects.filter(
        containerbase__cid__in=imported, containerpackage__in=packages
    ).values_list(
        "containerbase__cid", "containerpackage__name", "containerpackage__version"
    ):
        matches[cid].add((pname, pversion))

    rows = []
    unknown_hosts = set()
    unknown_containers = 0
    for hc in running:
        imageid = hc.container.imageid
        if imageid not in imported:
            unknown_containers += 1
            unknown_hosts.add(hc.hc.host_id)
            continue
        for pname, pversion in sorted(matches[imageid]):
            rows.append(
                {
                    "host": hc.hc.host,
                    "name": hc.name,
                    "image": hc.container.image,
                    "imageid": imageid,
                    "package": pname,
                    "version": pversion,
                }
            )
    return rows, (unknown_containers, len(unknown_hosts))
