import json
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fakeredis
import redis
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from servers import utils
from servers.management.commands import addhost
from servers.models import Host, HostDetails

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class CacheTestCase(TestCase):
    def setUp(self):
        self.r = fakeredis.FakeRedis()
        patcher = mock.patch.object(utils, "r", self.r)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_details(self, host, time, osname="Debian", osrelease="12"):
        "Adds a HostDetails row and updates the cache, like addhost does."
        hd = HostDetails.objects.create(host=host, time=time, osname=osname, osrelease=osrelease)
        utils.update_latest_hosts(
            host.hostname, hd.id, hd.time, host.id, utils.osdetails_name(osname, osrelease)
        )
        return hd

    def warm(self):
        call_command("warmservercache", stdout=mock.Mock())


class UpdateLatestHostsTests(CacheTestCase):
    def test_newer_details_replace_and_move_os_group(self):
        a = Host.objects.create(hostname="a")
        b = Host.objects.create(hostname="b")
        self.add_details(a, T0)
        self.add_details(b, T0)
        # a is upgraded: it must leave the Debian-12 group.
        self.add_details(a, T0 + timedelta(days=1), osrelease="13")

        self.assertEqual(
            utils.get_osdetails(), {"Debian-12": [("b", b.id)], "Debian-13": [("a", a.id)]}
        )

    def test_older_details_are_ignored(self):
        a = Host.objects.create(hostname="a")
        self.add_details(a, T0, osrelease="13")
        self.add_details(a, T0 - timedelta(days=1), osrelease="12")

        self.assertEqual(utils.get_osdetails(), {"Debian-13": [("a", a.id)]})

    def test_aware_times_are_converted_not_relabelled(self):
        a = Host.objects.create(hostname="a")
        self.add_details(a, T0, osrelease="12")
        # 13:00+02:00 is 11:00 UTC, so older than T0 even though 13 > 12.
        cest = timezone(timedelta(hours=2))
        self.add_details(a, datetime(2026, 10, 1, 13, 0, tzinfo=cest), osrelease="13")

        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})

    def test_hosts_are_newest_first(self):
        hosts = [Host.objects.create(hostname=name) for name in "abc"]
        for host in hosts:
            self.add_details(host, T0)

        self.assertEqual(
            utils.get_osdetails(), {"Debian-12": [(h.hostname, h.id) for h in reversed(hosts)]}
        )

    def test_hosts_sharing_a_hostname_are_kept_apart(self):
        # Host.hostname is not unique, so the cache must not merge these.
        old = Host.objects.create(hostname="dup")
        new = Host.objects.create(hostname="dup")
        HostDetails.objects.create(host=old, time=T0, osname="Debian", osrelease="12")
        self.warm()
        self.add_details(new, T0 - timedelta(days=1), osrelease="13")

        expected = {"Debian-13": [("dup", new.id)], "Debian-12": [("dup", old.id)]}
        self.assertEqual(utils.get_osdetails(), expected)
        self.assertEqual(utils.osdetails_from_db(), expected)

    def test_no_cache_means_none(self):
        self.assertIsNone(utils.get_osdetails())


