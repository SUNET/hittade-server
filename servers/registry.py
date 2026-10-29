"""Turn the image IDs hosts report into image config digests.

Docker reports the image config digest as a container's image ID, and that is
what container scans are stored under (ContainerBase.cid). Docker with the
containerd image store (the default for new installs since Docker 29) reports
the registry manifest digest instead, so the same image shows up with two IDs
and never matches its scan. The registry knows both: the manifest names its
config digest.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

MANIFEST_ACCEPT = (
    "application/vnd.docker.distribution.manifest.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.index.v1+json"
)
INDEX_TYPES = {
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
}
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMEOUT = 10


def registry_and_repo(image):
    """("registry", "repo") of an image name like reg/repo:tag, or None."""
    name = image.split("@", 1)[0]
    # A ":" after the last "/" is the tag; one before it is a registry port.
    if ":" in name.rsplit("/", 1)[-1]:
        name = name.rsplit(":", 1)[0]
    registry, _, repo = name.partition("/")
    if not repo:
        return None
    return registry, repo


def bearer_token(challenge, repo):
    """Anonymous pull token for a 'WWW-Authenticate: Bearer ...' challenge."""
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = params.pop("realm", None)
    if not realm or not challenge.lower().startswith("bearer"):
        return None
    params["scope"] = f"repository:{repo}:pull"
    url = f"{realm}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("token") or data.get("access_token")


def fetch_manifest(registry, repo, reference):
    "The manifest of repo@reference, or None when the registry has none."
    url = f"https://{registry}/v2/{repo}/manifests/{reference}"
    headers = {"Accept": MANIFEST_ACCEPT}
    try:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=TIMEOUT
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 401:
                return None
            token = bearer_token(e.headers.get("WWW-Authenticate", ""), repo)
            if not token:
                return None
            headers["Authorization"] = f"Bearer {token}"
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=TIMEOUT
            ) as response:
                return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None


def config_digest(image, image_id):
    """Config digest for image_id when it is a manifest digest of image.

    Returns None when image_id is not a manifest in the image's repository
    (it is then already a config digest), when the registry is not one of
    settings.CONTAINER_REGISTRIES, or when the registry cannot be reached.
    """
    if not DIGEST.match(image_id or ""):
        return None
    parts = registry_and_repo(image)
    if parts is None or parts[0] not in settings.CONTAINER_REGISTRIES:
        return None
    registry, repo = parts
    manifest = fetch_manifest(registry, repo, image_id)
    if manifest is None:
        return None
    if manifest.get("mediaType") in INDEX_TYPES or "manifests" in manifest:
        # A multi-platform image: the hosts are linux/amd64.
        for entry in manifest.get("manifests", []):
            platform = entry.get("platform") or {}
            if platform.get("os") == "linux" and platform.get("architecture") == "amd64":
                manifest = fetch_manifest(registry, repo, entry["digest"])
                break
        else:
            return None
        if manifest is None:
            return None
    digest = (manifest.get("config") or {}).get("digest")
    if digest and DIGEST.match(digest) and digest != image_id:
        return digest
    return None
