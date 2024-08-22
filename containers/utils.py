from django.conf import settings
from datetime import datetime, timezone
import redis

redis_conf = settings.REDIS

r = redis.Redis(host=redis_conf["host"], port=redis_conf["port"], db=redis_conf["db"])

def update_latest_containers(cname: str, db_id:int, ctime: datetime) -> None:
    "Updates the latest container entry"
    global r
    key = f"latest:{cname}"
    time_value = ctime.replace(tzinfo=timezone.utc).timestamp()
    current_latest = r.hget(key, "time")
    if time_value > float(current_latest or 0):
        r.hset(key, "time", time_value)
        r.hset(key, "db_id", db_id)

def latest_containers() -> list:
    "Get the IDs of the latest containers"
    global r
    keys = r.keys("latest:*")
    results = []
    for key in keys:
        db_id = int(r.hget(key, "db_id"))
        results.append(db_id)
    return results


def delete_all_container_cache():
    "Deletes the warm cache."
    global r
    keys = r.keys("latest:*")
    for key in keys:
        r.delete(key)
