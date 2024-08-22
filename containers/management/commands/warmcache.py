from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from containers.models import ContainerTags, ContainerBase, ContainerPackage
from datetime import datetime
from pprint import pprint
from containers.utils import *


class Command(BaseCommand):
    help = "Warms up redis cache for latest containers."


    def handle(self, *args, **options):
        "Warms up redis cache for latest containers."

        # First delete the warm cache to avoid stale data
        delete_all_container_cache()
        # Now loop through all container bases and update the cache
        cbs = ContainerBase.objects.all()
        for cb in cbs:
            update_latest_containers(cb.cname, cb.id, cb.ctime)
        self.stdout.write(self.style.SUCCESS("Redis cache warmed up for latest containers."))