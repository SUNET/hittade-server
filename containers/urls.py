from django.urls import path

from . import views

app_name = "containers"
urlpatterns = [
    # /containers/ is the list of images with the OS filter; the same view
    # as /containers/containers.
    path("", views.containers, name="index"),
    path("package/<int:pk>", views.package, name="package"),
    path("search/", views.search, name="search"),
    path("cbase/<str:cid>", views.cbase, name="cbase"),
    path("containers", views.containers, name="containers"),
]