from django.core.management.base import BaseCommand, CommandError

from servers.utils import rebuild_latest_hosts


class Command(BaseCommand):
    help = "Warms up redis cache for latest servers."

    def handle(self, *args, **options):
        "Warms up redis cache for latest servers."
        count = rebuild_latest_hosts()
        if count is None:
            raise CommandError("Another warmservercache is already running.")

        self.stdout.write(self.style.SUCCESS(f"Redis cache warmed up for {count} latest hosts."))
