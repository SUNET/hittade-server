from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from containers.models import ContainerTags, ContainerBase, ContainerPackage
from containers.utils import update_latest_containers
import orjson
import pathlib
from datetime import datetime
from pprint import pprint

# DB cache for runtime
PACKAGES = {}


class Command(BaseCommand):
    help = "Adds container image details to the database."

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)

    def handle(self, *args, **options):
        filename = options["filename"]
        # This is the time data is entered in the database.
        itime = datetime.now()
        p = pathlib.Path(filename)
        if p.is_dir():
            # We have a directory of files.
            for filename in p.rglob("*.json"):
                self.add_container_images(filename, itime)
        else:
            self.add_container_images(filename, itime)

    def add_container_images(self, filename, itime):
        "Parses and stores data on database."
        self.stdout.write(self.style.SUCCESS(f"Parsing {filename}"))
        # These variables to be used for speedup
        global PACKAGES


        # Using orjson to faster parsing of the JSON data
        with open(filename, "r") as fobj:
            file_text = fobj.read()
            try:
                maindata = orjson.loads(file_text)
            except orjson.JSONDecodeError:
                self.stderr.write(self.style.ERROR(f"Invalid JSON in file: {filename}"))
                return

        data = list(maindata.values())[0]

        try:
            image_data = data["inspect_data"][0]
            cid = image_data["Id"]
            ctime = image_data["Created"]
            repotags = image_data["RepoTags"]
        except KeyError:
            self.stderr.write(self.style.ERROR(f"Invalid input in file: {filename}"))
            return
        # The OS details maybe missing in the JSON files.
        #
        os_data = data.get("os_hash", {})
        osname = os_data.get("NAME", "Unknown")
        osversion = os_data.get("VERSION_ID", "Unknown")

        # The first tag defines the container name
        fulltag_1 = repotags[0]
        cname = fulltag_1.split(":")[0]

        itags = ContainerTags.objects.filter(fullname=fulltag_1)

        # Verify if we already saved this data based on container ID and the full name.
        cb = ContainerBase.objects.filter(cid=cid, tags__in=itags).first()
        if cb:
            # We already have this data, so skip
            self.stdout.write(f"Skipping {cid} from file {filename}.")
            return


        # Save the containerbase details
        cb = ContainerBase(cid=cid, cname=cname, osname=osname, osversionid=osversion, time=itime, ctime=ctime)
        cb.save()
        # We can now update the warm cache for latest containers
        update_latest_containers(cname, cb.id, cb.ctime)

        tags = []
        # Save the tags
        for fulltag in repotags:
            words = fulltag.split(":")
            tag = words[0]
            ct, _ = ContainerTags.objects.get_or_create(tag=tag, fullname=fulltag)
            tags.append(ct)
        cb.tags.add(*tags)
        cb.save()

        packages = []
        # Save the packages
        for package_data in data.get("pkg_list", []):
            name = package_data["package"]
            version = package_data["version"]
            if not name or not version:
                continue
            provider = package_data["provider"]
            unique_package_key = f"{name}:{version}:{provider}"
            if unique_package_key in PACKAGES:
                # We've already seen this package
                cp = PACKAGES[unique_package_key]
            else:
                cp, _ = ContainerPackage.objects.get_or_create(
                    name=name, version=version, provider=provider
                )
                PACKAGES[unique_package_key] = cp
            packages.append(cp)
        cb.packages.add(*packages)
        cb.save()
        self.stdout.write(self.style.SUCCESS(f"Successfully added {filename}"))