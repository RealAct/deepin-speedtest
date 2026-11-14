"""Input validation shared by the UI and the measurement engine.

Everything that crosses a trust boundary (user input, network responses,
messages from the engine process, files on disk) goes through a function in
this module before it is used.
"""

from __future__ import annotations

import ipaddress
import math
import re
import unicodedata
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MLAB_SUFFIX = ".measurement-lab.org"
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_PARAM_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_TOKEN_CHARS = re.compile(r"^[A-Za-z0-9._~+/=-]{1,4096}$")
MAX_TEXT = 256
MAX_URL = 8192


class ValidationError(ValueError):
    """Raised when untrusted input does not match what we expect."""


def clean_text(value: Any, limit: int = MAX_TEXT) -> str:
    """Return a printable, length-limited single-line string."""
    if not isinstance(value, str):
        raise ValidationError("expected a string")
    out = []
    for ch in value:
        cat = unicodedata.category(ch)
        if cat[0] == "C":  # control, format, surrogate, private use, unassigned
            continue
        out.append(ch)
        if len(out) >= limit:
            break
    return "".join(out).strip()


def finite_number(value: Any, lo: float = 0.0, hi: float = 1e7) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("expected a number")
    f = float(value)
    if not math.isfinite(f) or f < lo or f > hi:
        raise ValidationError("number out of range")
    return f


def optional_number(value: Any, lo: float = 0.0, hi: float = 1e7) -> Optional[float]:
    if value is None:
        return None
    return finite_number(value, lo, hi)


def validate_hostname(host: str) -> str:
    """Validate a DNS name or IP literal; returns the canonical lowercase form."""
    if not isinstance(host, str) or not host or len(host) > 253:
        raise ValidationError("invalid host name")
    host = host.strip().rstrip(".").lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        raise ValidationError("invalid host name")
    labels = ascii_host.split(".")
    if len(labels) < 2 or not all(_LABEL.match(lbl) for lbl in labels):
        raise ValidationError("invalid host name")
    if labels[-1].isdigit():
        raise ValidationError("invalid host name")
    return ascii_host


def _check_port(port: Optional[int]) -> int:
    if port is None:
        return 443
    if not 1 <= port <= 65535:
        raise ValidationError("invalid port")
    return port


def parse_server_address(text: str) -> Tuple[str, int]:
    """Parse a user-typed ``host`` or ``host:port`` for a self-hosted server."""
    text = clean_text(text, 300)
    if "://" in text:
        parts = urlsplit(text)
        if parts.scheme not in ("https", "wss"):
            raise ValidationError("only https:// or wss:// servers are allowed")
        if parts.username or parts.password:
            raise ValidationError("credentials in URLs are not allowed")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValidationError("enter just a host name (and optional port)")
        try:
            port = parts.port
        except ValueError:
            raise ValidationError("invalid port")
        return validate_hostname(parts.hostname or ""), _check_port(port)
    parts = urlsplit("//" + text)
    if parts.username or parts.password or parts.path or parts.query or parts.fragment:
        raise ValidationError("enter just a host name (and optional port)")
    try:
        port = parts.port
    except ValueError:
        raise ValidationError("invalid port")
    return validate_hostname(parts.hostname or ""), _check_port(port)


def validate_https_base(url: str) -> str:
    """Validate a self-hosted LibreSpeed base URL (``https://host[:port]/path/``)."""
    if not isinstance(url, str) or len(url) > 1024:
        raise ValidationError("invalid URL")
    url = clean_text(url, 1024)
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValidationError("only https:// URLs are allowed")
    if parts.username or parts.password:
        raise ValidationError("credentials in URLs are not allowed")
    if parts.query or parts.fragment:
        raise ValidationError("the server URL must not contain ? or #")
    try:
        port = parts.port
    except ValueError:
        raise ValidationError("invalid port")
    host = validate_hostname(parts.hostname or "")
    path = parts.path or "/"
    if not re.match(r"^/[A-Za-z0-9._~/%-]*$", path) or "/../" in path + "/" or "/./" in path + "/":
        raise ValidationError("invalid URL path")
    if not path.endswith("/"):
        path += "/"
    netloc = ("[%s]" % host) if ":" in host else host
    if port is not None:
        netloc += ":%d" % _check_port(port)
    return urlunsplit(("https", netloc, path, "", ""))


def validate_ndt7_url(url: str, *, allow_any_host: bool, expected_test: str) -> str:
    """Validate an ndt7 WebSocket URL.

    ``allow_any_host`` is only true for servers the user typed in themselves;
    URLs that come from the M-Lab Locate API must point at M-Lab hosts.
    """
    if not isinstance(url, str) or len(url) > MAX_URL:
        raise ValidationError("invalid ndt7 URL")
    parts = urlsplit(url)
    if parts.scheme != "wss":
        raise ValidationError("ndt7 URL must use wss://")
    if parts.username or parts.password or parts.fragment:
        raise ValidationError("invalid ndt7 URL")
    try:
        port = parts.port
    except ValueError:
        raise ValidationError("invalid port")
    _check_port(port)
    host = validate_hostname(parts.hostname or "")
    if not allow_any_host and not host.endswith(MLAB_SUFFIX):
        raise ValidationError("server is not an M-Lab host")
    if parts.path != "/ndt/v7/" + expected_test:
        raise ValidationError("unexpected ndt7 path")
    query = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=False)
    if len(query) > 16:
        raise ValidationError("too many ndt7 URL parameters")
    for key, value in query:
        if not _PARAM_KEY.match(key) or not _TOKEN_CHARS.match(value or "x"):
            raise ValidationError("unexpected ndt7 URL parameter")
    return urlunsplit(("wss", parts.netloc.lower(), parts.path, urlencode(query), ""))


def with_client_params(url: str, params: Dict[str, str]) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in params]
    query.extend(sorted(params.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
