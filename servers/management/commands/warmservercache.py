from collections import defaultdict
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from servers.models import HostDetails
from servers.utils import *


class Command(BaseCommand):
    help = "Warms up redis cache for latest servers."

    def handle(self, *args, **options):
        "Warms up redis cache for latest servers."

        # First delete the warm cache to avoid stale data
        delete_all_host_cache()

        redis_dict = {}
        redis_list = defaultdict(list)

        # Now loop through all container bases and update the cache
        hds = HostDetails.objects.all()
        for hd in hds:
            osdetails = f"{hd.osname}-{hd.osrelease}"
            if update_latest_hosts(hd.host.hostname, hd.id, hd.time):
                # we update local cache
                redis_dict[hd.host.hostname] = (osdetails, hd.host.id)

        # Now create lists for different osdetails
        for k, v in redis_dict.items():
            redis_list[v[0]].append((k, v[1]))  # (hostname, host_id) for the database

        # Now update redis
        save_osdetails(redis_list)

        self.stdout.write(self.style.SUCCESS("Redis cache warmed up for latest hosts."))
