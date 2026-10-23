from django.core.management.base import BaseCommand

from servers.models import HostDetails
from servers.utils import delete_all_host_cache, osdetails_name, update_latest_hosts


class Command(BaseCommand):
    help = "Warms up redis cache for latest servers."

    def handle(self, *args, **options):
        "Warms up redis cache for latest servers."

        # First delete the warm cache to avoid stale data
        delete_all_host_cache()

        # Newest first, so the first row we see for a host is its latest one.
        seen = set()
        hds = (
            HostDetails.objects.order_by("-time")
            .values_list("id", "time", "osname", "osrelease", "host_id", "host__hostname")
            .iterator()
        )
        for db_id, time, osname, osrelease, host_id, hostname in hds:
            if host_id in seen:
                continue
            seen.add(host_id)
            update_latest_hosts(hostname, db_id, time, host_id, osdetails_name(osname, osrelease))

        self.stdout.write(
            self.style.SUCCESS(f"Redis cache warmed up for {len(seen)} latest hosts.")
        )
