from django.test import TestCase
from django.urls import reverse
from test_container_links import user_with

from servers.models import Host


class HostsPageTests(TestCase):
    def test_shows_total_hosts(self):
        for name in ("web1", "db1", "ci1"):
            Host.objects.create(hostname=name)
        self.client.force_login(user_with("view_host"))
        response = self.client.get(reverse("servers:hosts"))
        self.assertContains(
            response, 'Total hosts: <span class="ht-badge -info">3</span>', html=False
        )
