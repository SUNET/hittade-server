"""
URL configuration for hittade project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from debug_toolbar.toolbar import debug_toolbar_urls
from django.contrib import admin
from django.urls import include, path

from api.views import api
from start_page.views import start_page

urlpatterns = [
    path("", start_page, name="start_page"),
    path("admin/", admin.site.urls),
    path("servers/", include("servers.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("containers/", include("containers.urls")),
    path("api/", api.urls),
] + debug_toolbar_urls()
