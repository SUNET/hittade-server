from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import OuterRef, Subquery
from django.core.paginator import Paginator
import datetime
import pytz
from .forms import SearchForm
from .models import ContainerPackage, ContainerTags, ContainerBase
from .utils import latest_containers
# Create your views here.


@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
def index(request):
    return render(request, "containers/search.html")


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

    return render(
        request,
        "containers/package.html",
        {"package": package, "data": result},
    ) 


@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
def cbase(request, cid):
    "Shows details of a specific container image based on it's container ID."
    try:
        cb = ContainerBase.objects.filter(cid=cid)[0]
    except ContainerBase.DoesNotExist:
        return render(request, "containers/container.html", {"error": "Container not found."})
    return render(request, "containers/container.html", {"cb": cb, "tags": cb.tags.all(), "packages": cb.packages.all()})

@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
def containers(request):
    cbs = ContainerBase.objects.prefetch_related("tags").order_by("-ctime")
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
    return render(request, "containers/containers.html", {"cbs": result})


@login_required
@permission_required("containers.view_containerbase", raise_exception=True)
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

    return render(
        request, "containers/search.html", {"form": form, "data": data, "text": text}
    )