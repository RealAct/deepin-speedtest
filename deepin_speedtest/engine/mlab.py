"""Server discovery through the public M-Lab Locate API (v2).

The Locate API is the documented, permission-free way for third-party ndt7
clients to find nearby M-Lab servers. It returns short-lived access tokens
embedded in the test URLs.
"""

from __future__ import annotations

import json
import ssl
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from .. import __version__
from ..validate import ValidationError, clean_text, validate_hostname, validate_ndt7_url
from .https import get_bytes

LOCATE_HOST = "locate.measurementlab.net"
LOCATE_PATH = "/v2/nearest/ndt/ndt7"
MAX_SERVERS = 8


def client_params() -> Dict[str, str]:
    # Only the client name and version are sent, as the ndt7 spec asks.
    return {"client_name": "deepin-speedtest", "client_version": __version__}


def locate(ssl_context: Optional[ssl.SSLContext] = None, timeout: float = 10.0) -> List[Dict[str, Any]]:
    body = get_bytes(LOCATE_HOST, LOCATE_PATH + "?" + urlencode(client_params()),
                     timeout=timeout, limit=256 * 1024, ssl_context=ssl_context)
    return parse_locate(body)


def parse_locate(body: bytes) -> List[Dict[str, Any]]:
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValidationError("Locate API returned invalid JSON")
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
        raise ValidationError("Locate API returned an unexpected document")
    servers: List[Dict[str, Any]] = []
    for item in doc["results"][:MAX_SERVERS]:
        try:
            servers.append(_parse_result(item))
        except ValidationError:
            continue  # skip malformed entries rather than trusting them
    if not servers:
        raise ValidationError("no usable M-Lab servers were returned")
    return servers


def _parse_result(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValidationError("bad result")
    machine = validate_hostname(item.get("machine", ""))
    loc = item.get("location") if isinstance(item.get("location"), dict) else {}
    city = clean_text(loc.get("city", ""), 80) if isinstance(loc.get("city", ""), str) else ""
    country = clean_text(loc.get("country", ""), 8) if isinstance(loc.get("country", ""), str) else ""
    urls = item.get("urls")
    if not isinstance(urls, dict):
        raise ValidationError("bad urls")
    down = validate_ndt7_url(urls.get("wss:///ndt/v7/download", ""), allow_any_host=False,
                             expected_test="download")
    up = validate_ndt7_url(urls.get("wss:///ndt/v7/upload", ""), allow_any_host=False,
                           expected_test="upload")
    label = ", ".join(p for p in (city, country) if p) or machine
    return {
        "backend": "ndt7",
        "id": machine,
        "name": label,
        "host": machine,
        "provider": "M-Lab",
        "download_url": down,
        "upload_url": up,
    }
