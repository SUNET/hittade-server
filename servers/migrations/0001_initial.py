# Generated by Django 5.0.7 on 2024-07-30 16:02

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ContainerImage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("image", models.CharField(max_length=100)),
                ("imageid", models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name="Host",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("hostname", models.CharField(max_length=200)),
            ],
        ),
        migrations.CreateModel(
            name="HostContainers",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("time", models.DateTimeField()),
                ("containers", models.ManyToManyField(to="servers.containerimage")),
                (
                    "host",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="servers.host"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="HostDetails",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("time", models.DateTimeField()),
                ("domain", models.CharField(blank=True, max_length=255, null=True)),
                ("osname", models.CharField(blank=True, max_length=100, null=True)),
                ("osrelease", models.CharField(blank=True, max_length=255, null=True)),
                ("rkr", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "cosmosrepourl",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("ipv4", models.CharField(blank=True, max_length=255, null=True)),
                ("ipv6", models.CharField(blank=True, max_length=300, null=True)),
                (
                    "host",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="servers.host"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Package",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("version", models.CharField(max_length=255)),
            ],
            options={
                "unique_together": {("name", "version")},
            },
        ),
        migrations.CreateModel(
            name="HostPackages",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("time", models.DateTimeField()),
                (
                    "host",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="servers.host"
                    ),
                ),
                ("packages", models.ManyToManyField(to="servers.package")),
            ],
        ),
    ]
