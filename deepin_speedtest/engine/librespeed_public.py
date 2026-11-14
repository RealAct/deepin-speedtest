"""Server discovery for the public LibreSpeed network.

LibreSpeed (https://librespeed.org) is an open-source speed test whose
volunteer-run public servers are published as a JSON list for any client
to use. We fetch that list over HTTPS, validate every entry, measure a TCP
handshake to each candidate and return the closest ones.
"""

from __future__ import annotations

import json
import socket
import ssl
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from ..validate import (ValidationError, clean_text, validate_https_base, validate_rel_path)
from .https import get_bytes

LIST_HOST = "librespeed.org"
LIST_PATH = "/backend-servers/servers.php"
MAX_LIST_BYTES = 512 * 1024
MAX_CANDIDATES = 24
MAX_SERVERS = 8
PROBE_TIMEOUT = 1.5


def parse_list(body: bytes) -> List[Dict[str, Any]]:
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValidationError("LibreSpeed server list is not valid JSON")
    if not isinstance(doc, list):
        raise ValidationError("LibreSpeed server list has an unexpected format")
    servers: List[Dict[str, Any]] = []
    seen = set()
    for item in doc:
        try:
            server = _parse_entry(item)
        except ValidationError:
            continue  # skip anything that is not exactly what we expect
        if server["id"] in seen:
            continue
        seen.add(server["id"])
        servers.append(server)
        if len(servers) >= MAX_CANDIDATES:
            break
    if not servers:
        raise ValidationError("no usable LibreSpeed servers were returned")
    return servers


def _parse_entry(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValidationError("bad entry")
    raw = item.get("server")
    if not isinstance(raw, str) or len(raw) > 512:
        raise ValidationError("bad server URL")
    raw = raw.strip()
    if raw.startswith("//"):
        raw = "https:" + raw          # protocol-relative entries: always use TLS
    base = validate_https_base(raw)   # rejects http:// and anything odd
    parts = urlsplit(base)
    if (parts.port or 443) != 443:
        raise ValidationError("only port 443 servers are used")  # matches the sandbox port rule
    name = clean_text(item.get("name", ""), 80) if isinstance(item.get("name"), str) else ""
    sponsor = clean_text(item.get("sponsorName", ""), 60) if isinstance(item.get("sponsorName"), str) else ""
    return {
        "backend": "librespeed",
        "custom": False,
        "id": "librespeed:" + base,
        "name": name or (parts.hostname or ""),
        "host": parts.hostname or "",
        "provider": ("LibreSpeed · " + sponsor) if sponsor else "LibreSpeed",
        "base_url": base,
        "dl_path": validate_rel_path(item.get("dlURL", "backend/garbage.php")),
        "ul_path": validate_rel_path(item.get("ulURL", "backend/empty.php")),
    }


def _probe(server: Dict[str, Any], results: Dict[str, float]) -> None:
    try:
        t0 = time.perf_counter()
        sock = socket.create_connection((server["host"], 443), timeout=PROBE_TIMEOUT)
        results[server["id"]] = time.perf_counter() - t0
        sock.close()
    except OSError:
        pass


def locate(ssl_context: Optional[ssl.SSLContext] = None, timeout: float = 10.0) -> List[Dict[str, Any]]:
    body = get_bytes(LIST_HOST, LIST_PATH, timeout=timeout, limit=MAX_LIST_BYTES, ssl_context=ssl_context)
    candidates = parse_list(body)
    results: Dict[str, float] = {}
    threads = [threading.Thread(target=_probe, args=(s, results), daemon=True) for s in candidates]
    for t in threads:
        t.start()
    deadline = time.monotonic() + PROBE_TIMEOUT + 3.0   # DNS can be slow
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    reachable = sorted((s for s in candidates if s["id"] in results), key=lambda s: results[s["id"]])
    if not reachable:
        raise OSError("no LibreSpeed server answered")
    return reachable[:MAX_SERVERS]
