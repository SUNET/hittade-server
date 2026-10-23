from django.urls import path

from . import views

app_name = "servers"
urlpatterns = [
    path("", views.index, name="index"),
    # path("add/", views.add, name="add"),
    path("package/<int:pk>", views.package, name="package"),
    path("host/<int:pk>", views.host, name="host"),
    path("search/", views.search, name="search"),
    path("hosts", views.hosts, name="hosts"),
    path("running-containers", views.running_containers, name="running_containers"),
    path("logout", views.logout_view, name="logout"),
]
