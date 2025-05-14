# Create your models here.
from django.db import models


class Host(models.Model):
    id: int
    hostname = models.CharField(max_length=200)

    class Meta:
        indexes = [
            models.Index(fields=["hostname"]),
        ]


class HostDetails(models.Model):
    id: int
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    time = models.DateTimeField()
    domain = models.CharField(max_length=255, null=True, blank=True)
    osname = models.CharField(max_length=100, null=True, blank=True)
    osrelease = models.CharField(max_length=255, null=True, blank=True)
    rkr = models.CharField(max_length=255, null=True, blank=True)
    cosmosrepourl = models.CharField(max_length=255, null=True, blank=True)
    ipv4 = models.CharField(max_length=255, null=True, blank=True)
    ipv6 = models.CharField(max_length=300, null=True, blank=True)
    fail2ban = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["domain"]),
            models.Index(fields=["osname", "osrelease"]),
            models.Index(fields=["ipv4"]),
            models.Index(fields=["ipv6"]),
            models.Index(fields=["fail2ban"]),
        ]
        ordering = ("-time",)


class Package(models.Model):
    id: int
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=255)

    class Meta:
        unique_together = ("name", "version")
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["name", "version"]),
        ]


class HostPackages(models.Model):
    id: int
    time = models.DateTimeField()
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    packages = models.ManyToManyField(Package)


class ConfigValues(models.Model):
    id: int
    ctype = models.CharField(max_length=255)
    name = models.CharField()
    value = models.CharField()

    class Meta:
        unique_together = ("ctype", "name", "value")
        indexes = [
            models.Index(fields=["ctype", "name"]),
            models.Index(fields=["ctype", "name", "value"]),
        ]


class HostConfigs(models.Model):
    id: int
    time = models.DateTimeField()
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    configs = models.ManyToManyField(ConfigValues)


class ContainerImage(models.Model):
    id: int
    image = models.CharField(max_length=100)
    imageid = models.CharField(max_length=255)

    class Meta:
        indexes = [
            models.Index(fields=["image"]),
            models.Index(fields=["imageid"]),
        ]


class HostContainers(models.Model):
    id: int
    time = models.DateTimeField()
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    containers = models.ManyToManyField(
        ContainerImage,
        through="HostContainersThrough",
        through_fields=("hc", "container"),
    )


class HostContainersThrough(models.Model):
    id: int
    hc = models.ForeignKey(HostContainers, on_delete=models.CASCADE)
    container = models.ForeignKey(ContainerImage, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
