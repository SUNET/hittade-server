from typing import Any
from django.core.management.base import BaseCommand, CommandError
from servers.models import Host, Package, HostDetails
from django.utils.dateparse import parse_datetime
import json
from cProfile import Profile

class Command(BaseCommand):
    help = "Adds host details to the database using factor."

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)

    def _handle(self, *args: Any, **options: Any) -> str | None:
        profiler = Profile()
        profiler.runcall(self._handle, *args, **options)
        profiler.dump_stats("addhost.prof")

    def handle(self, *args, **options):
        filename = options["filename"]
        with open(filename, "r") as fobj:
            data = json.load(fobj)

        hostname = data["name"]
        # Easier to work with values
        values = data["values"]
        created_str = data["timestamp"]
        created_at = parse_datetime(created_str)
        system_packages = values["packages"][0]
        domain = values.get("domain", None)
        osname = values["os"]["name"]
        osrelease = values["os"]["release"]["full"]
        rkr = values["running-kernel"]["kernel-release"]
        cosmosrepourl = values.get("cosmos_repo_origin_url", None)
        ipv4 = values.get("ipaddress", None)
        ipv6 = values.get("ipaddress6", None)
        # First get/save the host
        host, _ = Host.objects.get_or_create(
            hostname=hostname,
            domain=domain,
            osname=osname,
            osrelease=osrelease,
            rkr=rkr,
            cosmosrepourl=cosmosrepourl,
            ipv4=ipv4,
            ipv6=ipv6
        )

        hdetails = HostDetails(host=host, time=created_at)
        hdetails.save()
        ps = []
        # Now for each package, get/save the details
        for p in system_packages:
            try:
                package, _ = Package.objects.get_or_create(name=p["name"], version=p["version"])
                ps.append(package)
            except Exception as e:
                print(e)
                continue
        

            # Now we have the package
        hdetails.packages.add(*ps)
        # Now save the host details
        hdetails.save()

        self.stdout.write(self.style.SUCCESS(f"Successfully added {hostname}"))
