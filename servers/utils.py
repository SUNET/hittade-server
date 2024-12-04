import json
from datetime import datetime, timezone
from typing import Any, List

import redis
from django.conf import settings

redis_conf = settings.REDIS

r = redis.Redis(host=redis_conf["host"], port=redis_conf["port"], db=redis_conf["db"])

# local variable:
redis_cache = {}


def update_latest_hosts(hostname: str, db_id: int, ctime: datetime) -> bool:
    "Updates the latest host entry"
    global r
    key = f"latesth:{hostname}"
    time_value = ctime.replace(tzinfo=timezone.utc).timestamp()
    current_latest = r.hget(key, "time")
    if time_value > float(current_latest or 0):
        r.hset(key, "time", time_value)
        r.hset(key, "db_id", db_id)
        return True

    return False


def save_osdetails(details: dict[str, list[Any]]):
    "Saves the osdetails for various servers on redis"
    global r
    db_dir = {}
    for key, value in details.items():
        data = json.dumps(value)
        db_dir[key] = data

    # Save to redis
    r.hmset("osdetails", db_dir)


def get_osdetails():
    "Returns dictionary of all different osdetails"
    global r
    return r.hgetall("osdetails")


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
    for key in keys:
        r.delete(key)
