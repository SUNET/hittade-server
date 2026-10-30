import io
import json
import tempfile
import urllib.error
from pathlib import Path
from unittest import mock

import fakeredis
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from test_container_links import T0, scan
from test_servers_cache import host_scan

from containers.models import ContainerBase
from servers import registry, utils
from servers.management.commands import addhost
from servers.models import ContainerImage, Host, HostContainersThrough

REG = "platform.sunet.se"
MANIFEST = "sha256:" + "a" * 64
CONFIG = "sha256:" + "c" * 64
INDEX = "sha256:" + "1" * 64
AMD64 = "sha256:" + "2" * 64
ARM64 = "sha256:" + "3" * 64

# Registry stand-in: (repo, reference) -> manifest.
MANIFESTS = {
    ("eduid/app", MANIFEST): {
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {"digest": CONFIG},
    },
    ("eduid/app", INDEX): {
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {"digest": ARM64, "platform": {"os": "linux", "architecture": "arm64"}},
            {"digest": AMD64, "platform": {"os": "linux", "architecture": "amd64"}},
        ],
    },
    ("eduid/app", AMD64): {"config": {"digest": CONFIG}},
}


def fake_fetch(registry_, repo, reference):
    return MANIFESTS.get((repo, reference))


@mock.patch.object(registry, "fetch_manifest", side_effect=fake_fetch)
class ConfigDigestTests(SimpleTestCase):
    def test_manifest_digest_becomes_config_digest(self, fetch):
        self.assertEqual(registry.config_digest(f"{REG}/eduid/app:v1", MANIFEST), CONFIG)

    def test_index_uses_the_amd64_manifest(self, fetch):
        self.assertEqual(registry.config_digest(f"{REG}/eduid/app:v1", INDEX), CONFIG)

    def test_config_digest_is_left_alone(self, fetch):
        self.assertIsNone(registry.config_digest(f"{REG}/eduid/app:v1", CONFIG))

    def test_other_registries_are_not_asked(self, fetch):
        self.assertIsNone(registry.config_digest("registry.example.org/app:v1", MANIFEST))
        self.assertIsNone(registry.config_digest("redis:8", MANIFEST))
        fetch.assert_not_called()

    def test_non_digests_are_not_looked_up(self, fetch):
        self.assertIsNone(registry.config_digest(f"{REG}/eduid/app:v1", "not_available"))
        fetch.assert_not_called()


class RegistryAndRepoTests(SimpleTestCase):
    def test_names(self):
        for image, expected in [
            ("platform.sunet.se/eduid/fastapi:2026-production", ("platform.sunet.se", "eduid/fastapi")),
            ("docker.sunet.se/haproxy", ("docker.sunet.se", "haproxy")),
            ("reg.example.org:5000/a/b:1", ("reg.example.org:5000", "a/b")),
            (f"docker.sunet.se/app@{MANIFEST}", ("docker.sunet.se", "app")),
            ("redis", None),
        ]:
            with self.subTest(image=image):
                self.assertEqual(registry.registry_and_repo(image), expected)


class FetchManifestTests(SimpleTestCase):
    def response(self, data):
        r = mock.MagicMock()
        r.__enter__.return_value.read.return_value = json.dumps(data).encode()
        return r

    def test_retries_with_an_anonymous_token(self):
        challenge = urllib.error.HTTPError(
            "url", 401, "Unauthorized",
            {"WWW-Authenticate": f'Bearer realm="https://{REG}/v2/token",service="registry"'},
            None,
        )
        manifest = {"config": {"digest": CONFIG}}
        with mock.patch.object(
            registry.urllib.request, "urlopen",
            side_effect=[challenge, self.response({"token": "t"}), self.response(manifest)],
        ) as urlopen:
            self.assertEqual(registry.fetch_manifest(REG, "eduid/app", MANIFEST), manifest)
        token_url = urlopen.call_args_list[1].args[0]
        self.assertIn("scope=repository%3Aeduid%2Fapp%3Apull", token_url)
        self.assertEqual(urlopen.call_args_list[2].args[0].get_header("Authorization"), "Bearer t")

    def test_unknown_manifest(self):
        missing = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        with mock.patch.object(registry.urllib.request, "urlopen", side_effect=missing):
            self.assertIsNone(registry.fetch_manifest(REG, "eduid/app", CONFIG))


@mock.patch.object(registry, "fetch_manifest", side_effect=fake_fetch)
class AddhostImageIdTests(TestCase):
    def setUp(self):
        patcher = mock.patch.object(utils, "r", fakeredis.FakeRedis())
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        for cache in (addhost.PACKAGES, addhost.CONTAINERS, addhost.CONFIGVALUES, addhost.IMAGEIDS):
            cache.clear()

    def addhost(self, hostname, image_id):
        data = host_scan(hostname, "2026-10-01T12:00:00Z", "13")
        data["values"]["docker_ps"] = [
            {"Image": f"{REG}/eduid/app:v1", "ImageId": image_id, "Names": "app-1"}
        ]
        path = self.dir / f"{hostname}.json"
        path.write_text(json.dumps(data))
        call_command("addhost", str(path), stdout=mock.Mock(), stderr=mock.Mock())

    def test_stores_the_config_digest(self, fetch):
        self.addhost("new", MANIFEST)
        self.addhost("old", CONFIG)
        self.assertEqual(
            list(ContainerImage.objects.values_list("imageid", flat=True)), [CONFIG]
        )
        self.assertEqual(HostContainersThrough.objects.count(), 2)

    def test_scanned_ids_and_repeats_skip_the_registry(self, fetch):
        ContainerBase.objects.create(cid=CONFIG, cname="app", time=T0, ctime=T0)
        self.addhost("old", CONFIG)
        fetch.assert_not_called()
        self.addhost("new", MANIFEST)
        self.addhost("new2", MANIFEST)
        self.assertEqual(fetch.call_count, 1)


@mock.patch.object(registry, "fetch_manifest", side_effect=fake_fetch)
class FixImageIdsTests(TestCase):
    def setUp(self):
        ContainerBase.objects.create(cid=CONFIG, cname="app", time=T0, ctime=T0)
        self.old, self.new = Host.objects.create(hostname="old"), Host.objects.create(hostname="new")

    def run_command(self, *args):
        out = io.StringIO()
        call_command("fiximageids", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self, fetch):
        scan(self.new, T0, [(f"{REG}/eduid/app:v1", MANIFEST, "app-1")])
        self.assertIn("1 image ID(s) to fix", self.run_command())
        self.assertEqual(ContainerImage.objects.get().imageid, MANIFEST)

    def test_renames_a_lone_row(self, fetch):
        scan(self.new, T0, [(f"{REG}/eduid/app:v1", MANIFEST, "app-1")])
        self.run_command("--apply")
        self.assertEqual(ContainerImage.objects.get().imageid, CONFIG)

    def test_merges_into_the_existing_row(self, fetch):
        scan(self.old, T0, [(f"{REG}/eduid/app:v1", CONFIG, "app_1")])
        scan(self.new, T0, [(f"{REG}/eduid/app:v1", MANIFEST, "app-1")])
        self.run_command("--apply")
        ci = ContainerImage.objects.get()
        self.assertEqual(ci.imageid, CONFIG)
        self.assertEqual(
            sorted(HostContainersThrough.objects.filter(container=ci).values_list("name", flat=True)),
            ["app-1", "app_1"],
        )
