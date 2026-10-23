import logging

import redis
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import OuterRef, Subquery

# Create your views here.
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from containers.models import ContainerBase

from .forms import SearchForm
from .models import (
    ConfigValues,
    Host,
    HostConfigs,
    HostContainers,
    HostDetails,
    HostPackages,
    Package,
)
from .utils import (
    generate_host_configurations_dict,
    get_osdetails,
    osdetails_from_db,
    running_containers_with_package,
)

logger = logging.getLogger(__name__)


def logout_view(request):
    # FIXME: Handle CSRF token validation
    logout(request)
    return redirect("/")


@login_required
@permission_required("servers.view_host", raise_exception=True)
def package(request, pk):
    package = Package.objects.get(pk=pk)
    latest_host_details_subquery = (
        HostPackages.objects.filter(host=OuterRef("pk"))
        .order_by("-time")
        .values("pk")[:1]
    )
    hosts_with_package = Host.objects.filter(
        hostpackages__pk__in=Subquery(latest_host_details_subquery),
        hostpackages__packages=package,
    ).distinct()
    return render(
        request,
        "servers/package.html",
        {
            "title": f"Package: {package.name} - {package.version}",
            "package": package,
            "hosts": hosts_with_package,
        },
    )


@login_required
@permission_required("servers.view_host", raise_exception=True)
def host(request, pk):
    host = Host.objects.get(pk=pk)
    host_packages = HostPackages.objects.filter(host=host).order_by("-time")[0]
    try:
        host_configs = HostConfigs.objects.filter(host=host).order_by("-time")[0]
    except IndexError:
        host_configs = []
    host_containers = HostContainers.objects.filter(host=host).order_by("-time")[0]
    cdetails = host_containers.hostcontainersthrough_set.select_related("container")
    # Image IDs of the running containers that were imported as container images.
    imported_cids = set(
        ContainerBase.objects.filter(
            cid__in={hc.container.imageid for hc in cdetails}
        ).values_list("cid", flat=True)
    )
    details = HostDetails.objects.filter(host=host).order_by("-time")[0]

    if host_configs:
        config_from_db = host_configs.configs.all()
    else:
        config_from_db = []

    return render(
        request,
        "servers/host.html",
        {
            "title": host.hostname,
            "host": host,
            "packages": host_packages.packages.all(),
            "containers": cdetails,
            "imported_cids": imported_cids,
            "details": details,
            "configurations": generate_host_configurations_dict(config_from_db),
        },
    )


@login_required
@permission_required("servers.view_host", raise_exception=True)
def search(request):
    # if this is a POST request we need to process the form data
    data = {}
    text = ""
    stype = ""

    if request.method == "POST":
        # create a form instance and populate it with data from the request:
        form = SearchForm(request.POST)
        # check whether it's valid:
        if form.is_valid():
            # process the data in form.cleaned_data as required
            # ...
            # redirect to a new URL:
            text = form.data["search"]
            stype = form.data["stype"]
            if form.data["stype"] == "package":
                search_text = form.data["search"]
                words = search_text.split(" ")
                package_name = words[0]
                if len(words) == 1:
                    packages = Package.objects.filter(name__icontains=package_name)
                else:
                    package_version = words[1]
                    packages = Package.objects.filter(
                        name__icontains=package_name, version__icontains=package_version
                    )
                data["packages"] = packages
            else:
                search_text = form.data["search"]
                search_text = search_text.strip()
                hosts = Host.objects.filter(hostname__icontains=search_text)
                data["hosts"] = hosts
    # if a GET (or any other method) we'll create a blank form
    else:
        form = SearchForm()

    return render(
        request,
        "servers/search.html",
        {
            "title": "Search",
            "form": form,
            "data": data,
            "text": text,
            "stype": stype,
        },
    )


@login_required
@permission_required(
    ["servers.view_host", "containers.view_containerbase"], raise_exception=True
)
def running_containers(request):
    "Hosts with a running container that has the searched package."
    text = request.GET.get("search", "").strip()
    rows = []
    unknown = (0, 0)
    if text:
        # "openssl" matches the package name, "openssl 3.0" the version too.
        words = text.split()
        version = words[1] if len(words) > 1 else ""
        rows, unknown = running_containers_with_package(words[0], version)
    return render(
        request,
        "servers/running_containers.html",
        {
            "title": "Running containers",
            "text": text,
            "rows": rows,
            "unknown_containers": unknown[0],
            "unknown_hosts": unknown[1],
        },
    )


@login_required
@permission_required("servers.view_host", raise_exception=True)
def hosts(request):
    "To show list of all hosts."
    hosts = Host.objects.all().order_by("hostname")
    return render(request, "servers/hosts.html", {"title": "All hosts", "hosts": hosts})


@login_required
@permission_required("servers.view_host", raise_exception=True)
def index(request):
    try:
        osdetails = get_osdetails()
    except redis.RedisError:
        logger.warning("Redis unavailable, building the servers index from the database")
        osdetails = None
    if osdetails is None:
        # No cache yet (or redis was flushed/is down): use the database until
        # the next app restart rebuilds it (or run `warmservercache`).
        osdetails = osdetails_from_db()

    return render(
        request, "servers/index.html", {"title": "Servers", "osdetails": osdetails}
    )
