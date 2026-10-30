from datetime import timedelta

from django.test import TestCase
from test_container_links import T0, scan

from api.models import APIKey
from servers.models import Host

URL = "/api/containers/running"
R = "docker.sunet.se"


class RunningImagesApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _, cls.key = APIKey.generate(name="cscan")
        web = Host.objects.create(hostname="web1")
        db = Host.objects.create(hostname="db1")
        scan(web, T0, [
            (f"{R}/app:1", "sha256:a", "app"),
            (f"{R}/app:1", "sha256:a", "app-2"),  # two containers, one image
            (f"{R}/proxy", "sha256:p", "proxy"),  # no tag: docker runs latest
            (f"{R}/pinned@sha256:abcd", "sha256:d", "pinned"),
        ])
        # db1's older scan ran old:1; only its latest scan counts.
        scan(db, T0, [(f"{R}/old:1", "sha256:o", "old")])
        scan(db, T0 + timedelta(hours=1), [(f"{R}/app:1", "sha256:a", "app")])

    def test_lists_images_of_the_latest_scans(self):
        response = self.client.get(URL, headers={"X-API-Key": self.key})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [f"{R}/app:1", f"{R}/pinned@sha256:abcd", f"{R}/proxy:latest"],
        )

    def test_needs_an_api_key(self):
        self.assertEqual(self.client.get(URL).status_code, 401)
