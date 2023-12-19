from django.shortcuts import render

# Create your views here.
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponseRedirect
from django.shortcuts import render

from .forms import PackageForm
from .models import Package, HostDetails, Host

def index(request):
    return HttpResponse("Hello, world. You're at the polls index.")

@csrf_exempt
def add(request):
    if request.method == "POST":
        return HttpResponse("received a POST request")
    return HttpResponse("h")

def package(request, pk):
    package = Package.objects.get(pk=pk)
    hosts ={hostdetails.host for hostdetails in  HostDetails.objects.filter(packages=package)}
    return render(request, "servers/package.html", {"package": package, "hosts": hosts})

def search(request):
    # if this is a POST request we need to process the form data
    data = {}
    if request.method == "POST":
        # create a form instance and populate it with data from the request:
        form = PackageForm(request.POST)
        # check whether it's valid:
        if form.is_valid():
            # process the data in form.cleaned_data as required
            # ...
            # redirect to a new URL:
            package_name = form.data["package_name"]
            package_version = form.data["package_version"]
            if not package_version:
                packages = Package.objects.filter(name__icontains=package_name)
            else:
                packages = Package.objects.filter(name__icontains=package_name, version__icontains=package_version)
            data["packages"] = packages
            print(f"LEN {packages}")


    # if a GET (or any other method) we'll create a blank form
    else:
        form = PackageForm()

    return render(request, "servers/search.html", {"form": form, "data": data})