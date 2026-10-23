from datetime import datetime

from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.pagination import LimitOffsetPagination, paginate
from ninja.security import APIKeyHeader

from servers.models import Host, HostConfigs, HostContainers, HostDetails, HostPackages

from .models import APIKey


class ApiKeyAuth(APIKeyHeader):
    param_name = "X-API-Key"

    def authenticate(self, request, key):
        if not key:
            return None
        try:
            api_key = APIKey.objects.get(key_hash=APIKey.hash_key(key), active=True)
        except APIKey.DoesNotExist:
            return None
        APIKey.objects.filter(pk=api_key.pk).update(last_used=timezone.now())
        return api_key


api = NinjaAPI(auth=ApiKeyAuth())


class HostSchema(Schema):
    id: int
    hostname: str


class HostDetailsSchema(Schema):
    time: datetime
    domain: str | None
    osname: str
    osrelease: str
    rkr: str
    cosmosrepourl: str
    ipv4: str | None
    ipv6: str | None
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
    packages: list[PackageSchema]
    containers: list[ServerContainerSchema]
    configs: list[HostConfigurationSchema]


@api.get("/hosts", response=list[HostSchema])
@paginate(LimitOffsetPagination)
def list_hosts(request):
    return Host.objects.all().order_by("hostname")


@api.get("/host/{host_id}/config", response=list[HostConfigurationSchema])
def get_host_config(request, host_id):
    """Returns only the host configuration entries."""
    host = Host.objects.get(pk=host_id)
    try:
        host_configs = HostConfigs.objects.filter(host=host).order_by("-time").first()
        cd = [c for c in host_configs.configs.all()]
    except IndexError:
        cd = []
    return [HostConfigurationSchema.model_validate(c) for c in cd]


@api.get("/host/{host_id}", response=CombinedHostSchema)
def host_details(request, host_id):
    host = Host.objects.get(pk=host_id)
    host_packages = HostPackages.objects.filter(host=host).order_by("-time")[0]
    try:
        host_configs = HostConfigs.objects.filter(host=host).order_by("-time")[0]
    except IndexError:
        host_configs = []
    host_containers = HostContainers.objects.filter(host=host).order_by("-time")[0]
    details = HostDetails.objects.filter(host=host).order_by("-time")[0]
    if host_configs:
        cd = [c for c in host_configs.configs.all()]
    else:
        cd = []

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
