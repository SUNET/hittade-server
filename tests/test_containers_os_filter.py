"""Tests for the OS filter of running containers on /containers/."""

import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from test_container_links import T0, scan, user_with

from containers.models import ContainerBase, ContainerTags
from containers.utils import natural_key, running_images_with_os, running_os_versions
from servers.models import Host

URL = reverse("containers:containers")


def image(cid, tag, osname, version):
    "Saves a scanned container image with one tag (name:tag) and its OS."
    cb = ContainerBase.objects.create(
        cid=cid, cname=tag.rsplit(":", 1)[0], osname=osname, osversionid=version,
        time=T0, ctime=T0,
    )
    cb.tags.add(ContainerTags.objects.create(tag=tag.rsplit(":", 1)[1], fullname=tag))
    return cb


class OsFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Images on two hosts.

        Running (latest scan of a host): a (on both hosts), b, c, e and f, plus
        an image that was never scanned. d only ran in db1's older scan.
        """
        image("sha256:a", "app:1", "debian", "12.7")
        image("sha256:b", "web:1", "debian", "12.7")
        image("sha256:c", "db:1", "debian", "9.2")
        image("sha256:d", "old:1", "debian", "10.1")  # not running any more
        image("sha256:e", "edge:1", "alpine", "3.22.1")
        image("sha256:f", "sid:1", "debian", "")
        # cscan stores an image once per tag.
        image("sha256:b", "web:latest", "debian", "12.7")
        web = Host.objects.create(hostname="web1")
        db = Host.objects.create(hostname="db1")
        scan(web, T0, [("app:1", "sha256:a", "app"), ("web:1", "sha256:b", "web"),
                       ("sid:1", "sha256:f", "sid"), ("x:1", "sha256:unscanned", "x")])
        scan(db, T0, [("old:1", "sha256:d", "old")])
        scan(db, T0 + timedelta(hours=1), [("app:1", "sha256:a", "app"), ("db:1", "sha256:c", "db"),
                                           ("edge:1", "sha256:e", "edge")])
        cls.user = user_with("view_host", "view_containerbase")

    def setUp(self):
        self.client.force_login(self.user)

    def test_os_versions_of_running_images(self):
        "Only running, scanned images count; b counts once for its two tags."
        self.assertEqual(
            running_os_versions(),
            [
                ("alpine", [("3.22.1", 1)]),
                # 10.1 only ran in an older scan; 9.2 sorts before 12.7.
                ("debian", [("", 1), ("9.2", 1), ("12.7", 2)]),
            ],
        )

    def test_natural_key(self):
        "Versions sort by their numbers, not as text."
        self.assertEqual(
            sorted(["10.1", "9.2", "12.10", "12.7", ""], key=natural_key),
            ["", "9.2", "10.1", "12.7", "12.10"],
        )

    def test_images_with_os(self):
        "Tags of one image are merged; hosts counts the hosts running it."
        self.assertEqual(
            running_images_with_os("debian", "12.7"),
            [
                {"cid": "sha256:a", "tags": ["app:1"], "hosts": 2},
                {"cid": "sha256:b", "tags": ["web:1", "web:latest"], "hosts": 1},
            ],
        )
        self.assertEqual(
            running_images_with_os("debian", ""),
            [{"cid": "sha256:f", "tags": ["sid:1"], "hosts": 1}],
        )
        self.assertEqual(running_images_with_os("debian", "10.1"), [])

    def test_page_shows_the_options_and_the_filtered_images(self):
        "The chosen option is selected and only its images are listed, unpaged."
        response = self.client.get(URL, {"os": "debian|12.7"})
        self.assertContains(response, '<option value="debian|12.7" selected>debian 12.7 (2)</option>', html=True)
        self.assertContains(response, '<option value="debian|">debian (no version) (1)</option>', html=True)
        self.assertContains(response, "Running containers with debian 12.7")
        self.assertContains(response, reverse("containers:cbase", args=["sha256:b"]))
        # One line per tag of an image.
        link = reverse("containers:cbase", args=["sha256:b"])
        self.assertContains(response, f'<li><a href="{link}">web:1</a></li>', html=True)
        self.assertContains(response, f'<li><a href="{link}">web:latest</a></li>', html=True)
        self.assertNotContains(response, reverse("containers:cbase", args=["sha256:c"]))
        self.assertNotContains(response, "ht-pagination")

    def test_unfiltered_page_lists_all_images(self):
        "Without a filter, every image is listed, running or not."
        response = self.client.get(URL)
        self.assertContains(response, '<option value="">All container images</option>', html=True)
        for cid in ("sha256:a", "sha256:d"):
            self.assertContains(response, reverse("containers:cbase", args=[cid]))

    def test_download_keeps_the_filter(self):
        "The Download JSON button downloads the filtered images."
        response = self.client.get(URL, {"os": "debian|12.7"})
        self.assertContains(response, 'href="?os=debian%7C12.7&amp;format=json"')
        response = self.client.get(URL, {"os": "debian|12.7", "format": "json"})
        self.assertIn("hittade-running-images-debian-12.7-", response["Content-Disposition"])
        data = json.loads(response.content)
        self.assertEqual((data["osname"], data["osversionid"]), ("debian", "12.7"))
        self.assertEqual([c["cid"] for c in data["containers"]], ["sha256:a", "sha256:b"])

    def test_containers_index_is_this_page(self):
        "/containers/ shows this page, and its form submits to /containers/."
        index = reverse("containers:index")
        self.assertEqual(index, "/containers/")
        response = self.client.get(index, {"os": "debian|12.7"})
        self.assertContains(response, f'<form class="ht-filter" action="{index}" method="get">')
        self.assertContains(response, "Running containers with debian 12.7")

    def test_pagination_stays_on_the_page(self):
        "Prev/Next links stay on the URL of the page (here /containers/)."
        for n in range(60):
            image(f"sha256:p{n}", f"page{n}:1", "debian", "12.7")
        response = self.client.get(reverse("containers:index"))
        self.assertContains(response, 'href="?page=2"')
