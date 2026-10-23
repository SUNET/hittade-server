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


# Hash of host id -> JSON [hostname, osdetails, hostdetails_id, time] for the
# latest HostDetails of every host. Used by the /servers/ index page. Keyed by
# id because Host.hostname is not unique.
LATEST_HOSTS_KEY = "latesthosts"
# Set only by a complete rebuild (warmservercache), to the run_id of the redis
# process it was built in. Without it the hash may be partial (e.g. redis was
# flushed and addhost added a single host). With a different run_id, redis has
# restarted since, possibly from a snapshot older than later imports. Either
# way readers must use the database until the next rebuild.
LATEST_HOSTS_READY_KEY = "latesthosts:ready"
# A rebuild fills this hash and then renames it over LATEST_HOSTS_KEY.
LATEST_HOSTS_BUILDING_KEY = "latesthosts:building"
# Only one rebuild at a time; holds the run_id of the redis process it was taken
# in, so a lock restored from a snapshot after a restart does not block rebuilds.
LATEST_HOSTS_LOCK_KEY = "latesthosts:lock"
LOCK_SECONDS = 3600
# Marks the building hash as existing before any host is added to it.
BUILDING_PLACEHOLDER = "__building__"
# Old formats, only deleted now: osdetails -> list of hosts, and latesth:{hostname}.
LEGACY_OSDETAILS_KEY = "osdetails"
LEGACY_LATEST_PATTERN = "latesth:*"

# The scripts are registered once; every call passes client= so they always
# run on the current module-level client.
# Sets KEYS[n][ARGV[1]] (the host id) = ARGV[3] where ARGV[2] (the time) is newer than the
# stored entry. KEYS[1] is always updated, the others only while they exist,
# so imports during a rebuild also land in the building hash. Returns 1 if
# KEYS[1] was updated.
_SET_IF_NEWER = r.register_script(
    """
local field, time, value = ARGV[1], tonumber(ARGV[2]), ARGV[3]
local updated = 0
for i, key in ipairs(KEYS) do
    if i == 1 or redis.call("EXISTS", key) == 1 then
        local current = redis.call("HGET", key, field)
        if not current or time > tonumber(cjson.decode(current)[4]) then
            redis.call("HSET", key, field, value)
            if i == 1 then
                updated = 1
            end
        end
    end
end
return updated
"""
)

# Atomically replaces the live hash with the building one and marks it ready
# for the redis process (ARGV[2]) the rebuild started in.
_PUBLISH = r.register_script(
    """
redis.call("HDEL", KEYS[1], ARGV[1])
if redis.call("EXISTS", KEYS[1]) == 1 then
    redis.call("RENAME", KEYS[1], KEYS[2])
else
    redis.call("DEL", KEYS[2])
end
redis.call("SET", KEYS[3], ARGV[2])
"""
)

# Takes the rebuild lock unless this redis process (ARGV[1]) already holds it.
_LOCK = r.register_script(
    """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return 0
end
redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
return 1
"""
)


def _redis_run_id() -> str:
    "Random id of the running redis process; it changes on every restart."
    return r.info("server")["run_id"]


def latest_hosts_ready() -> bool:
    "Whether the cache was fully rebuilt in the current redis process."
    run_id = _redis_run_id()
    ready = r.get(LATEST_HOSTS_READY_KEY)
    return ready is not None and ready.decode("utf-8") == run_id


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


def _entry(hostname: str, osdetails: str, db_id: int | None, time_value: float) -> str:
    return json.dumps([hostname, osdetails, db_id, time_value])


def update_latest_hosts(
    hostname: str, db_id: int, ctime: datetime, host_id: int, osdetails: str
) -> bool:
    "Updates the latest host entry, if this HostDetails is newer."
    time_value = _timestamp(ctime)
    updated = _SET_IF_NEWER(
        keys=[LATEST_HOSTS_KEY, LATEST_HOSTS_BUILDING_KEY],
        args=[host_id, time_value, _entry(hostname, osdetails, db_id, time_value)],
        client=r,
    )
    return bool(updated)