class WarmServerCacheTests(CacheTestCase):
    def test_rebuilds_from_database(self):
        a = Host.objects.create(hostname="a")
        b = Host.objects.create(hostname="b")
        empty = Host.objects.create(hostname="empty")
        HostDetails.objects.create(host=a, time=T0, osname="Debian", osrelease="12")
        HostDetails.objects.create(
            host=a, time=T0 + timedelta(days=1), osname="Debian", osrelease="13"
        )
        HostDetails.objects.create(host=b, time=T0, osname="Ubuntu", osrelease="24.04")
        # Stale entries from before: a deleted host and old cache keys.
        self.r.hset(utils.LATEST_HOSTS_KEY, 999, '["gone", "Debian-11", 1, 0]')
        for key in utils.LEGACY_KEYS:
            self.r.set(key, "1")
        self.r.hset("latesth:a", "time", 0)

        # One query for all hosts and their latest details, whatever the history.
        with self.assertNumQueries(1):
            self.warm()

        expected = {
            "None-None": [("empty", empty.id)],
            "Ubuntu-24.04": [("b", b.id)],
            "Debian-13": [("a", a.id)],
        }
        self.assertEqual(utils.get_osdetails(), expected)
        # Same hosts as the database fallback, including hosts without details.
        self.assertEqual(utils.osdetails_from_db(), expected)
        self.assertEqual(self.r.keys("*"), [utils.LATEST_HOSTS_KEY.encode()])
        # The live cache never expires, though the temporary hash had a TTL.
        self.assertEqual(self.r.ttl(utils.LATEST_HOSTS_KEY), -1)

    def test_no_hosts_removes_the_cache(self):
        self.r.hset(utils.LATEST_HOSTS_KEY, 999, '["gone", "Debian-11", 1, 0]')
        self.warm()
        self.assertIsNone(utils.get_osdetails())
        self.assertEqual(self.r.keys("*"), [])

    def test_host_without_details_is_replaced_by_its_first_scan(self):
        empty = Host.objects.create(hostname="empty")
        self.warm()
        self.add_details(empty, T0)
        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("empty", empty.id)]})

    def test_previous_cache_is_served_while_rebuilding(self):
        a = Host.objects.create(hostname="a")
        self.add_details(a, T0)
        self.warm()
        b = Host.objects.create(hostname="b")
        HostDetails.objects.create(host=b, time=T0, osname="Debian", osrelease="13")
        real_rows = utils.latest_host_rows

        def rows_while_serving():
            rows = list(real_rows())

            def iterate():
                for row in rows:
                    # Mid-rebuild, readers still get the complete previous cache.
                    self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})
                    yield row

            return mock.Mock(iterator=iterate)

        with mock.patch.object(utils, "latest_host_rows", rows_while_serving):
            self.warm()
        self.assertEqual(
            utils.get_osdetails(), {"Debian-13": [("b", b.id)], "Debian-12": [("a", a.id)]}
        )

    def test_overlapping_rebuilds_each_publish_a_complete_cache(self):
        hosts = [Host.objects.create(hostname=f"h{i}") for i in range(3)]
        for host in hosts:
            HostDetails.objects.create(host=host, time=T0, osname="Debian", osrelease="12")
        expected = {"Debian-12": [(h.hostname, h.id) for h in reversed(hosts)]}
        real_rows = utils.latest_host_rows
        nested = []

        def rows_with_a_second_rebuild():
            rows = list(real_rows())

            def iterate():
                for i, row in enumerate(rows):
                    if i == 1 and not nested:
                        # A second rebuild (e.g. a manual warmservercache) runs
                        # to completion while the first is half-way writing.
                        nested.append(True)
                        utils.rebuild_latest_hosts()
                        self.assertEqual(utils.get_osdetails(), expected)
                    yield row

            return mock.Mock(iterator=iterate)

        # Write every row immediately, so the rebuilds really interleave in redis.
        with (
            mock.patch.object(utils, "BUILDING_BATCH_SIZE", 1),
            mock.patch.object(utils, "latest_host_rows", rows_with_a_second_rebuild),
        ):
            self.warm()

        self.assertEqual(nested, [True])
        self.assertEqual(utils.get_osdetails(), expected)
        self.assertEqual(self.r.keys(f"{utils.BUILDING_KEY_PREFIX}*"), [])

    def test_failed_rebuild_keeps_the_previous_cache(self):
        a = Host.objects.create(hostname="a")
        self.add_details(a, T0)
        self.warm()
        Host.objects.create(hostname="b")

        def broken_rows():
            def rows():
                yield (a.id, "a", None, None, None, None)
                yield (a.id + 1, "b", None, None, None, None)
                raise RuntimeError("database went away")

            return mock.Mock(iterator=rows)

        # Write every row immediately, so a partial temporary hash exists.
        with (
            mock.patch.object(utils, "BUILDING_BATCH_SIZE", 1),
            mock.patch.object(utils, "latest_host_rows", broken_rows),
            self.assertRaises(RuntimeError),
        ):
            self.warm()

        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})
        self.assertEqual(self.r.keys(f"{utils.BUILDING_KEY_PREFIX}*"), [])


