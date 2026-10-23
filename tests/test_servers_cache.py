import json
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fakeredis
import redis
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from servers import utils
from servers.management.commands import addhost
from servers.models import Host, HostDetails

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class CacheTestCase(TestCase):
    def setUp(self):
        self.r = fakeredis.FakeRedis()
        # fakeredis has no INFO; simulate the redis process id ourselves.
        self.run_id = "process-1"
        for name, value in (("r", self.r), ("_redis_run_id", lambda: self.run_id)):
            patcher = mock.patch.object(utils, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def snapshot(self):
        "What redis would persist to disk now."
        return {key: self.r.dump(key) for key in self.r.keys("*")}

    def restart(self, snapshot):
        "Restart redis as a new process, restoring the given (older) snapshot."
        self.r.flushall()
        for key, value in snapshot.items():
            self.r.restore(key, 0, value)
        self.run_id = f"process-{int(self.run_id.split('-')[1]) + 1}"

    def add_details(self, host, time, osname="Debian", osrelease="12"):
        "Adds a HostDetails row and updates the cache, like addhost does."
        hd = HostDetails.objects.create(host=host, time=time, osname=osname, osrelease=osrelease)
        utils.cache_host_details(hd)
        return hd

    def warm(self):
        call_command("warmservercache", stdout=mock.Mock())


class UpdateLatestHostsTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        # Start from a complete (empty) cache, as after a deploy.
        self.warm()

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


class CacheCompletenessTests(CacheTestCase):
    def test_cache_is_not_used_until_a_rebuild_completes(self):
        a = Host.objects.create(hostname="a")
        self.add_details(a, T0)
        # e.g. redis was flushed and addhost then added one host.
        self.assertIsNone(utils.get_osdetails())

        self.warm()
        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})

    def test_deleting_the_cache_makes_it_incomplete(self):
        self.warm()
        utils.delete_all_host_cache()
        self.assertIsNone(utils.get_osdetails())

    def test_import_during_rebuild_is_kept(self):
        a = Host.objects.create(hostname="a")
        b = Host.objects.create(hostname="b")
        HostDetails.objects.create(host=a, time=T0, osname="Debian", osrelease="12")
        real_rows = utils.latest_host_rows

        def rows_then_concurrent_import():
            rows = list(real_rows())
            # addhost commits b after the rebuild read the database.
            self.add_details(b, T0, osname="Ubuntu", osrelease="24.04")
            # ... and the rebuild must not be visible before it is published.
            self.assertIsNone(utils.get_osdetails())
            return mock.Mock(iterator=lambda: iter(rows))

        with mock.patch.object(utils, "latest_host_rows", rows_then_concurrent_import):
            self.warm()

        self.assertEqual(
            utils.get_osdetails(), {"Debian-12": [("a", a.id)], "Ubuntu-24.04": [("b", b.id)]}
        )

    def test_previous_cache_is_served_while_rebuilding(self):
        a = Host.objects.create(hostname="a")
        self.add_details(a, T0)
        self.warm()
        real_rows = utils.latest_host_rows

        def rows_while_serving():
            self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})
            return real_rows()

        with mock.patch.object(utils, "latest_host_rows", rows_while_serving):
            self.warm()

    def test_only_one_rebuild_at_a_time(self):
        self.r.set(utils.LATEST_HOSTS_LOCK_KEY, self.run_id)
        with self.assertRaises(CommandError):
            self.warm()
        self.assertIsNone(utils.get_osdetails())

    def test_lock_restored_from_a_previous_redis_process_is_taken_over(self):
        # Redis restarted during a rebuild and restored the lock with its data.
        self.r.set(utils.LATEST_HOSTS_LOCK_KEY, "process-0")
        self.warm()
        self.assertEqual(utils.get_osdetails(), {})
        self.assertFalse(self.r.exists(utils.LATEST_HOSTS_LOCK_KEY))


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


class AddhostTestCase(CacheTestCase):
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
        call_command("addhost", str(path), stdout=mock.Mock(), stderr=mock.Mock())

    def redis_down(self):
        return mock.patch.object(
            utils, "update_latest_hosts", side_effect=redis.ConnectionError("down")
        )


