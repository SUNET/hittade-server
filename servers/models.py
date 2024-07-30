# Create your models here.
import datetime
from django.db import models
from django.utils import timezone


class Host(models.Model):
    hostname = models.CharField(max_length=200)


class HostDetails(models.Model):
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    time = models.DateTimeField()
    domain = models.CharField(max_length=255, null=True, blank=True)
    osname = models.CharField(max_length=100, null=True, blank=True)
    osrelease = models.CharField(max_length=255, null=True, blank=True)
    rkr = models.CharField(max_length=255, null=True, blank=True)
    cosmosrepourl = models.CharField(max_length=255, null=True, blank=True)
    ipv4 = models.CharField(max_length=255, null=True, blank=True)
    ipv6 = models.CharField(max_length=300, null=True, blank=True)


class Package(models.Model):
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=255)

    class Meta:
        unique_together = ("name", "version")


class HostPackages(models.Model):
    time = models.DateTimeField()
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    packages = models.ManyToManyField(Package)


class ContainerImage(models.Model):
    image = models.CharField(max_length=100)
    imageid = models.CharField(max_length=255)


class HostContainers(models.Model):
    time = models.DateTimeField()
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    containers = models.ManyToManyField(ContainerImage())