def host_scan(hostname, timestamp, osrelease):
    "A minimal addhost input file."
    return {
        "name": hostname,
        "timestamp": timestamp,
        "values": {
            "packages": [[{"name": "bash", "version": "5.2"}]],
            "domain": "example.org",
            "os": {"name": "Debian", "release": {"full": osrelease}},
            "running-kernel": {"kernel-release": "6.12"},
            "ipaddress": "192.0.2.1",
            "ipaddress6": "2001:db8::1",
        },
    }


class AddhostTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        # addhost caches database rows across calls; tests roll them back.
        for cache in (addhost.PACKAGES, addhost.CONTAINERS, addhost.CONFIGVALUES):
            cache.clear()

    def addhost(self, hostname, timestamp, osrelease):
        path = self.dir / f"{hostname}-{timestamp[:10]}.json"
        path.write_text(json.dumps(host_scan(hostname, timestamp, osrelease)))
        stderr = mock.Mock()
        call_command("addhost", str(path), stdout=mock.Mock(), stderr=stderr)
        return stderr

    def test_updates_the_cache(self):
        self.addhost("a", "2026-10-01T12:00:00Z", "12")
        self.addhost("a", "2026-10-02T12:00:00Z", "13")
        a = Host.objects.get(hostname="a")
        self.assertEqual(utils.get_osdetails(), {"Debian-13": [("a", a.id)]})

    def test_redis_failure_does_not_fail_the_import(self):
        self.addhost("a", "2026-10-01T12:00:00Z", "12")
        with mock.patch(
            "servers.management.commands.addhost.update_latest_hosts",
            side_effect=redis.ConnectionError("down"),
        ):
            stderr = self.addhost("a", "2026-10-02T12:00:00Z", "13")

        self.assertIn("Redis cache not updated", stderr.write.call_args.args[0])
        a = Host.objects.get(hostname="a")
        self.assertEqual(utils.osdetails_from_db(), {"Debian-13": [("a", a.id)]})
        # Known and accepted: stale until the next app restart rebuilds it.
        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})
        self.warm()
        self.assertEqual(utils.get_osdetails(), {"Debian-13": [("a", a.id)]})


class IndexViewTests(CacheTestCase):
    URL = "/servers/"

    def setUp(self):
        super().setUp()
        user = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(user)
        self.a = Host.objects.create(hostname="a")
        HostDetails.objects.create(host=self.a, time=T0, osname="Debian", osrelease="12")

    def test_uses_cache(self):
        self.r.hset(utils.LATEST_HOSTS_KEY, self.a.id, '["a", "Cached-1", 1, 0]')
        with self.assertNumQueries(2):  # session + user, nothing for the hosts
            response = self.client.get(self.URL)
        self.assertEqual(response.context["osdetails"], {"Cached-1": [("a", self.a.id)]})

    def test_falls_back_to_database_without_cache(self):
        # A host without any HostDetails must not break the page.
        empty = Host.objects.create(hostname="empty")
        response = self.client.get(self.URL)
        self.assertEqual(
            response.context["osdetails"],
            {"None-None": [("empty", empty.id)], "Debian-12": [("a", self.a.id)]},
        )

    def test_falls_back_to_database_when_redis_is_down(self):
        with mock.patch("servers.views.get_osdetails", side_effect=redis.ConnectionError):
            response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["osdetails"], {"Debian-12": [("a", self.a.id)]})
