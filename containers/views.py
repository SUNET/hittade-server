from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import F, OuterRef, Subquery
from django.shortcuts import redirect, render

from hittade.downloads import json_download, wants_json
from servers.models import HostContainers, HostContainersThrough

from .forms import SearchForm
from .models import ContainerBase, ContainerPackage, ContainerTags
from .utils import latest_containers

# Create your views here.


@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
def index(request):
    return redirect(search)

@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
def package(request, pk):
    package = ContainerPackage.objects.get(pk=pk)
    latest = latest_containers()
    cbs = ContainerBase.objects.filter(packages=package, id__in=latest).prefetch_related()

    # Now construct the data
    result = []
    for cb in cbs:
        data = {}
        for tag in cb.tags.all():
            data["fullname"] = tag.fullname
            data["cid"] = cb.cid
        result.append(data)

    if wants_json(request):
        return json_download(
            {
                "package": {
                    "name": package.name,
                    "version": package.version,
                    "provider": package.provider,
                },
                "containers": result,
            },
            "containers-with-package",
            package.name,
            package.version,
        )
    return render(
        request,
        "containers/package.html",
        {
            "title": "Package details",
            "package": package, 
            "data": result,
            "download": True,
        },
    ) 


@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
def cbase(request, cid):
    "Shows details of a specific container image based on it's container ID."
    cb = ContainerBase.objects.filter(cid=cid).first()
    if cb is None:
        return render(
            request,
            "containers/container.html",
            {"error": "Container not found."},
            status=404,
        )

    # Hosts whose latest docker ps shows a container running this image, only
    # for users who can see the servers.
    running = []
    if request.user.has_perm("servers.view_host"):
        latest_hc = (
            HostContainers.objects.filter(host=OuterRef("hc__host"))
            .order_by("-time")
            .values("id")[:1]
        )
        running = (
            HostContainersThrough.objects.filter(container__imageid=cid)
            .annotate(latest_hc=Subquery(latest_hc))
            .filter(hc_id=F("latest_hc"))
            .select_related("hc__host")
            .order_by("hc__host__hostname", "name")
        )

    tags = cb.tags.all()
    packages = cb.packages.all()
    if wants_json(request):
        data = {
            "cid": cb.cid,
            "name": cb.cname,
            "tags": [t.fullname for t in tags],
            "osname": cb.osname,
            "osversionid": cb.osversionid,
            "created_at": cb.ctime,
            "scanned_at": cb.time,
            "packages": [
                {"name": p.name, "version": p.version, "provider": p.provider}
                for p in packages
            ],
        }
        if request.user.has_perm("servers.view_host"):
            data["running_on"] = [
                {
                    "host": hc.hc.host.hostname,
                    "host_id": hc.hc.host.id,
                    "container": hc.name,
                    "seen_at": hc.hc.time,
                }
                for hc in running
            ]
        # The image ID without "sha256:", shortened like docker does.
        return json_download(data, "container", cb.cname, cb.cid.split(":")[-1][:12])

    return render(
        request, 
        "containers/container.html", 
        {
            "title": "Container details",
            "cb": cb, 
            "tags": tags, 
            "packages": packages,
            "running": running,
            "download": True,
        }
    )

@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
def containers(request):
    cbs = ContainerBase.objects.prefetch_related("tags").order_by("-ctime")
    if wants_json(request):
        # All of them, not one page.
        return json_download(
            {
                "containers": [
                    {
                        "cid": cb.cid,
                        "tags": [t.fullname for t in cb.tags.all()],
                        "created_at": cb.ctime,
                    }
                    for cb in cbs
                ]
            },
            "containers",
        )
    paginator = Paginator(cbs, 50)

    page_number = request.GET.get("page", 1)
    page_number = int(page_number)
    if page_number < 1:
        page_number = 1
    elif page_number > paginator.num_pages:
        page_number = paginator.num_pages

    page = paginator.page(page_number)
    result = []
    for cb in page.object_list:
        result.append({"fullname": cb.tags.all()[0].fullname, "cid": cb.cid})
    
    return render(
        request, 
        "containers/containers.html", 
        {
            "title": "All container images",
            "cbs": result, 
            "page": page,
            "download": True,
        }
    )


@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
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
                    packages = ContainerPackage.objects.filter(name__icontains=package_name)
                else:
                    package_version = words[1]
                    packages = ContainerPackage.objects.filter(
                        name__icontains=package_name, version__icontains=package_version
                    )
                data["packages"] = packages
            else:
                search_text = form.data["search"]
                search_text = search_text.strip()
                container_tags  = ContainerTags.objects.filter(fullname__icontains=search_text)
                container_bases = ContainerBase.objects.filter(tags__in=container_tags)
                # Now create the list of containers with proper tags.
                # There can be more than one container+tag combination with same value.
                results = []
                for cb in container_bases:
                    result = {}
                    for tag in cb.tags.all():
                        result["fullname"] = tag.fullname
                        result["cid"] = cb.cid
                    results.append(result)

                data["cbs"] = results
    # if a GET (or any other method) we'll create a blank form
    else:
        form = SearchForm()

    if data and wants_json(request):
        result = {"search": text, "type": stype}
        if "packages" in data:
            result["packages"] = [
                {"id": p.id, "name": p.name, "version": p.version, "provider": p.provider}
                for p in data["packages"]
            ]
        else:
            result["containers"] = data["cbs"]
        return json_download(result, "container-search", stype, text)

    return render(
        request, 
        "containers/search.html", 
        {
            "title": "Container search",
            "form": form, 
            "data": data, 
            "text": text,
            "stype": stype,
            "download": bool(data),
        }
    )