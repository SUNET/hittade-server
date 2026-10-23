from datetime import UTC, datetime, timedelta, timezone
from unittest import mock

import fakeredis
import redis
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from servers import utils
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


class WarmServerCacheTests(CacheTestCase):
    def test_rebuilds_from_database(self):
        a = Host.objects.create(hostname="a")
        b = Host.objects.create(hostname="b")
        HostDetails.objects.create(host=a, time=T0, osname="Debian", osrelease="12")
        HostDetails.objects.create(host=a, time=T0 + timedelta(days=1), osname="Debian", osrelease="13")
        HostDetails.objects.create(host=b, time=T0, osname="Ubuntu", osrelease="24.04")
        # Stale entries from before: a deleted host and the old cache format.
        self.r.hset(utils.LATEST_HOSTS_KEY, "gone", '[999, "Debian-11", 1, 0]')
        self.r.hset(utils.LEGACY_OSDETAILS_KEY, "Debian-11", "[]")

        call_command("warmservercache", stdout=mock.Mock())

        expected = {"Debian-13": [("a", a.id)], "Ubuntu-24.04": [("b", b.id)]}
        self.assertEqual(utils.get_osdetails(), expected)
        self.assertEqual(utils.osdetails_from_db(), expected)
        self.assertFalse(self.r.exists(utils.LEGACY_OSDETAILS_KEY))


class IndexViewTests(CacheTestCase):
    URL = "/servers/"

    def setUp(self):
        super().setUp()
        user = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(user)
        self.a = Host.objects.create(hostname="a")
        HostDetails.objects.create(host=self.a, time=T0, osname="Debian", osrelease="12")

    def test_uses_cache(self):
        self.r.hset(utils.LATEST_HOSTS_KEY, "a", f'[{self.a.id}, "Cached-1", 1, 0]')
        with self.assertNumQueries(2):  # session + user, nothing for the hosts
            response = self.client.get(self.URL)
        self.assertEqual(response.context["osdetails"], {"Cached-1": [("a", self.a.id)]})

    def test_falls_back_to_database_when_cache_is_empty(self):
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
