"""ndt7 client (https://github.com/m-lab/ndt-server/blob/main/spec/ndt7-protocol.md).

ndt7 is M-Lab's open, documented speed-test protocol. A test is one TLS
WebSocket per direction, ~10 seconds each. The server periodically sends
JSON measurement messages (including kernel TCP_INFO), which we use for the
loaded-latency figure and for the upload rate as seen by the receiver.
"""

from __future__ import annotations

import json
import select
import ssl
import statistics
import time
from typing import Any, Callable, Dict, List, Optional

from .wsclient import OP_TEXT, ConnectionClosed, WebSocket, WebSocketError, random_filler

SUBPROTOCOL = "net.measurementlab.ndt.v7"
MAX_DURATION = 15.0           # hard stop for either direction (seconds)
UPLOAD_DURATION = 10.0        # client-side upload length, per the spec
MIN_MESSAGE = 1 << 13
MAX_MESSAGE = 1 << 24
PROGRESS_INTERVAL = 0.2

Emit = Callable[[Dict[str, Any]], None]


def _mbps(nbytes: float, seconds: float) -> float:
    return (nbytes * 8.0 / seconds / 1e6) if seconds > 0 else 0.0


def _parse_measurement(data: bytes) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _num(doc: Optional[Dict[str, Any]], *path: str) -> Optional[float]:
    cur: Any = doc
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    if isinstance(cur, bool) or not isinstance(cur, (int, float)):
        return None
    if cur < 0 or cur > 1e15:
        return None
    return float(cur)


def download(url: str, emit: Emit, *, ssl_context: Optional[ssl.SSLContext] = None) -> Dict[str, Any]:
    ws = WebSocket(url, SUBPROTOCOL, timeout=10.0, ssl_context=ssl_context)
    ws.connect()
    start = time.monotonic()
    state = {"bytes": 0, "last": start}
    rtts: List[float] = []

    def on_bytes(n: int) -> None:
        state["bytes"] += n
        now = time.monotonic()
        if now - state["last"] >= PROGRESS_INTERVAL:
            state["last"] = now
            elapsed = now - start
            emit({"type": "progress", "phase": "download", "value": _mbps(state["bytes"], elapsed),
                  "fraction": min(1.0, elapsed / 10.0)})
            if elapsed > MAX_DURATION:
                raise _Deadline()

    try:
        while time.monotonic() - start < MAX_DURATION:
            op, data = ws.recv(on_bytes)
            if op == OP_TEXT:
                rtt = _num(_parse_measurement(data), "TCPInfo", "RTT")
                if rtt is not None:
                    rtts.append(rtt / 1000.0)
    except (ConnectionClosed, _Deadline):
        pass
    finally:
        ws.close()
    elapsed = time.monotonic() - start
    if state["bytes"] == 0:
        raise WebSocketError("server sent no data")
    return {
        "download_mbps": round(_mbps(state["bytes"], elapsed), 2),
        "download_latency_ms": round(statistics.median(rtts), 2) if rtts else None,
        "download_bytes": state["bytes"],
    }


def upload(url: str, emit: Emit, *, ssl_context: Optional[ssl.SSLContext] = None) -> Dict[str, Any]:
    ws = WebSocket(url, SUBPROTOCOL, timeout=10.0, ssl_context=ssl_context)
    ws.connect()
    assert ws._sock is not None
    sock = ws._sock
    filler = random_filler(MAX_MESSAGE)
    chunks: Dict[int, bytes] = {MAX_MESSAGE: filler}
    size = MIN_MESSAGE
    sent = 0
    start = time.monotonic()
    last = start
    rtts: List[float] = []
    server: Dict[str, Optional[float]] = {"bytes": None, "elapsed": None}

    def handle(data: bytes) -> None:
        doc = _parse_measurement(data)
        rtt = _num(doc, "TCPInfo", "RTT")
        if rtt is not None:
            rtts.append(rtt / 1000.0)
        received = _num(doc, "TCPInfo", "BytesReceived")
        t_us = _num(doc, "TCPInfo", "ElapsedTime")
        if received is not None and t_us:
            server["bytes"], server["elapsed"] = received, t_us / 1e6

    def drain(wait: float) -> None:
        while sock.pending() or select.select([sock], [], [], wait)[0]:
            op, data = ws.recv()
            if op == OP_TEXT:
                handle(data)
            wait = 0.0

    try:
        while True:
            now = time.monotonic()
            elapsed = now - start
            if elapsed >= UPLOAD_DURATION:
                break
            drain(0.0)
            chunk = chunks.get(size)
            if chunk is None:
                chunk = chunks[size] = filler[:size]
            ws.send_binary_filler(chunk)
            sent += size
            if size < MAX_MESSAGE and size < sent / 16:
                size *= 2
            if now - last >= PROGRESS_INTERVAL:
                last = now
                rate = _server_rate(server) or _mbps(sent, elapsed)
                emit({"type": "progress", "phase": "upload", "value": rate,
                      "fraction": min(1.0, elapsed / UPLOAD_DURATION)})
        # Collect the server's final measurements for a moment.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            drain(max(0.0, deadline - time.monotonic()))
    except ConnectionClosed:
        pass
    finally:
        ws.close()
    elapsed = time.monotonic() - start
    rate = _server_rate(server)
    if rate is None:
        rate = _mbps(sent, min(elapsed, UPLOAD_DURATION))
    return {
        "upload_mbps": round(rate, 2),
        "upload_latency_ms": round(statistics.median(rtts), 2) if rtts else None,
        "upload_bytes": sent,
    }


def _server_rate(server: Dict[str, Optional[float]]) -> Optional[float]:
    if server["bytes"] is None or not server["elapsed"]:
        return None
    return _mbps(server["bytes"], server["elapsed"])


class _Deadline(Exception):
    pass
