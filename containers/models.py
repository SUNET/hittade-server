from django.db import models

# Create your models here.

class ContainerTags(models.Model):
    tag = models.CharField(max_length=255)
    fullname = models.CharField(max_length=255)
    class Meta:
        indexes = [
            models.Index(fields=["tag"]),
            models.Index(fields=["fullname"]),
        ]

class ContainerPackage(models.Model):
    provider = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=255)

    class Meta:
        unique_together = ("name", "version", "provider"),
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["name", "version"]),
            models.Index(fields=["name", "version","provider" ]),
        ]

class ContainerBase(models.Model):
    cid = models.CharField(max_length=255)
    cname = models.CharField(max_length=255)
    osname = models.CharField(max_length=255, null=True)
    osversionid = models.CharField(max_length=255, null=True)
    time = models.DateTimeField()
    ctime = models.DateTimeField()
    tags = models.ManyToManyField(ContainerTags)
    packages = models.ManyToManyField(ContainerPackage)

    class Meta:
        indexes = [
            models.Index(fields=["cid"]),
            models.Index(fields=["osname", "osversionid"]),
        ]    

