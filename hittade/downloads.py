"""Download the data of a page as a JSON file.

A page offers it with the "Download JSON" button of dashboard.html, which
shows when the view puts download=True in the context. The button asks for the
same page with format=json (as a query parameter, or as a form field for the
search pages, which POST), and the view then returns json_download() instead
of the HTML.
"""

import re

from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from django.utils import timezone


def wants_json(request) -> bool:
    "Whether the Download JSON button asked for this page."
    return (request.GET.get("format") or request.POST.get("format")) == "json"


def download_name(*parts) -> str:
    """hittade-<parts>-<date>.json, safe as a file name on any system.

    Characters other than letters, digits and . + _ - become "_", so
    "platform.sunet.se/eduid/app:v1" is "platform.sunet.se_eduid_app_v1".
    """
    words = [re.sub(r"[^A-Za-z0-9.+_-]+", "_", str(p)).strip("._") for p in parts]
    date = timezone.localdate().isoformat()
    return "-".join(["hittade", *[w for w in words if w], date]) + ".json"


def json_download(data: dict, *name_parts) -> JsonResponse:
    "data as an attached, indented JSON file named by download_name(*name_parts)."
    response = JsonResponse(
        {"generated_at": timezone.now(), **data},
        encoder=DjangoJSONEncoder,
        json_dumps_params={"indent": 2},
    )
    response["Content-Disposition"] = f'attachment; filename="{download_name(*name_parts)}"'
    return response
