from django.urls import path

from . import views

app_name = "servers"
urlpatterns = [
    path("", views.search, name="index"),
    #path("add/", views.add, name="add"),
    path("package/<int:pk>", views.package, name="package"),
    path("host/<int:pk>", views.host, name="host"),
    path("search/", views.search, name="search"),
    path("hosts", views.hosts, name="hosts"),
]
