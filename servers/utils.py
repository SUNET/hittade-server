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
# Old format (osdetails -> list of hosts), only deleted now.
LEGACY_OSDETAILS_KEY = "osdetails"


def osdetails_name(osname, osrelease) -> str:
    "The OS label hosts are grouped by."
    return f"{osname}-{osrelease}"


def _timestamp(ctime: datetime) -> float:
    # Naive times are UTC (USE_TZ with TIME_ZONE = "UTC"); aware ones are
    # converted, not relabelled.
    if ctime.tzinfo is None:
        ctime = ctime.replace(tzinfo=timezone.utc)
    return ctime.timestamp()


def update_latest_hosts(
    hostname: str, db_id: int, ctime: datetime, host_id: int, osdetails: str
) -> bool:
    "Updates the latest host entry, if this HostDetails is newer."
    global r
    key = f"latesth:{hostname}"
    time_value = _timestamp(ctime)
    current_latest = r.hget(key, "time")
    if time_value > float(current_latest or 0):
        pipe = r.pipeline()
        pipe.hset(key, mapping={"time": time_value, "db_id": db_id})
        pipe.hset(
            LATEST_HOSTS_KEY, hostname, json.dumps([host_id, osdetails, db_id, time_value])
        )
        pipe.execute()
        return True

    return False


def get_osdetails() -> dict[str, list[tuple[str, int]]]:
    """Returns osdetails -> [(hostname, host_id), ...] from the cache.

    Hosts are ordered newest first (by host id), like the database version.
    An empty dict means the cache is empty (run warmservercache).
    """
    global r
    hosts = []
    for hostname, value in r.hgetall(LATEST_HOSTS_KEY).items():
        host_id, osdetails, _, _ = json.loads(value)
        hosts.append((host_id, hostname.decode("utf-8"), osdetails))
    data: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for host_id, hostname, osdetails in sorted(hosts, reverse=True):
        data[osdetails].append((hostname, host_id))
    return dict(data)


def osdetails_from_db() -> dict[str, list[tuple[str, int]]]:
    "Same as get_osdetails(), computed from the database in one query."
    from .models import Host, HostDetails

    latest = HostDetails.objects.filter(host=OuterRef("pk")).order_by("-time")
    hosts = (
        Host.objects.order_by("-id")
        .annotate(
            osname=Subquery(latest.values("osname")[:1]),
            osrelease=Subquery(latest.values("osrelease")[:1]),
        )
        .values_list("hostname", "id", "osname", "osrelease")
    )
    data: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for hostname, host_id, osname, osrelease in hosts:
        data[osdetails_name(osname, osrelease)].append((hostname, host_id))
    return dict(data)


def latest_hostdetails() -> list:
    "Get the IDs of the latest hostdetails"
    global r
    keys = r.keys("latesth:*")
    results = []
    for key in keys:
        db_id = int(r.hget(key, "db_id"))
        results.append(db_id)
    return results


def delete_all_host_cache():
    "Deletes the warm cache."
    global r
    keys = r.keys("latesth:*")
    r.delete(LATEST_HOSTS_KEY, LEGACY_OSDETAILS_KEY, *keys)


def generate_host_configurations_dict(input: list) -> dict:
    "Generate dict of configuration files, for use by frontend."
    configurations = {}

    for configuration in input:
        if configuration.ctype not in configurations:
            configurations[configuration.ctype] = {}

        configurations[configuration.ctype][configuration.name] = configuration.value

    return configurations