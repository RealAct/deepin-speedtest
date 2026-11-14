"""Entry point of the sandboxed measurement engine.

The desktop UI never talks to the network itself. It starts this module as a
separate, unprivileged child process, writes one JSON request line to its
stdin and reads JSON event lines from its stdout. The engine locks itself
down (see ``swiftlet.hardening``) before opening any connection.
"""

from __future__ import annotations

import json
import socket
import ssl
import sys
import time
import traceback
from typing import Any, Dict, Iterable, Optional, Set
from urllib.parse import urlsplit

# Import everything that will be needed *before* the sandbox is applied.
import encodings.idna  # noqa: F401  (lazy-loaded by socket for IDN host names)
import http.client  # noqa: F401
import select  # noqa: F401
import statistics  # noqa: F401
import threading  # noqa: F401

from .. import hardening
from ..validate import ValidationError, validate_https_base, validate_ndt7_url
from . import latency, librespeed, mlab, ndt7
from .https import HTTPSError
from .wsclient import WebSocketError

MAX_REQUEST = 64 * 1024


class Engine:
    def __init__(self, out=None, ssl_context: Optional[ssl.SSLContext] = None) -> None:
        self._out = out or sys.stdout
        self._ctx = ssl_context

    def emit(self, event: Dict[str, Any]) -> None:
        self._out.write(json.dumps(event, separators=(",", ":"), allow_nan=False) + "\n")
        self._out.flush()

    # -- request handling ---------------------------------------------

    @staticmethod
    def parse_request(raw: bytes) -> Dict[str, Any]:
        if len(raw) > MAX_REQUEST:
            raise ValidationError("request too large")
        try:
            req = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ValidationError("request is not valid JSON")
        if not isinstance(req, dict) or req.get("op") not in ("locate", "run"):
            raise ValidationError("unknown request")
        if req["op"] == "run":
            server = req.get("server")
            if not isinstance(server, dict):
                raise ValidationError("missing server")
            backend = server.get("backend")
            if backend == "ndt7":
                custom = server.get("custom") is True
                server = {
                    "backend": "ndt7",
                    "custom": custom,
                    "download_url": validate_ndt7_url(server.get("download_url", ""),
                                                      allow_any_host=custom, expected_test="download"),
                    "upload_url": validate_ndt7_url(server.get("upload_url", ""),
                                                    allow_any_host=custom, expected_test="upload"),
                }
            elif backend == "librespeed":
                server = {"backend": "librespeed", "base_url": validate_https_base(server.get("base_url", ""))}
            else:
                raise ValidationError("unknown backend")
            req = {"op": "run", "server": server}
        else:
            req = {"op": "locate"}
        return req

    @staticmethod
    def ports_for(req: Dict[str, Any]) -> Set[int]:
        if req["op"] == "locate":
            return {443}
        server = req["server"]
        urls: Iterable[str]
        if server["backend"] == "ndt7":
            urls = (server["download_url"], server["upload_url"])
        else:
            urls = (server["base_url"],)
        return {urlsplit(u).port or 443 for u in urls}

    def handle(self, req: Dict[str, Any]) -> None:
        if req["op"] == "locate":
            self.emit({"type": "servers", "servers": mlab.locate(ssl_context=self._ctx)})
            return
        server = req["server"]
        if server["backend"] == "ndt7":
            target = urlsplit(server["download_url"])
        else:
            target = urlsplit(server["base_url"])
        host, port = target.hostname or "", target.port or 443

        started = time.time()
        self.emit({"type": "stage", "phase": "ping"})
        lat = latency.summarize(latency.tcp_rtt_samples(host, port, emit=self.emit))
        self.emit({"type": "latency", "ping_ms": lat["ping_ms"], "jitter_ms": lat["jitter_ms"]})

        self.emit({"type": "stage", "phase": "download"})
        if server["backend"] == "ndt7":
            down = ndt7.download(server["download_url"], self.emit, ssl_context=self._ctx)
        else:
            down = librespeed.download(server["base_url"], self.emit, ssl_context=self._ctx)
        self.emit({"type": "measured", "phase": "download", "value": down["download_mbps"]})

        self.emit({"type": "stage", "phase": "upload"})
        if server["backend"] == "ndt7":
            up = ndt7.upload(server["upload_url"], self.emit, ssl_context=self._ctx)
        else:
            up = librespeed.upload(server["base_url"], self.emit, ssl_context=self._ctx)
        self.emit({"type": "measured", "phase": "upload", "value": up["upload_mbps"]})

        self.emit({
            "type": "result",
            "timestamp": int(started),
            "host": host,
            "ping_ms": lat["ping_ms"],
            "jitter_ms": lat["jitter_ms"],
            "download_mbps": down["download_mbps"],
            "upload_mbps": up["upload_mbps"],
            "download_latency_ms": down.get("download_latency_ms"),
            "upload_latency_ms": up.get("upload_latency_ms"),
        })


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "The server's TLS certificate could not be verified."
    if isinstance(exc, ssl.SSLError):
        return "A secure (TLS) connection could not be established."
    if isinstance(exc, socket.gaierror):
        return "The server name could not be resolved. Check your connection."
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "The server stopped responding."
    if isinstance(exc, (ValidationError, WebSocketError, HTTPSError)):
        return str(exc)[:200] or exc.__class__.__name__
    if isinstance(exc, OSError):
        return (exc.strerror or str(exc) or "network error")[:200]
    return "Unexpected error (%s)" % exc.__class__.__name__


def main() -> int:
    hardening.refuse_root()
    engine = Engine()
    try:
        req = Engine.parse_request(sys.stdin.buffer.readline(MAX_REQUEST + 1))
        report = hardening.sandbox_engine(Engine.ports_for(req))
        engine.emit({"type": "sandbox", "landlock_abi": report.get("landlock_abi", 0),
                     "no_new_privs": bool(report.get("no_new_privs"))})
        engine.handle(req)
        return 0
    except KeyboardInterrupt:
        return 130
    except BaseException as exc:  # report every failure as a structured event
        if "--debug" in sys.argv:
            traceback.print_exc(file=sys.stderr)
        try:
            engine.emit({"type": "error", "message": friendly_error(exc)})
        except (OSError, ValueError):
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
