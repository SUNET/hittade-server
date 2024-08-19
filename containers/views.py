from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required

from .forms import SearchForm
from .models import Container, ContainerPackage, ContainerTags, ContainerBase
# Create your views here.


def index(request):
    return render(request, "containers/search.html")


def package(request, pk):
    return render(request, "containers/search.html")


def cbase(request, cid: str=""):
    return render(request, "containers/search.html")



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