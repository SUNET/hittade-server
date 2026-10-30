import json
from unittest import mock

import fakeredis
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from test_container_links import T0, scan, user_with

from containers import utils as containers_utils
from containers.models import ContainerBase, ContainerPackage, ContainerTags
from hittade.downloads import download_name
from servers import utils
from servers.models import Host, HostDetails, HostPackages, Package

CID = "sha256:" + "ab" * 32
IMAGE = "platform.sunet.se/eduid/app:v1"


class DownloadNameTests(SimpleTestCase):
    def test_names(self):
        today = timezone.localdate().isoformat()
        for parts, expected in [
            (("hosts",), "hittade-hosts"),
            (("host", "web1.example.org"), "hittade-host-web1.example.org"),
            (("container", IMAGE, "abab"), "hittade-container-platform.sunet.se_eduid_app_v1-abab"),
            (("running-containers", "python3*", "3.11*"), "hittade-running-containers-python3-3.11"),
            (("search", "../../etc", 'a"b'), "hittade-search-etc-a_b"),
            (("search", "", "openssl"), "hittade-search-openssl"),
        ]:
            with self.subTest(parts=parts):
                self.assertEqual(download_name(*parts), f"{expected}-{today}.json")


class DownloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.web = Host.objects.create(hostname="web1.example.org")
        HostDetails.objects.create(
            host=cls.web, time=T0, osname="Debian", osrelease="13", rkr="6.12"
        )
        bash = Package.objects.create(name="bash", version="5.2")
        HostPackages.objects.create(host=cls.web, time=T0).packages.add(bash)
        scan(cls.web, T0, [(IMAGE, CID, "app-1"), ("other:1", "sha256:other", "other")])

        cb = ContainerBase.objects.create(
            cid=CID, cname="platform.sunet.se/eduid/app", osname="debian",
            osversionid="13", time=T0, ctime=T0,
        )
        cb.tags.add(ContainerTags.objects.create(tag="v1", fullname=IMAGE))
        cls.openssl = ContainerPackage.objects.create(
            name="openssl", version="3.5.1", provider="deb"
        )
        cb.packages.add(cls.openssl)
        cls.cb = cb
        cls.bash = bash
        cls.user = user_with("view_host", "view_containerbase")

    def setUp(self):
        for module in (utils, containers_utils):
            patcher = mock.patch.object(module, "r", fakeredis.FakeRedis())
            patcher.start()
            self.addCleanup(patcher.stop)
        containers_utils.update_latest_containers(self.cb.cname, self.cb.id, T0)
        self.client.force_login(self.user)

    def download(self, response, name):
        "The JSON of a download response named hittade-<name>-<date>.json."
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        today = timezone.localdate().isoformat()
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="hittade-{name}-{today}.json"',
        )
        data = json.loads(response.content)
        self.assertIn("generated_at", data)
        return data

    def test_get_pages(self):
        for url, name, check in [
            (
                reverse("servers:index"), "servers-by-os",
                lambda d: d["os"] == {"Debian-13": [{"id": self.web.id, "hostname": "web1.example.org"}]},
            ),
            (
                reverse("servers:hosts"), "hosts",
                lambda d: d["hosts"] == [{"id": self.web.id, "hostname": "web1.example.org"}],
            ),
            (
                reverse("servers:package", args=[self.bash.id]), "hosts-with-package-bash-5.2",
                lambda d: d["hosts"] == [{"id": self.web.id, "hostname": "web1.example.org"}],
            ),
            (
                reverse("servers:host", args=[self.web.id]), "host-web1.example.org",
                lambda d: d["details"]["kernel"] == "6.12"
                and d["packages"] == [{"name": "bash", "version": "5.2"}]
                and [(c["name"], c["scanned"]) for c in d["running_containers"]]
                == [("app-1", True), ("other", False)],
            ),
            (
                reverse("servers:running_containers") + "?search=open*+3.*",
                "running-containers-open-3",
                lambda d: [(r["host"], r["container"], r["package"]) for r in d["rows"]]
                == [("web1.example.org", "app-1", "openssl")]
                and d["unscanned_containers"] == 1,
            ),
            (
                reverse("containers:package", args=[self.openssl.id]),
                "containers-with-package-openssl-3.5.1",
                lambda d: d["containers"] == [{"fullname": IMAGE, "cid": CID}],
            ),
            (
                reverse("containers:cbase", args=[CID]),
                "container-platform.sunet.se_eduid_app-" + "ab" * 6,
                lambda d: d["tags"] == [IMAGE]
                and d["packages"] == [{"name": "openssl", "version": "3.5.1", "provider": "deb"}]
                and [r["host"] for r in d["running_on"]] == ["web1.example.org"],
            ),
            (
                # The whole list, not the page.
                reverse("containers:containers") + "?page=2", "containers",
                lambda d: [c["cid"] for c in d["containers"]] == [CID],
            ),
        ]:
            with self.subTest(url=url):
                html = self.client.get(url)
                self.assertContains(html, "Download JSON")
                sep = "&" if "?" in url else "?"
                data = self.download(self.client.get(f"{url}{sep}format=json"), name)
                self.assertTrue(check(data), data)

    def test_button_keeps_the_query_but_not_the_page(self):
        html = self.client.get(reverse("servers:running_containers"), {"search": "open* 3.*"})
        self.assertContains(html, 'href="?search=open%2A+3.%2A&amp;format=json"')
        html = self.client.get(reverse("containers:containers"), {"page": 1})
        self.assertContains(html, 'href="?format=json"')

    def test_search_pages_post_again(self):
        for url, form, name, key, expected in [
            (
                reverse("servers:search"), {"search": "web", "stype": "host"},
                "host-search-host-web", "hosts",
                [{"id": self.web.id, "hostname": "web1.example.org"}],
            ),
            (
                reverse("servers:search"), {"search": "bash", "stype": "package"},
                "host-search-package-bash", "packages",
                [{"id": self.bash.id, "name": "bash", "version": "5.2"}],
            ),
            (
                reverse("containers:search"), {"search": "eduid", "stype": "container"},
                "container-search-container-eduid", "containers",
                [{"fullname": IMAGE, "cid": CID}],
            ),
            (
                reverse("containers:search"), {"search": "openssl", "stype": "package"},
                "container-search-package-openssl", "packages",
                [{"id": self.openssl.id, "name": "openssl", "version": "3.5.1", "provider": "deb"}],
            ),
        ]:
            with self.subTest(url=url, form=form):
                html = self.client.post(url, form)
                self.assertContains(html, '<input type="hidden" name="format" value="json">')
                self.assertContains(html, f'<input type="hidden" name="search" value="{form["search"]}">')
                data = self.download(self.client.post(url, {**form, "format": "json"}), name)
                self.assertEqual(data[key], expected)

    def test_no_button_without_results(self):
        for url in (
            reverse("servers:search"),
            reverse("containers:search"),
            reverse("servers:running_containers"),
        ):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), "Download JSON")

    def test_running_on_needs_view_host(self):
        self.client.force_login(user_with("view_containerbase"))
        data = self.download(
            self.client.get(reverse("containers:cbase", args=[CID]), {"format": "json"}),
            "container-platform.sunet.se_eduid_app-" + "ab" * 6,
        )
        self.assertNotIn("running_on", data)

    def test_downloads_need_the_page_permissions(self):
        self.client.force_login(user_with("view_containerbase"))
        response = self.client.get(reverse("servers:hosts"), {"format": "json"})
        self.assertEqual(response.status_code, 403)