class RedisFailureTests(AddhostTestCase):
    def test_failed_write_is_not_trusted_and_retry_repairs_it(self):
        self.addhost("a", "2026-10-01T12:00:00Z", "12")
        self.warm()
        a = Host.objects.get(hostname="a")
        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})

        # The new scan is committed, but redis fails: import must still finish.
        with self.redis_down():
            self.addhost("a", "2026-10-02T12:00:00Z", "13")
        self.assertTrue(HostDetails.objects.filter(cached=False).exists())
        # Redis is back with its old data and ready flag: it must not be used.
        self.assertIsNone(utils.get_osdetails())

        # Retrying the same file skips the import but repairs the cache.
        self.addhost("a", "2026-10-02T12:00:00Z", "13")
        self.assertFalse(HostDetails.objects.filter(cached=False).exists())
        self.assertEqual(utils.get_osdetails(), {"Debian-13": [("a", a.id)]})

    def test_new_host_missed_by_redis_is_not_hidden(self):
        self.addhost("a", "2026-10-01T12:00:00Z", "12")
        self.warm()
        with self.redis_down():
            self.addhost("b", "2026-10-01T12:00:00Z", "12")
        self.assertIsNone(utils.get_osdetails())
        self.assertEqual(
            sorted(h for h, _ in utils.osdetails_from_db()["Debian-12"]), ["a", "b"]
        )

    def test_rebuild_repairs_rows_it_read(self):
        a = Host.objects.create(hostname="a")
        HostDetails.objects.create(host=a, time=T0, osname="Debian", osrelease="12")
        self.assertIsNone(utils.get_osdetails())
        self.warm()
        self.assertFalse(HostDetails.objects.filter(cached=False).exists())
        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})

    def test_rows_committed_after_the_rebuild_read_stay_uncached(self):
        a = Host.objects.create(hostname="a")
        real_rows = utils.latest_host_rows

        def rows_then_failed_import():
            rows = list(real_rows())
            # Committed after the rebuild read, and its redis write failed.
            HostDetails.objects.create(host=a, time=T0, osname="Debian", osrelease="13")
            return mock.Mock(iterator=lambda: iter(rows))

        with mock.patch.object(utils, "latest_host_rows", rows_then_failed_import):
            self.warm()
        self.assertIsNone(utils.get_osdetails())
        self.assertEqual(utils.sync_uncached_host_details(), 1)
        self.assertEqual(utils.get_osdetails(), {"Debian-13": [("a", a.id)]})


