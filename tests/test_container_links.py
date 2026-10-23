from datetime import UTC, datetime, timedelta

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from containers.models import ContainerBase
from servers.models import (
    ContainerImage,
    Host,
    HostContainers,
    HostContainersThrough,
    HostDetails,
    HostPackages,
)

T0 = datetime(2026, 10, 1, tzinfo=UTC)
CID = "sha256:aaaa"


def scan(host, when, images):
    "Saves one docker ps snapshot of host: images is a list of (image, imageid, name)."
    hc = HostContainers.objects.create(host=host, time=when)
    for image, imageid, name in images:
        c, _ = ContainerImage.objects.get_or_create(image=image, imageid=imageid)
        HostContainersThrough.objects.create(hc=hc, container=c, name=name)


def user_with(*codenames):
    user = User.objects.create_user(username="-".join(codenames) or "none")
    user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
    return user


class ContainerLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ContainerBase.objects.create(cid=CID, cname="app", time=T0, ctime=T0)
        cls.web = Host.objects.create(hostname="web1")
        cls.db = Host.objects.create(hostname="db1")
        for host in (cls.web, cls.db):
            HostDetails.objects.create(host=host, time=T0)
            HostPackages.objects.create(host=host, time=T0)
        scan(cls.web, T0, [("app:1", CID, "app"), ("other:1", "sha256:bbbb", "other")])
        # db1 ran the image earlier, but its latest scan does not.
        scan(cls.db, T0, [("app:1", CID, "old-app")])
        scan(cls.db, T0 + timedelta(hours=1), [("other:1", "sha256:bbbb", "other")])

    def get(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def test_host_links_only_imported_images(self):
        user = user_with("view_host", "view_containerbase")
        response = self.get(user, reverse("servers:host", args=[self.web.id]))
        self.assertContains(response, reverse("containers:cbase", args=[CID]))
        self.assertNotContains(response, reverse("containers:cbase", args=["sha256:bbbb"]))

    def test_host_does_not_link_without_container_permission(self):
        user = user_with("view_host")
        response = self.get(user, reverse("servers:host", args=[self.web.id]))
        self.assertContains(response, "app:1")
        self.assertNotContains(response, reverse("containers:cbase", args=[CID]))

    def test_container_lists_hosts_from_latest_scan(self):
        user = user_with("view_host", "view_containerbase")
        response = self.get(user, reverse("containers:cbase", args=[CID]))
        self.assertEqual([hc.hc.host for hc in response.context["running"]], [self.web])
        self.assertContains(response, reverse("servers:host", args=[self.web.id]))
        self.assertNotContains(response, reverse("servers:host", args=[self.db.id]))

    def test_container_hides_hosts_without_server_permission(self):
        user = user_with("view_containerbase")
        response = self.get(user, reverse("containers:cbase", args=[CID]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "web1")

    def test_unknown_container_is_404(self):
        user = user_with("view_containerbase")
        response = self.get(user, reverse("containers:cbase", args=["sha256:missing"]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Container not found.", status_code=404)
