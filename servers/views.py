from django.shortcuts import render

# Create your views here.
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db.models import OuterRef, Subquery
from .forms import SearchForm
from .models import Package, Host, HostPackages, HostContainers, HostDetails


def index(request):
    return render(request, "servers/index.html")


@csrf_exempt
def add(request):
    if request.method == "POST":
        return HttpResponse("received a POST request")
    return HttpResponse("h")

@login_required
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
def host(request, pk):
    host = Host.objects.get(pk=pk)
    host_packages = HostPackages.objects.filter(host=host).order_by("-time")[0]
    host_containers = HostContainers.objects.filter(host=host).order_by("-time")[0]
    containers = host_containers.containers.all()
    details = HostDetails.objects.filter(host=host).order_by("-time")[0]

    return render(
        request,
        "servers/host.html",
        {
            "host": host,
            "packages": host_packages.packages.all(),
            "containers": containers,
            "details": details,
        },
    )

@login_required
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
def hosts(request):
    "To show list of all hosts."
    hosts = Host.objects.all().order_by("hostname")
    return render (request, "servers/hosts.html", {"hosts": hosts})
    