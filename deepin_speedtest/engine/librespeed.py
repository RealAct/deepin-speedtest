"""Client for self-hosted LibreSpeed servers (https://github.com/librespeed).

LibreSpeed is a free, self-hostable HTTP speed test. It uses plain HTTPS
requests against ``backend/garbage.php`` (download) and ``backend/empty.php``
(upload), with several parallel streams. Only ``https://`` servers are
accepted.
"""

from __future__ import annotations

import os
import ssl
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.parse import urlsplit

from .https import USER_AGENT, open_connection

STREAMS = 4
HIGH_SPEED_STREAMS = 8        # multi-gigabit links need more parallel TCP streams
DURATION = 10.0
CHUNK = 64 * 1024
HIGH_SPEED_CHUNK = 512 * 1024
UPLOAD_BODY = 4 * 1024 * 1024
HIGH_SPEED_UPLOAD_BODY = 64 * 1024 * 1024
PROGRESS_INTERVAL = 0.2

Emit = Callable[[Dict[str, Any]], None]


class _Counter:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.bytes = 0
        self.errors: List[str] = []

    def add(self, n: int) -> None:
        with self.lock:
            self.bytes += n


def _target(base_url: str):
    parts = urlsplit(base_url)
    return parts.hostname or "", parts.port or 443, parts.path or "/"


def _run(worker: Callable[[float, _Counter], None], phase: str, emit: Emit, streams: int = STREAMS) -> float:
    counter = _Counter()
    deadline = time.monotonic() + DURATION
    threads = [threading.Thread(target=worker, args=(deadline, counter), daemon=True)
               for _ in range(streams)]
    start = time.monotonic()
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(PROGRESS_INTERVAL)
        elapsed = time.monotonic() - start
        with counter.lock:
            nbytes = counter.bytes
        emit({"type": "progress", "phase": phase, "value": nbytes * 8 / elapsed / 1e6,
              "fraction": min(1.0, elapsed / DURATION)})
        if elapsed > DURATION + 15:
            break  # stalled sockets: daemon threads die with the process
    elapsed = min(time.monotonic() - start, DURATION + 15)
    if counter.bytes == 0:
        raise OSError(counter.errors[0] if counter.errors else "no data was transferred")
    return round(counter.bytes * 8 / elapsed / 1e6, 2)


def download(base_url: str, emit: Emit, *, ssl_context: Optional[ssl.SSLContext] = None,
             path: str = "backend/garbage.php", high_speed: bool = False) -> Dict[str, Any]:
    host, port, base = _target(base_url)
    chunk = HIGH_SPEED_CHUNK if high_speed else CHUNK
    # ckSize is the number of 1 MiB chunks the server sends per request.
    url = base + path + ("?ckSize=1024" if high_speed else "?ckSize=100")

    def worker(deadline: float, counter: _Counter) -> None:
        try:
            while time.monotonic() < deadline:
                conn = open_connection(host, port, timeout=10.0, ssl_context=ssl_context)
                try:
                    conn.request("GET", url,
                                 headers={"User-Agent": USER_AGENT, "Cache-Control": "no-store"})
                    resp = conn.getresponse()
                    if resp.status != 200:
                        raise OSError("server answered HTTP %d" % resp.status)
                    buf = bytearray(chunk)
                    while time.monotonic() < deadline:
                        got = resp.readinto(buf)
                        if not got:
                            break
                        counter.add(got)
                finally:
                    conn.close()
        except (OSError, ValueError) as exc:  # http.client errors derive from these
            counter.errors.append(str(exc)[:200])

    streams = HIGH_SPEED_STREAMS if high_speed else STREAMS
    return {"download_mbps": _run(worker, "download", emit, streams), "download_latency_ms": None}


def upload(base_url: str, emit: Emit, *, ssl_context: Optional[ssl.SSLContext] = None,
           path: str = "backend/empty.php", high_speed: bool = False) -> Dict[str, Any]:
    host, port, base = _target(base_url)
    chunk = HIGH_SPEED_CHUNK if high_speed else CHUNK
    body_size = HIGH_SPEED_UPLOAD_BODY if high_speed else UPLOAD_BODY
    filler = os.urandom(chunk)

    def body(deadline: float, counter: _Counter) -> Iterator[bytes]:
        sent = 0
        while sent < body_size:
            if time.monotonic() >= deadline:
                raise _Stop()
            yield filler
            sent += chunk
            counter.add(chunk)

    def worker(deadline: float, counter: _Counter) -> None:
        try:
            while time.monotonic() < deadline:
                conn = open_connection(host, port, timeout=10.0, ssl_context=ssl_context)
                try:
                    conn.request("POST", base + path, body=body(deadline, counter),
                                 headers={"User-Agent": USER_AGENT,
                                          "Content-Type": "application/octet-stream",
                                          "Content-Length": str(body_size)})
                    resp = conn.getresponse()
                    resp.read(4096)
                    if resp.status != 200:
                        raise OSError("server answered HTTP %d" % resp.status)
                finally:
                    conn.close()
        except _Stop:
            pass
        except (OSError, ValueError) as exc:
            counter.errors.append(str(exc)[:200])

    streams = HIGH_SPEED_STREAMS if high_speed else STREAMS
    return {"upload_mbps": _run(worker, "upload", emit, streams), "upload_latency_ms": None}


class _Stop(Exception):
    pass
