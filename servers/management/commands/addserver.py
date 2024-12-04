from django.core.management.base import BaseCommand
from servers.models import Host, Package, HostDetails
from lib4sbom.parser import SBOMParser
from django.utils.dateparse import parse_datetime


class Command(BaseCommand):
    help = "Adds server details to the database"

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)

    def handle(self, *args, **options):
        filename = options["filename"]
        parser = SBOMParser()
        parser.parse_file(filename)
        hostname = parser.get_document()["name"]
        created_str = parser.get_document()["created"]
        created_at = parse_datetime(created_str)
        system_packages = parser.get_packages()
        # First get/save the host
        try:
            host = Host.objects.get(hostname=hostname)
        except Host.DoesNotExist:
            host = Host(hostname=hostname)
            host.save()

        # Now for each package, get/save the details

        hdetails = HostDetails(host=host, time=created_at)
        hdetails.save()
        for p in system_packages:
            try:
                package = Package.objects.get(name=p["name"], version=p["version"])
            except Package.DoesNotExist:
                package = Package(name=p["name"], version=p["version"])
                package.save()
            except KeyError:
                continue
            # Now we have the package
            hdetails.packages.add(package)
        # Now save the host details
        hdetails.save()

        self.stdout.write(self.style.SUCCESS(f"Successfully added {hostname}"))
