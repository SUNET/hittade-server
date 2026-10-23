from django.core.management.base import BaseCommand

from servers.utils import rebuild_latest_hosts


class Command(BaseCommand):
    help = "Warms up redis cache for latest servers."

    def handle(self, *args, **options):
        "Warms up redis cache for latest servers."
        count = rebuild_latest_hosts()

        self.stdout.write(self.style.SUCCESS(f"Redis cache warmed up for {count} latest hosts."))
