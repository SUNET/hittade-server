import json
from typing import Any, DefaultDict

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import OuterRef, Subquery

# Create your views here.
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from .forms import SearchForm
from .models import Host, HostContainers, HostDetails, HostPackages, Package
from .utils import get_osdetails


def index(request):
    return render(request, "servers/index.html")


def logout_view(request):
    # FIXME: Handle CSRF token validation
    logout(request)
    return redirect(index)


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
        {"package": package, "hosts": hosts_with_package},
    )


@login_required
@permission_required("servers.view_host", raise_exception=True)
def host(request, pk):
    host = Host.objects.get(pk=pk)
    host_packages = HostPackages.objects.filter(host=host).order_by("-time")[0]
    host_containers = HostContainers.objects.filter(host=host).order_by("-time")[0]
    cdetails = host_containers.hostcontainersthrough_set.all().prefetch_related()
    details = HostDetails.objects.filter(host=host).order_by("-time")[0]

    return render(
        request,
        "servers/host.html",
        {
            "host": host,
            "packages": host_packages.packages.all(),
            "containers": cdetails,
            "details": details,
        },
    )


@login_required
@permission_required("servers.view_host", raise_exception=True)
def search(request):
    # if this is a POST request we need to process the form data
    data = {}
    text = ""
    if request.method == "POST":
        # create a form instance and populate it with data from the request:
        form = SearchForm(request.POST)
        # check whether it's valid:
        if form.is_valid():
            # process the data in form.cleaned_data as required
            # ...
            # redirect to a new URL:
            text = form.data["search"]
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
        request, "servers/search.html", {"form": form, "data": data, "text": text}
    )


@login_required
@permission_required("servers.view_host", raise_exception=True)
def hosts(request):
    "To show list of all hosts."
    hosts = Host.objects.all().order_by("hostname")
    return render(request, "servers/hosts.html", {"hosts": hosts})


@login_required
@permission_required("servers.view_host", raise_exception=True)
def index2(request):
    # osdetails: dict[Any, Any] = get_osdetails()
    # # HACK: To stop any error on the view for missing cache
    # if not osdetails:
    # osdetails = {}
    # data = {}
    # for k, v in osdetails.items():
    # data[k.decode("utf-8")] = json.loads(v)
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    print(ip)
    data = DefaultDict(list)
    hosts_with_all_details = (
        Host.objects.order_by("-id").distinct().prefetch_related("hostdetails_set")
    )
    for host in hosts_with_all_details:
        ld = host.hostdetails_set.first()  # pyright: ignore
        osdetails = f"{ld.osname}-{ld.osrelease}"
        data[osdetails].append((host.hostname, host.id))

    return render(request, "servers/index2.html", {"osdetails": dict(data)})
