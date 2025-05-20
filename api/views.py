from datetime import datetime
from pprint import pprint
from typing import List, Optional

from ninja import NinjaAPI, Schema
from ninja.pagination import PageNumberPagination, paginate

from servers.models import Host, HostConfigs, HostContainers, HostDetails, HostPackages

api = NinjaAPI()


class HostSchema(Schema):
    id: int
    hostname: str


class HostDetailsSchema(Schema):
    time: datetime
    domain: Optional[str]
    osname: str
    osrelease: str
    rkr: str
    cosmosrepourl: str
    ipv4: Optional[str]
    ipv6: Optional[str]
    fail2ban: bool


class PackageSchema(Schema):
    id: int
    name: str
    version: str


class ServerContainerSchema(Schema):
    image: str
    imageid: str


class HostConfigurationSchema(Schema):
    ctype: str
    name: str
    value: str


class CombinedHostSchema(Schema):
    host: HostSchema
    details: HostDetailsSchema
    packages: List[PackageSchema]
    containers: List[ServerContainerSchema]
    configs: List[HostConfigurationSchema]


@api.get("/hosts", response=List[HostSchema])
@paginate(PageNumberPagination)
def list_hosts(request):
    return Host.objects.all().order_by("hostname")


@api.get("/host/{host_id}", response=CombinedHostSchema)
def host_details(request, host_id):
    host = Host.objects.get(pk=host_id)
    host_packages = HostPackages.objects.filter(host=host).order_by("-time")[0]
    host_configs = HostConfigs.objects.filter(host=host).order_by("-time")[0]
    host_containers = HostContainers.objects.filter(host=host).order_by("-time")[0]
    cdetails = host_containers.hostcontainersthrough_set.all().prefetch_related()
    details = HostDetails.objects.filter(host=host).order_by("-time")[0]
    cd = [c for c in host_configs.configs.all()]

    return {
        "host": HostSchema.model_validate(host),
        "details": HostDetailsSchema.model_validate(details),
        "packages": [
            PackageSchema.model_validate(p) for p in host_packages.packages.all()
        ],
        "containers": [
            ServerContainerSchema.model_validate(hc)
            for hc in host_containers.containers.all()
        ],
        "configs": [HostConfigurationSchema.model_validate(c) for c in cd],
    }
