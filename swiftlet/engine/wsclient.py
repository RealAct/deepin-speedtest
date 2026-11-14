"""A small, strict WebSocket (RFC 6455) client over TLS.

Only the subset that ndt7 needs is implemented, and every frame coming from
the network is checked against hard limits before anything is buffered:

* TLS is mandatory (``wss://`` only) and the certificate is always verified.
* Frames from the server must not be masked and must use known opcodes.
* Control frames are limited to 125 bytes; data messages to ``max_message``.
* Text messages are buffered (bounded); binary payloads are counted and
  discarded without being stored, so a hostile server cannot make the client
  grow memory without bound.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import socket
import ssl
import struct
import time
from typing import Callable, Optional, Tuple
from urllib.parse import urlsplit

from .. import __version__

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

MAX_HANDSHAKE_BYTES = 16 * 1024
DEFAULT_MAX_MESSAGE = (1 << 24) + 1024  # ndt7 messages are at most 2^24 bytes
DEFAULT_MAX_TEXT = 64 * 1024


class WebSocketError(Exception):
    """Raised for any protocol violation or transport failure."""


class ConnectionClosed(WebSocketError):
    """The peer closed the connection (cleanly or not)."""


def make_tls_context() -> ssl.SSLContext:
    """Return a verifying client TLS context restricted to TLS 1.2+."""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    # Never fall back to anything that is not HTTP/1.1 for the upgrade.
    try:
        ctx.set_alpn_protocols(["http/1.1"])
    except NotImplementedError:  # pragma: no cover - very old OpenSSL
        pass
    return ctx


def _accept_value(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()  # noqa: S324 - mandated by RFC 6455
    return base64.b64encode(digest).decode("ascii")


class WebSocket:
    """A blocking WebSocket client connection."""

    def __init__(
        self,
        url: str,
        subprotocol: str,
        *,
        timeout: float = 15.0,
        ssl_context: Optional[ssl.SSLContext] = None,
        max_message: int = DEFAULT_MAX_MESSAGE,
        max_text: int = DEFAULT_MAX_TEXT,
    ) -> None:
        parts = urlsplit(url)
        if parts.scheme != "wss":
            raise WebSocketError("only wss:// URLs are allowed")
        if not parts.hostname:
            raise WebSocketError("URL has no host")
        if parts.username or parts.password:
            raise WebSocketError("credentials in URLs are not allowed")
        self.host = parts.hostname
        self.port = parts.port or 443
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        self._path = path
        self._subprotocol = subprotocol
        self._timeout = timeout
        self._ctx = ssl_context or make_tls_context()
        self._max_message = max_message
        self._max_text = max_text
        self._sock: Optional[ssl.SSLSocket] = None
        self._closed = False
        self._rbuf = bytearray()
        self._scratch = bytearray(256 * 1024)
        self.connect_seconds = 0.0

    # -- connection -----------------------------------------------------

    def connect(self) -> None:
        start = time.monotonic()
        raw = socket.create_connection((self.host, self.port), timeout=self._timeout)
        try:
            raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock = self._ctx.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise
        sock.settimeout(self._timeout)
        self._sock = sock
        self.connect_seconds = time.monotonic() - start
        try:
            self._handshake()
        except Exception:
            self.abort()
            raise

    def _handshake(self) -> None:
        assert self._sock is not None
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        host_header = "[%s]" % self.host if ":" in self.host else self.host
        if self.port != 443:
            host_header += ":%d" % self.port
        request = (
            "GET {path} HTTP/1.1\r\n"
            "Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: {proto}\r\n"
            "User-Agent: swiftlet/{ver}\r\n"
            "\r\n"
        ).format(path=self._path, host=host_header, key=key, proto=self._subprotocol, ver=__version__)
        self._sock.sendall(request.encode("ascii"))

        while b"\r\n\r\n" not in self._rbuf:
            if len(self._rbuf) > MAX_HANDSHAKE_BYTES:
                raise WebSocketError("handshake response too large")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketError("connection closed during handshake")
            self._rbuf += chunk
        head, _, rest = bytes(self._rbuf).partition(b"\r\n\r\n")
        self._rbuf = bytearray(rest)
        try:
            text = head.decode("iso-8859-1")
        except UnicodeDecodeError:  # pragma: no cover - latin-1 never fails
            raise WebSocketError("invalid handshake encoding")
        lines = text.split("\r\n")
        status = lines[0].split(" ", 2)
        if len(status) < 2 or status[0] != "HTTP/1.1" or status[1] != "101":
            raise WebSocketError("server refused the WebSocket upgrade (%s)" % lines[0][:80])
        headers = {}
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            if not sep:
                raise WebSocketError("malformed handshake header")
            headers[name.strip().lower()] = value.strip()
        if headers.get("upgrade", "").lower() != "websocket":
            raise WebSocketError("missing Upgrade: websocket")
        if "upgrade" not in headers.get("connection", "").lower():
            raise WebSocketError("missing Connection: upgrade")
        if headers.get("sec-websocket-accept") != _accept_value(key):
            raise WebSocketError("bad Sec-WebSocket-Accept")
        if headers.get("sec-websocket-protocol") != self._subprotocol:
            raise WebSocketError("server did not accept the subprotocol")
        if headers.get("sec-websocket-extensions"):
            raise WebSocketError("unexpected WebSocket extension")

    # -- low level IO ---------------------------------------------------

    def _read_exact(self, n: int) -> bytes:
        assert self._sock is not None
        while len(self._rbuf) < n:
            chunk = self._sock.recv(max(4096, n - len(self._rbuf)))
            if not chunk:
                raise ConnectionClosed("connection closed by peer")
            self._rbuf += chunk
        data = bytes(self._rbuf[:n])
        del self._rbuf[:n]
        return data

    def _discard(self, n: int, on_bytes: Optional[Callable[[int], None]]) -> None:
        """Read and throw away ``n`` payload bytes without storing them."""
        assert self._sock is not None
        if self._rbuf:
            take = min(n, len(self._rbuf))
            del self._rbuf[:take]
            n -= take
            if on_bytes is not None and take:
                on_bytes(take)
        view = memoryview(self._scratch)
        while n > 0:
            got = self._sock.recv_into(view, min(n, len(self._scratch)))
            if got == 0:
                raise ConnectionClosed("connection closed by peer")
            n -= got
            if on_bytes is not None:
                on_bytes(got)

    def _send_frame(self, opcode: int, payload: bytes, *, premasked: bool = False) -> None:
        """Send one final, masked frame.

        With ``premasked=True`` the payload is sent as-is with a fresh random
        mask key in the header. The server will unmask it to *different*
        bytes, which is fine for upload filler whose content is irrelevant,
        and avoids an expensive per-byte XOR in Python. The masking key is
        still fresh and unpredictable for every frame, as RFC 6455 requires.
        """
        if self._sock is None or self._closed:
            raise ConnectionClosed("connection is closed")
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)
        mask = secrets.token_bytes(4)
        header += mask
        if premasked:
            body = payload
        else:
            body = _apply_mask(payload, mask)
        self._sock.sendall(bytes(header))
        if body:
            self._sock.sendall(body)

    # -- public API -----------------------------------------------------

    def send_binary_filler(self, payload: bytes) -> None:
        self._send_frame(OP_BINARY, payload, premasked=True)

    def recv(self, on_binary_bytes: Optional[Callable[[int], None]] = None) -> Tuple[int, bytes]:
        """Receive the next data message.

        Returns ``(OP_TEXT, data)`` for text messages and ``(OP_BINARY, b"")``
        for binary messages (whose payload size is reported incrementally
        through ``on_binary_bytes`` as it streams in). Raises ``ConnectionClosed`` when
        the server closes the connection.
        """
        msg_op: Optional[int] = None
        text = bytearray()
        total = 0
        while True:
            b0, b1 = self._read_exact(2)
            fin = bool(b0 & 0x80)
            if b0 & 0x70:
                raise WebSocketError("reserved bits set")
            opcode = b0 & 0x0F
            if b1 & 0x80:
                raise WebSocketError("server frames must not be masked")
            length = b1 & 0x7F
            if length == 126:
                (length,) = struct.unpack("!H", self._read_exact(2))
            elif length == 127:
                (length,) = struct.unpack("!Q", self._read_exact(8))
                if length >> 63:
                    raise WebSocketError("invalid frame length")

            if opcode >= 0x8:  # control frame
                if not fin or length > 125:
                    raise WebSocketError("invalid control frame")
                data = self._read_exact(length)
                if opcode == OP_PING:
                    self._send_frame(OP_PONG, data)
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode == OP_CLOSE:
                    self._handle_close(data)
                    raise ConnectionClosed("server closed the connection")
                raise WebSocketError("unknown control opcode")

            if opcode == OP_CONT:
                if msg_op is None:
                    raise WebSocketError("unexpected continuation frame")
            elif opcode in (OP_TEXT, OP_BINARY):
                if msg_op is not None:
                    raise WebSocketError("new message before previous one finished")
                msg_op = opcode
            else:
                raise WebSocketError("unknown data opcode")

            total += length
            if total > self._max_message:
                raise WebSocketError("message too large")
            if msg_op == OP_TEXT:
                if total > self._max_text:
                    raise WebSocketError("text message too large")
                text += self._read_exact(length)
            else:
                self._discard(length, on_binary_bytes)
            if fin:
                if msg_op == OP_TEXT:
                    return OP_TEXT, bytes(text)
                return OP_BINARY, b""

    def _handle_close(self, data: bytes) -> None:
        if not self._closed:
            try:
                self._send_frame(OP_CLOSE, data[:2])
            except (OSError, WebSocketError):
                pass
        self._closed = True

    def close(self) -> None:
        if self._sock is None:
            return
        if not self._closed:
            try:
                self._send_frame(OP_CLOSE, struct.pack("!H", 1000))
            except (OSError, WebSocketError):
                pass
            self._closed = True
        self.abort()

    def abort(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._closed = True

    def settimeout(self, seconds: float) -> None:
        if self._sock is not None:
            self._sock.settimeout(seconds)

    def __enter__(self) -> "WebSocket":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _apply_mask(payload: bytes, mask: bytes) -> bytes:
    if not payload:
        return b""
    n = len(payload)
    reps = (n + 3) // 4
    key = int.from_bytes((mask * reps)[:n], "big")
    return (int.from_bytes(payload, "big") ^ key).to_bytes(n, "big")


def random_filler(size: int) -> bytes:
    """Incompressible upload filler (so middleboxes cannot compress it)."""
    return os.urandom(size)
