from django.urls import path

from . import views

app_name = "servers"
urlpatterns = [
    path("", views.index, name="index"),
    path("add/", views.add, name="add"),
    path("package/<int:pk>", views.package, name="package"),
    path("search/", views.search, name="search"),]