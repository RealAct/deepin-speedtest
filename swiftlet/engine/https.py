"""Minimal HTTPS helpers with hard size and time limits."""

from __future__ import annotations

import http.client
import ssl
from typing import Optional

from .. import __version__
from .wsclient import make_tls_context

USER_AGENT = "swiftlet/%s" % __version__


class HTTPSError(Exception):
    pass


def open_connection(host: str, port: int, *, timeout: float,
                    ssl_context: Optional[ssl.SSLContext] = None) -> http.client.HTTPSConnection:
    ctx = ssl_context or make_tls_context()
    return http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)


def get_bytes(host: str, path: str, *, port: int = 443, timeout: float = 10.0,
              limit: int = 1 << 20, ssl_context: Optional[ssl.SSLContext] = None) -> bytes:
    """GET ``https://host:port/path`` and return the body (at most ``limit`` bytes).

    Redirects are not followed: a redirect could silently move us to plain
    HTTP or to a host we did not validate.
    """
    conn = open_connection(host, port, timeout=timeout, ssl_context=ssl_context)
    try:
        conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise HTTPSError("server answered HTTP %d" % resp.status)
        body = resp.read(limit + 1)
        if len(body) > limit:
            raise HTTPSError("response too large")
        return body
    finally:
        conn.close()
