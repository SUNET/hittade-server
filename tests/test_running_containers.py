from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from test_container_links import T0, scan, user_with

from containers.models import ContainerBase, ContainerPackage
from servers.models import Host

URL = reverse("servers:running_containers")


def image(cid, packages):
    "Saves an imported image with packages, a list of (name, version)."
    cb = ContainerBase.objects.create(cid=cid, cname=cid, time=T0, ctime=T0)
    for name, version in packages:
        p, _ = ContainerPackage.objects.get_or_create(
            name=name, version=version, provider="deb"
        )
        cb.packages.add(p)


class RunningContainersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        image("sha256:old", [("openssl", "1.1.1"), ("bash", "5.1")])
        image("sha256:new", [("openssl", "3.0.2"), ("libssl3", "3.0.2")])
        cls.web = Host.objects.create(hostname="web1")
        cls.db = Host.objects.create(hostname="db1")
        cls.ci = Host.objects.create(hostname="ci1")
        scan(cls.web, T0, [("app:1", "sha256:new", "app"), ("x:1", "sha256:unknown", "x")])
        scan(cls.db, T0, [("db:1", "sha256:old", "db")])
        # ci1 ran sha256:new earlier, but its latest scan only has an unknown image.
        scan(cls.ci, T0, [("app:1", "sha256:new", "old-app")])
        scan(cls.ci, T0 + timedelta(hours=1), [("y:1", "sha256:unknown2", "y")])
        cls.user = user_with("view_host", "view_containerbase")

    def search(self, text, user=None):
        self.client.force_login(user or self.user)
        return self.client.get(URL, {"search": text})

    def rows(self, response):
        return [
            (r["host"].hostname, r["name"], r["package"], r["version"])
            for r in response.context["rows"]
        ]

    def test_name_matches_substring_on_latest_scans(self):
        response = self.search("ssl")
        self.assertEqual(
            self.rows(response),
            [
                ("db1", "db", "openssl", "1.1.1"),
                ("web1", "app", "libssl3", "3.0.2"),
                ("web1", "app", "openssl", "3.0.2"),
            ],
        )
        self.assertContains(response, reverse("servers:host", args=[self.web.id]))
        self.assertContains(response, reverse("containers:cbase", args=["sha256:new"]))

    def test_second_word_matches_version_substring(self):
        response = self.search("openssl 3.0")
        self.assertEqual(self.rows(response), [("web1", "app", "openssl", "3.0.2")])

    def test_reports_containers_without_imported_image(self):
        response = self.search("bash")
        self.assertEqual(self.rows(response), [("db1", "db", "bash", "5.1")])
        self.assertContains(
            response,
            "2 running containers on 2 hosts have no imported image, so they were not searched.",
        )

    def test_no_match(self):
        response = self.search("nginx")
        self.assertEqual(self.rows(response), [])
        self.assertContains(response, 'No running container has a package matching "nginx".')

    def test_empty_search_shows_only_the_form(self):
        response = self.search("")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "No running container")

    def test_needs_both_permissions(self):
        for codename in ("view_host", "view_containerbase"):
            response = self.search("ssl", user_with(codename))
            self.assertEqual(response.status_code, 403)
