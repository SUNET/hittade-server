import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from containers.management.commands import addcontainer
from containers.models import ContainerBase, ContainerPackage


def image(cid, tag, packages):
    "Builds a scan record in the shape addcontainer expects."
    return {
        cid: {
            "inspect_data": [
                {"Id": cid, "Created": "2026-10-01T10:00:00Z", "RepoTags": [tag]}
            ],
            "os_hash": {"NAME": "Debian GNU/Linux", "VERSION_ID": "13"},
            "pkg_list": [
                {"package": name, "version": version, "provider": "deb"}
                for name, version in packages
            ],
        }
    }


class AddContainerTests(TestCase):
    def setUp(self):
        addcontainer.PACKAGES.clear()
        patcher = mock.patch.object(addcontainer, "update_latest_containers")
        self.update_latest = patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name, record):
        (self.dir / name).write_text(json.dumps(record))

    def run_import(self):
        with self.captureOnCommitCallbacks(execute=True):
            call_command("addcontainer", str(self.dir), stdout=mock.Mock(), stderr=mock.Mock())

    def test_imports_images_and_shares_packages(self):
        self.write("a.json", image("sha-a", "app:1", [("bash", "5.2"), ("curl", "8.0")]))
        # Duplicate package within one file, and one shared with a.json.
        self.write(
            "b.json", image("sha-b", "web:2", [("bash", "5.2"), ("zlib", "1.3"), ("zlib", "1.3")])
        )
        (self.dir / "bad.json").write_text("not json")
        self.run_import()

        self.assertEqual(ContainerBase.objects.count(), 2)
        self.assertEqual(ContainerPackage.objects.count(), 3)
        b = ContainerBase.objects.get(cid="sha-b")
        self.assertEqual(
            sorted(b.packages.values_list("name", flat=True)), ["bash", "zlib"]
        )
        self.assertEqual(list(b.tags.values_list("fullname", flat=True)), ["web:2"])
        self.assertEqual(self.update_latest.call_count, 2)

    def test_reimport_skips_existing_images(self):
        self.write("a.json", image("sha-a", "app:1", [("bash", "5.2")]))
        self.run_import()
        # A fresh run starts with an empty cache and must reuse existing rows.
        addcontainer.PACKAGES.clear()
        self.write("c.json", image("sha-c", "app:2", [("bash", "5.2"), ("curl", "8.0")]))
        self.run_import()

        self.assertEqual(ContainerBase.objects.count(), 2)
        self.assertEqual(ContainerPackage.objects.count(), 2)
