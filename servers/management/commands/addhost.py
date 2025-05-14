import datetime
import pathlib

import orjson
import pytz
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from servers.models import (
    ConfigValues,
    ContainerImage,
    Host,
    HostConfigs,
    HostContainers,
    HostContainersThrough,
    HostDetails,
    HostPackages,
    Package,
)
from servers.utils import update_latest_hosts

# DB cache for runtime
PACKAGES = {}
CONTAINERS = {}
CONFIGVALUES = {}


class Command(BaseCommand):
    help = "Adds host details to the database using factor."

    def add_arguments(self, parser):
        parser.add_argument("filename", type=str)

    # def _handle(self, *args: Any, **options: Any) -> str | None:
    #     profiler = Profile()
    #     profiler.runcall(self._handle, *args, **options)
    #     profiler.dump_stats("addhost.prof")

    def handle(self, *args, **options):
        filename = options["filename"]
        if pathlib.Path(filename).is_dir():
            # We have a directory of files.
            for filename in pathlib.Path(filename).iterdir():
                if filename.suffix == ".json":
                    try:
                        self.add_host_details(str(filename))
                    except Exception as e:
                        self.stderr.write(
                            self.style.ERROR(
                                f"Error processing file: {filename}: {str(e)}"
                            )
                        )
        else:
            self.add_host_details(filename)

    def add_host_details(self, filename):
        "Parses and stores data on database."
        # These variables to be used for speedup
        global PACKAGES
        global CONTAINERS

        # Using orjson to faster parsing of the JSON data
        with open(filename, "r") as fobj:
            file_text = fobj.read()
            data = orjson.loads(file_text)

        try:
            hostname = ""
            if "name" in data:
                hostname = data["name"]
            else:
                if "ec2_metadata" in data:
                    if "hostname" in data["ec2_metadata"]:
                        hostname = data["ec2_metadata"]["hostname"]
                if not hostname:
                    raise KeyError("No hostname found.")
            # Easier to work with values
            if "values" in data:
                values = data["values"]
            else:
                values = data
            # FIXME: The timestamp is still missing in many files, generated on Debian 12.
            try:
                created_str = data["timestamp"]
                created_at = parse_datetime(created_str)
            except:
                created_at = datetime.datetime.now(datetime.timezone.utc).replace(
                    tzinfo=pytz.utc
                )
            system_packages = values["packages"][0]
            domain = values.get("domain", None)
            osname = values["os"]["name"]
            osrelease = values["os"]["release"]["full"]
            rkr = values["running-kernel"]["kernel-release"]
            cosmosrepourl = values.get("cosmos_repo_origin_url", None)
            ipv4 = values.get("ipaddress", None)
            ipv6 = values.get("ipaddress6", None)
            fail2ban_text = values.get("fail2ban_is_enabled", "no").lower().strip()
            if fail2ban_text == "no":
                fail2ban = False
            else:
                fail2ban = True

        except KeyError as e:
            self.stderr.write(
                self.style.ERROR(f"Invalid input in file: {filename} missing key {e}")
            )
            return
        # First get/save the host
        host, _ = Host.objects.get_or_create(
            hostname=hostname,
        )

        # First check if we already saved this data based on host and time
        hpackages = HostPackages.objects.filter(host=host, time=created_at).first()
        if hpackages:
            # We already have this data, so skip
            print(f"Skipping {hostname} at {created_at}.")
            return

        hpackages = HostPackages(host=host, time=created_at)

        hpackages.save()
        ps = []
        # Now for each package, get/save the details
        for p in system_packages:
            try:
                name = p["name"]
                version = p["version"]
                key_text = f"{name}:{version}"

                # We are using a dictionary for faster lookup of packages.
                if key_text in PACKAGES:
                    # We've already seen this package
                    package = PACKAGES[key_text]
                else:
                    package, _ = Package.objects.get_or_create(
                        name=name, version=version
                    )
                    PACKAGES[key_text] = package
                ps.append(package)
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"Error adding package {p} with error: {str(e)}")
                )
                continue

        # Now we have all the packages
        hpackages.packages.add(*ps)
        hpackages.save()

        # Save sshd configuration values from hosts
        hconfigs = HostConfigs(host=host, time=created_at)
        hconfigs.save()

        cs = []
        if "sshd_config" in values:
            config_values = values.get("sshd_config", {})
            for k, v in config_values.items():
                try:
                    key_text = f"sshd_config:{k}"
                    if key_text in CONFIGVALUES:
                        configvalue = CONFIGVALUES[key_text]
                    else:
                        configvalue, _ = ConfigValues.objects.get_or_create(
                            ctype="sshd_config", name=k, value=v
                        )
                        CONFIGVALUES[key_text] = configvalue

                    cs.append(configvalue)
                except Exception as e:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Error adding configuration {k} with {v} with error: {str(e)}"
                        )
                    )
                    continue
            # TODO: move this block outside of if when we have more configs
            # Now we have all the config values
            hconfigs.configs.add(*cs)
            hconfigs.save()

        # Save the running containers on the host
        hcontainers = HostContainers(host=host, time=created_at)
        hcontainers.save()

        for container in values.get("docker_ps", []):
            image = container["Image"]
            image_id = container.get("ImageId", "not_available")
            c, _ = ContainerImage.objects.get_or_create(image=image, imageid=image_id)
            # Save the container details
            hct = HostContainersThrough(
                hc=hcontainers, container=c, name=container["Names"]
            )
            hct.save()

        # Now save the host details
        hd = HostDetails.objects.create(
            host=host,
            time=created_at,
            domain=domain,
            osname=osname,
            osrelease=osrelease,
            rkr=rkr,
            cosmosrepourl=cosmosrepourl,
            ipv4=ipv4,
            ipv6=ipv6,
            fail2ban=fail2ban,
        )
        update_latest_hosts(hd.host.hostname, hd.id, hd.time)

        self.stdout.write(self.style.SUCCESS(f"Successfully added {hostname}"))
