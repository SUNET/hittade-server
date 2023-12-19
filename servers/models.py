# Create your models here.
import datetime
from django.db import models
from django.utils import timezone


class Host(models.Model):
    hostname = models.CharField(max_length=200)
    domain = models.CharField(max_length=255, null=True, blank=True)
    osname = models.CharField(max_length=100, null=True, blank=True)
    osrelease = models.CharField(max_length=255, null=True, blank=True)
    rkr = models.CharField(max_length=255, null=True, blank=True)
    cosmosrepourl = models.CharField(max_length=255, null=True, blank=True)
    


class Package(models.Model):
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=255)

    class Meta:
        unique_together = ("name", "version")


class HostDetails(models.Model):
    time = models.DateTimeField(auto_now_add=True)
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    packages = models.ManyToManyField(Package)