class RedisRestartTests(AddhostTestCase):
    def test_restored_older_ready_cache_is_rejected_and_retry_repairs_it(self):
        self.addhost("a", "2026-10-01T12:00:00Z", "12")
        a = Host.objects.get(hostname="a")
        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})
        # Redis saves a snapshot, then a successful import: the database marks
        # the new row as cached.
        snapshot = self.snapshot()
        self.addhost("a", "2026-10-02T12:00:00Z", "13")
        self.assertEqual(utils.get_osdetails(), {"Debian-13": [("a", a.id)]})
        self.assertFalse(HostDetails.objects.filter(cached=False).exists())

        # Redis restarts from the older snapshot, ready flag included.
        self.restart(snapshot)
        self.assertEqual(
            json.loads(self.r.hget(utils.LATEST_HOSTS_KEY, a.id))[1], "Debian-12"
        )
        self.assertIsNone(utils.get_osdetails())
        self.assertFalse(utils.latest_hosts_ready())

        # Retrying the same file (all skipped) rebuilds the cache.
        self.addhost("a", "2026-10-02T12:00:00Z", "13")
        self.assertEqual(utils.get_osdetails(), {"Debian-13": [("a", a.id)]})

    def test_index_uses_database_after_restart(self):
        self.addhost("a", "2026-10-01T12:00:00Z", "12")
        snapshot = self.snapshot()
        self.addhost("b", "2026-10-01T12:00:00Z", "12")
        self.restart(snapshot)

        user = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(user)
        response = self.client.get("/servers/")
        self.assertEqual(
            sorted(h for h, _ in response.context["osdetails"]["Debian-12"]), ["a", "b"]
        )

    def test_restart_while_reading_is_not_trusted(self):
        self.warm()
        self.assertEqual(utils.get_osdetails(), {})
        # Same ready flag, but the process changed between the two run_id reads.
        with mock.patch.object(utils, "_redis_run_id", side_effect=["process-1", "process-2"]):
            self.assertIsNone(utils.get_osdetails())

    def test_restart_during_rebuild_is_not_trusted(self):
        a = Host.objects.create(hostname="a")
        HostDetails.objects.create(host=a, time=T0, osname="Debian", osrelease="12")
        real_rows = utils.latest_host_rows

        def rows_then_restart():
            rows = list(real_rows())
            self.restart(self.snapshot())
            return mock.Mock(iterator=lambda: iter(rows))

        with mock.patch.object(utils, "latest_host_rows", rows_then_restart):
            self.warm()
        self.assertIsNone(utils.get_osdetails())
        self.warm()
        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("a", a.id)]})


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
        # Stale entries from before: a deleted host and the old cache formats.
        self.r.hset(utils.LATEST_HOSTS_KEY, 999, '["gone", "Debian-11", 1, 0]')
        self.r.hset(utils.LEGACY_OSDETAILS_KEY, "Debian-11", "[]")
        self.r.hset("latesth:a", "time", 0)

        # Uncached ids, all hosts with their latest details, marking cached:
        # a fixed number of queries, whatever the history.
        with self.assertNumQueries(3):
            self.warm()

        expected = {
            "None-None": [("empty", empty.id)],
            "Ubuntu-24.04": [("b", b.id)],
            "Debian-13": [("a", a.id)],
        }
        self.assertEqual(utils.get_osdetails(), expected)
        # Same hosts as the database fallback, including hosts without details.
        self.assertEqual(utils.osdetails_from_db(), expected)
        self.assertFalse(self.r.exists(utils.LEGACY_OSDETAILS_KEY, "latesth:a"))
        self.assertFalse(self.r.exists(utils.LATEST_HOSTS_BUILDING_KEY))
        self.assertFalse(self.r.exists(utils.LATEST_HOSTS_LOCK_KEY))

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

    def test_host_without_details_is_replaced_by_its_first_scan(self):
        empty = Host.objects.create(hostname="empty")
        self.warm()
        self.add_details(empty, T0)
        self.assertEqual(utils.get_osdetails(), {"Debian-12": [("empty", empty.id)]})


class IndexViewTests(CacheTestCase):
    URL = "/servers/"

    def setUp(self):
        super().setUp()
        user = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(user)
        self.a = Host.objects.create(hostname="a")
        HostDetails.objects.create(host=self.a, time=T0, osname="Debian", osrelease="12")

    def test_uses_cache(self):
        self.warm()
        self.r.hset(utils.LATEST_HOSTS_KEY, self.a.id, '["a", "Cached-1", 1, 0]')
        # session + user + "any uncached rows?", nothing for the hosts
        with self.assertNumQueries(3):
            response = self.client.get(self.URL)
        self.assertEqual(response.context["osdetails"], {"Cached-1": [("a", self.a.id)]})

    def test_falls_back_to_database_when_cache_is_incomplete(self):
        # A partial cache (redis flushed, then one import) must not hide hosts.
        b = Host.objects.create(hostname="b")
        self.add_details(b, T0, osrelease="13")
        # A host without any HostDetails must not break the page.
        empty = Host.objects.create(hostname="empty")
        response = self.client.get(self.URL)
        self.assertEqual(
            response.context["osdetails"],
            {
                "None-None": [("empty", empty.id)],
                "Debian-13": [("b", b.id)],
                "Debian-12": [("a", self.a.id)],
            },
        )

    def test_falls_back_to_database_when_redis_is_down(self):
        with mock.patch("servers.views.get_osdetails", side_effect=redis.ConnectionError):
            response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["osdetails"], {"Debian-12": [("a", self.a.id)]})