def get_osdetails() -> dict[str, list[tuple[str, int]]] | None:
    """Returns osdetails -> [(hostname, host_id), ...] from the cache.

    Hosts are ordered newest first (by host id), like the database version.
    Returns None when the cache is not complete: it was not fully rebuilt in
    the running redis process (run warmservercache), or a HostDetails row is not
    in it yet (a redis write failed or was interrupted; see
    sync_uncached_host_details()).
    """
    from .models import HostDetails

    if HostDetails.objects.filter(cached=False).exists():
        return None
    # The run_id is read before and after, so a restart while reading (which
    # could restore an old hash and ready flag) is never trusted.
    run_id = _redis_run_id()
    pipe = r.pipeline(transaction=True)
    pipe.get(LATEST_HOSTS_READY_KEY)
    pipe.hgetall(LATEST_HOSTS_KEY)
    ready, entries = pipe.execute()
    if ready is None or ready.decode("utf-8") != run_id or _redis_run_id() != run_id:
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


def rebuild_latest_hosts() -> int | None:
    """Rebuilds the latest hosts cache from the database and publishes it.

    Readers keep seeing the previous complete cache (or the database) until the
    new one is swapped in atomically. Returns the number of hosts, or None if
    another rebuild is running.
    """
    # Publish as ready for the process we start in: if redis restarts during
    # the rebuild, the result is not trusted and the next rebuild redoes it.
    run_id = _redis_run_id()
    if not _LOCK(keys=[LATEST_HOSTS_LOCK_KEY], args=[run_id, LOCK_SECONDS], client=r):
        return None
    try:
        # Create the building hash *before* reading the database: an import
        # that commits after our read then also updates it (_SET_IF_NEWER).
        r.delete(LATEST_HOSTS_BUILDING_KEY)
        r.hset(LATEST_HOSTS_BUILDING_KEY, BUILDING_PLACEHOLDER, "1")
        # Rows missing from the cache that the read below will include; rows
        # committed after this stay uncached until the next sync or rebuild.
        uncached = _uncached_ids()
        count = 0
        pipe = r.pipeline(transaction=False)
        for host_id, hostname, db_id, time, osname, osrelease in latest_host_rows().iterator():
            time_value = _timestamp(time)
            _SET_IF_NEWER(
                keys=[LATEST_HOSTS_BUILDING_KEY],
                args=[
                    host_id,
                    time_value,
                    _entry(hostname, osdetails_name(osname, osrelease), db_id, time_value),
                ],
                client=pipe,
            )
            count += 1
            if count % 1000 == 0:
                pipe.execute()
        pipe.execute()
        _PUBLISH(
            keys=[LATEST_HOSTS_BUILDING_KEY, LATEST_HOSTS_KEY, LATEST_HOSTS_READY_KEY],
            args=[BUILDING_PLACEHOLDER, run_id],
            client=r,
        )
        _mark_cached(uncached)
        r.delete(LEGACY_OSDETAILS_KEY, *r.keys(LEGACY_LATEST_PATTERN))
        return count
    finally:
        r.delete(LATEST_HOSTS_LOCK_KEY)


def _uncached_ids() -> list[int]:
    from .models import HostDetails

    return list(
        HostDetails.objects.filter(cached=False).order_by().values_list("id", flat=True)
    )


def _mark_cached(ids: list[int]):
    from .models import HostDetails

    for start in range(0, len(ids), 1000):
        HostDetails.objects.filter(id__in=ids[start : start + 1000]).update(cached=True)


def cache_host_details(hd) -> bool:
    """Puts a new HostDetails into the redis cache, then marks it cached.

    Raises redis.RedisError if redis fails; the row then stays uncached, so the
    index uses the database until sync_uncached_host_details() repairs it.
    """
    updated = update_latest_hosts(
        hd.host.hostname, hd.id, hd.time, hd.host_id, osdetails_name(hd.osname, hd.osrelease)
    )
    _mark_cached([hd.id])
    return updated


def sync_uncached_host_details() -> int:
    """Applies every HostDetails missing from the redis cache. Returns the count.

    Safe to repeat: older rows never replace newer cache entries. Raises
    redis.RedisError if redis is still unavailable.
    """
    from .models import HostDetails

    rows = HostDetails.objects.filter(cached=False).select_related("host").order_by("id")
    count = 0
    for hd in rows.iterator():
        cache_host_details(hd)
        count += 1
    return count


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