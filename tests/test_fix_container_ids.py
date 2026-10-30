import importlib.util
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase
from test_container_links import T0, scan

from containers.models import ContainerBase, ContainerTags
from servers.models import Host

spec = importlib.util.spec_from_file_location(
    "fix_container_ids", Path(__file__).parent.parent / "scripts" / "fix_container_ids.py"
)
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)

REG = "docker.sunet.se"


def image(cid, tag):
    cb = ContainerBase.objects.create(cid=cid, cname=tag, time=T0, ctime=T0)
    t, _ = ContainerTags.objects.get_or_create(tag=tag.rsplit(":", 1)[-1], fullname=tag)
    cb.tags.add(t)
    return cb


# Registry stand-in: manifest digest -> config digest.
MANIFESTS = {"sha256:m-app-old": "sha256:c-app-old", "sha256:m-app-new": "sha256:c-app-new"}


def config_digest(image, manifest_digest):
    return MANIFESTS.get(manifest_digest)


class FixContainerIdsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.app_old = image("sha256:m-app-old", f"{REG}/app:latest")
        cls.app_new = image("sha256:m-app-new", f"{REG}/app:latest")
        # Only one imported build, and the registry no longer has its manifest.
        cls.db = image("sha256:m-db-gone", f"{REG}/db:1")
        cls.linked = image("sha256:c-ok", f"{REG}/ok:1")
        cls.web = Host.objects.create(hostname="web1")
        cls.ci = Host.objects.create(hostname="ci1")
        scan(cls.web, T0, [
            (f"{REG}/app", "sha256:c-app-new", "app"),  # no tag means latest
            (f"{REG}/db:1", "sha256:c-db", "db"),
            (f"{REG}/ok:1", "sha256:c-ok", "ok"),
            (f"{REG}/missing:1", "sha256:c-missing", "missing"),
            (f"{REG}/old:1", "not_available", "old"),
        ])
        # ci1 ran the old app build, but its latest scan runs nothing.
        scan(cls.ci, T0, [(f"{REG}/app:latest", "sha256:c-app-old", "app")])
        scan(cls.ci, T0 + timedelta(hours=1), [])

    def test_plan(self):
        changes, notes = fix.plan(config_digest)
        self.assertEqual(
            sorted((cb.pk, cid, how) for cb, cid, how in changes),
            sorted([
                (self.app_new.pk, "sha256:c-app-new", "verified"),
                (self.db.pk, "sha256:c-db", "unverified"),
            ]),
        )
        self.assertEqual(notes, [f"{REG}/missing:1: not imported"])

    def test_skips_a_different_build(self):
        # The only imported build of app:latest is the old one; the host runs another.
        self.app_new.delete()
        changes, notes = fix.plan(config_digest)
        self.assertNotIn(self.app_old.pk, [cb.pk for cb, _, _ in changes])
        self.assertIn(
            f"{REG}/app:latest: none of the 1 imported build(s) is sha256:c-app-new", notes
        )

    def test_apply_updates_every_tag_of_the_same_image(self):
        # app:1.0 was imported with the same manifest digest as the running app:latest.
        same = image("sha256:m-app-new", f"{REG}/app:1.0")
        changes, _ = fix.plan(config_digest)
        self.assertEqual(fix.apply(changes), 3)
        same.refresh_from_db()
        self.app_new.refresh_from_db()
        self.app_old.refresh_from_db()
        self.assertEqual(same.cid, "sha256:c-app-new")
        self.assertEqual(self.app_new.cid, "sha256:c-app-new")
        self.assertEqual(self.app_old.cid, "sha256:m-app-old")  # another build: unchanged
        self.assertEqual(fix.plan(config_digest)[0], [])  # nothing left to do

    def test_rerun_keeps_ids_already_fixed(self):
        # app:moving is the old app build; after the fix its cid is a config
        # digest the registry cannot resolve as a manifest. A host running
        # another build of the tag must not take it over as "unverified".
        image("sha256:m-app-old", f"{REG}/app:moving")
        scan(self.web, T0 + timedelta(hours=1), [
            (f"{REG}/app:latest", "sha256:c-app-old", "app"),
            (f"{REG}/app:moving", "sha256:c-app-new", "moving"),
        ])
        fix.apply(fix.plan(config_digest)[0])
        changes, _ = fix.plan(config_digest)
        self.assertEqual(changes, [])
        self.assertEqual(
            ContainerBase.objects.get(tags__fullname=f"{REG}/app:moving").cid,
            "sha256:c-app-old",
        )

    def test_export_lists_old_and_new_ids(self):
        image("sha256:m-app-new", f"{REG}/app:1.0")  # same image, another tag
        changes, _ = fix.plan(config_digest)
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "fix.txt"
        fix.export(changes, path)
        self.assertEqual(
            sorted(path.read_text().splitlines()),
            [
                f"sha256:m-app-new\tsha256:c-app-new\t{REG}/app:1.0,{REG}/app:latest",
                f"sha256:m-db-gone\tsha256:c-db\t{REG}/db:1",
            ],
        )

