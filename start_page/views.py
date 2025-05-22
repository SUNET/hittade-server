from collections import Counter
from django.shortcuts import render
from django.http import HttpRequest

from servers.models import Host

def start_page(request: HttpRequest):
    if not request.user.is_authenticated:
        return render(request, "start_page/public.html")

    context = {}

    if request.user.has_perm("servers.view_host"):
        hosts = Host.objects.all()

        os_names = []
        for host in Host.objects.order_by("-id").distinct():
            if (ld := host.hostdetails_set.first()):
                os_names.append(f"{ld.osname}-{ld.osrelease}")
        
        most_common_os, most_common_os_count = Counter(os_names).most_common(1)[0]

        os_count = len(list(set(os_names)))

        packages = []
        for host in Host.objects.order_by("-id").distinct():
            for package in host.hostpackages_set.first().packages.all():
                packages.append(f"{package.name}-{package.version}")

        most_common_package, most_common_package_count = Counter(packages).most_common(1)[0]

        package_count = len(list(set(packages)))

        context["servers"] = {
            "count": len(hosts),
            "recents": hosts.order_by("-id")[:10],
            "os_count": os_count,
            "most_common_os": most_common_os,
            "most_common_os_count": most_common_os_count,
            "package_count": package_count,
            "most_common_package": most_common_package,
            "most_common_package_count": most_common_package_count,
        }

    return render(
        request=request, 
        template_name="start_page/authenticated.html",
        context=context
    )
