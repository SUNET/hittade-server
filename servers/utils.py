import json
from collections import defaultdict
from datetime import datetime, timezone

import redis
from django.conf import settings
from django.db.models import OuterRef, Subquery

redis_conf = settings.REDIS

r = redis.Redis(host=redis_conf["host"], port=redis_conf["port"], db=redis_conf["db"])

# local variable:
redis_cache = {}


# Hash of hostname -> JSON [host_id, osdetails, hostdetails_id, time] for the
# latest HostDetails of every host. Used by the /servers/ index page.
LATEST_HOSTS_KEY = "latesthosts"
# Set only by a complete rebuild (warmservercache). Without it the hash may be
# partial (e.g. redis was flushed and addhost added a single host), so readers
# must use the database instead.
LATEST_HOSTS_READY_KEY = "latesthosts:ready"
# A rebuild fills this hash and then renames it over LATEST_HOSTS_KEY.
LATEST_HOSTS_BUILDING_KEY = "latesthosts:building"
# Only one rebuild at a time.
LATEST_HOSTS_LOCK_KEY = "latesthosts:lock"
# Marks the building hash as existing before any host is added to it.
BUILDING_PLACEHOLDER = "__building__"
# Old formats, only deleted now: osdetails -> list of hosts, and latesth:{hostname}.
LEGACY_OSDETAILS_KEY = "osdetails"
LEGACY_LATEST_PATTERN = "latesth:*"

# The scripts are registered once; every call passes client= so they always
# run on the current module-level client.
# Sets KEYS[n][ARGV[1]] = ARGV[3] where ARGV[2] (the time) is newer than the
# stored entry. KEYS[1] is always updated, the others only while they exist,
# so imports during a rebuild also land in the building hash. Returns 1 if
# KEYS[1] was updated.
_SET_IF_NEWER = r.register_script(
    """
local hostname, time, value = ARGV[1], tonumber(ARGV[2]), ARGV[3]
local updated = 0
for i, key in ipairs(KEYS) do
    if i == 1 or redis.call("EXISTS", key) == 1 then
        local current = redis.call("HGET", key, hostname)
        if not current or time > tonumber(cjson.decode(current)[4]) then
            redis.call("HSET", key, hostname, value)
            if i == 1 then
                updated = 1
            end
        end
    end
end
return updated
"""
)

# Atomically replaces the live hash with the building one and marks it ready.
_PUBLISH = r.register_script(
    """
redis.call("HDEL", KEYS[1], ARGV[1])
if redis.call("EXISTS", KEYS[1]) == 1 then
    redis.call("RENAME", KEYS[1], KEYS[2])
else
    redis.call("DEL", KEYS[2])
end
redis.call("SET", KEYS[3], "1")
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
        ctime = ctime.replace(tzinfo=timezone.utc)
    return ctime.timestamp()


def _entry(host_id: int, osdetails: str, db_id: int | None, time_value: float) -> str:
    return json.dumps([host_id, osdetails, db_id, time_value])


def update_latest_hosts(
    hostname: str, db_id: int, ctime: datetime, host_id: int, osdetails: str
) -> bool:
    "Updates the latest host entry, if this HostDetails is newer."
    time_value = _timestamp(ctime)
    updated = _SET_IF_NEWER(
        keys=[LATEST_HOSTS_KEY, LATEST_HOSTS_BUILDING_KEY],
        args=[hostname, time_value, _entry(host_id, osdetails, db_id, time_value)],
        client=r,
    )
    return bool(updated)


def get_osdetails() -> dict[str, list[tuple[str, int]]] | None:
    """Returns osdetails -> [(hostname, host_id), ...] from the cache.

    Hosts are ordered newest first (by host id), like the database version.
    Returns None when the cache is not complete (run warmservercache).
    """
    pipe = r.pipeline(transaction=True)
    pipe.exists(LATEST_HOSTS_READY_KEY)
    pipe.hgetall(LATEST_HOSTS_KEY)
    ready, entries = pipe.execute()
    if not ready:
        return None
    hosts = []
    for hostname, value in entries.items():
        host_id, osdetails, _, _ = json.loads(value)
        hosts.append((host_id, hostname.decode("utf-8"), osdetails))
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


def rebuild_latest_hosts() -> int | None:
    """Rebuilds the latest hosts cache from the database and publishes it.

    Readers keep seeing the previous complete cache (or the database) until the
    new one is swapped in atomically. Returns the number of hosts, or None if
    another rebuild is running.
    """
    if not r.set(LATEST_HOSTS_LOCK_KEY, "1", nx=True, ex=3600):
        return None
    try:
        # Create the building hash *before* reading the database: an import
        # that commits after our read then also updates it (_SET_IF_NEWER).
        r.delete(LATEST_HOSTS_BUILDING_KEY)
        r.hset(LATEST_HOSTS_BUILDING_KEY, BUILDING_PLACEHOLDER, "1")
        count = 0
        pipe = r.pipeline(transaction=False)
        for host_id, hostname, db_id, time, osname, osrelease in latest_host_rows().iterator():
            time_value = _timestamp(time)
            _SET_IF_NEWER(
                keys=[LATEST_HOSTS_BUILDING_KEY],
                args=[
                    hostname,
                    time_value,
                    _entry(host_id, osdetails_name(osname, osrelease), db_id, time_value),
                ],
                client=pipe,
            )
            count += 1
            if count % 1000 == 0:
                pipe.execute()
        pipe.execute()
        _PUBLISH(
            keys=[LATEST_HOSTS_BUILDING_KEY, LATEST_HOSTS_KEY, LATEST_HOSTS_READY_KEY],
            args=[BUILDING_PLACEHOLDER],
            client=r,
        )
        r.delete(LEGACY_OSDETAILS_KEY, *r.keys(LEGACY_LATEST_PATTERN))
        return count
    finally:
        r.delete(LATEST_HOSTS_LOCK_KEY)


def delete_all_host_cache():
    "Deletes the warm cache; readers use the database until the next rebuild."
    r.delete(
        LATEST_HOSTS_READY_KEY,
        LATEST_HOSTS_KEY,
        LATEST_HOSTS_BUILDING_KEY,
        LEGACY_OSDETAILS_KEY,
        *r.keys(LEGACY_LATEST_PATTERN),
    )


def generate_host_configurations_dict(input: list) -> dict:
    "Generate dict of configuration files, for use by frontend."
    configurations = {}

    for configuration in input:
        if configuration.ctype not in configurations:
            configurations[configuration.ctype] = {}

        configurations[configuration.ctype][configuration.name] = configuration.value

    return configurations