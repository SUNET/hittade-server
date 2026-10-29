from django.core.management.base import BaseCommand
from django.db import transaction

from containers.models import ContainerBase
from servers.models import ContainerImage, HostContainersThrough
from servers.registry import config_digest


class Command(BaseCommand):
    help = (
        "Replaces the manifest digests stored as image IDs of running containers "
        "with config digests, so they match container scans. Dry run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="write the changes")

    def handle(self, *args, **options):
        scanned = set(ContainerBase.objects.values_list("cid", flat=True))
        changes = []
        for ci in ContainerImage.objects.exclude(imageid__in=scanned).order_by("image"):
            digest = config_digest(ci.image, ci.imageid)
            if digest:
                changes.append((ci, digest))
                self.stdout.write(f"{ci.image}: {ci.imageid} -> {digest}")

        if not options["apply"]:
            self.stdout.write(f"{len(changes)} image ID(s) to fix; run with --apply to write.")
            return

        with transaction.atomic():
            for ci, digest in changes:
                target = ContainerImage.objects.filter(image=ci.image, imageid=digest).first()
                if target is None:
                    ci.imageid = digest
                    ci.save(update_fields=["imageid"])
                else:
                    # The host links move to the existing row for the image.
                    HostContainersThrough.objects.filter(container=ci).update(container=target)
                    ci.delete()
        self.stdout.write(self.style.SUCCESS(f"Fixed {len(changes)} image ID(s)."))
