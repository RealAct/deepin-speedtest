"""Local TLS test servers that speak ndt7 and LibreSpeed (test-only code)."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import socket
import socketserver
import ssl
import struct
import subprocess
import tempfile
import threading
import time

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def make_cert(tmpdir: str):
    key = os.path.join(tmpdir, "key.pem")
    crt = os.path.join(tmpdir, "cert.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-nodes", "-keyout", key, "-out", crt, "-days", "2", "-subj", "/CN=127.0.0.1",
         "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return crt, key


def server_context(crt: str, key: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    return ctx


def client_context(crt: str) -> ssl.SSLContext:
    from deepin_speedtest.engine.wsclient import make_tls_context
    ctx = make_tls_context()
    ctx.load_verify_locations(crt)
    return ctx


def _frame(opcode: int, payload: bytes, fin: bool = True, masked: bool = False) -> bytes:
    head = bytearray([(0x80 if fin else 0) | opcode])
    n = len(payload)
    mbit = 0x80 if masked else 0
    if n < 126:
        head.append(mbit | n)
    elif n < 65536:
        head.append(mbit | 126)
        head += struct.pack("!H", n)
    else:
        head.append(mbit | 127)
        head += struct.pack("!Q", n)
    if masked:
        head += b"\0\0\0\0"
    return bytes(head) + payload


class Ndt7Handler(socketserver.BaseRequestHandler):
    duration = 1.0
    behaviour = "normal"  # or: bad_accept, masked, huge, no_proto

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                raise ConnectionError
            buf += chunk
        return buf

    def handle(self):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data += chunk
        head = data.split(b"\r\n\r\n", 1)[0].decode()
        lines = head.split("\r\n")
        path = lines[0].split(" ")[1]
        headers = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lines[1:]}
        accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + GUID).encode()).digest()).decode()
        if self.behaviour == "bad_accept":
            accept = "AAAA" + accept[4:]
        resp = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        resp += "Sec-WebSocket-Accept: %s\r\n" % accept
        if self.behaviour != "no_proto":
            resp += "Sec-WebSocket-Protocol: net.measurementlab.ndt.v7\r\n"
        self.request.sendall((resp + "\r\n").encode())
        if path.startswith("/ndt/v7/download"):
            self._download()
        else:
            self._upload()

    def _measurement(self, elapsed_us, received=None):
        doc = {"TCPInfo": {"RTT": 12000, "MinRTT": 9000, "ElapsedTime": elapsed_us}}
        if received is not None:
            doc["TCPInfo"]["BytesReceived"] = received
        return json.dumps(doc).encode()

    def _download(self):
        if self.behaviour == "masked":
            self.request.sendall(_frame(2, b"x" * 10, masked=True))
            time.sleep(0.2)
            return
        if self.behaviour == "huge":
            self.request.sendall(bytes([0x82, 127]) + struct.pack("!Q", 1 << 40))
            time.sleep(0.2)
            return
        payload = os.urandom(1 << 16)
        start = time.monotonic()
        last = 0.0
        self.request.sendall(_frame(9, b"ping"))  # client must answer pings
        while time.monotonic() - start < self.duration:
            # fragmented binary message: two frames
            self.request.sendall(_frame(2, payload[:30000], fin=False) + _frame(0, payload[30000:]))
            if time.monotonic() - last > 0.25:
                last = time.monotonic()
                self.request.sendall(_frame(1, self._measurement(int((last - start) * 1e6))))
        self.request.sendall(_frame(8, struct.pack("!H", 1000)))
        # Read until the client hangs up so that closing never resets the
        # connection while the client still has unread data.
        self.request.settimeout(3)
        try:
            while self.request.recv(65536):
                pass
        except OSError:
            pass

    def _upload(self):
        self.request.settimeout(5)
        start = time.monotonic()
        last = 0.0
        received = 0
        try:
            while True:
                b0, b1 = self._read_exact(2)
                n = b1 & 0x7F
                if n == 126:
                    (n,) = struct.unpack("!H", self._read_exact(2))
                elif n == 127:
                    (n,) = struct.unpack("!Q", self._read_exact(8))
                assert b1 & 0x80, "client frames must be masked"
                self._read_exact(4)
                left = n
                while left:
                    got = len(self.request.recv(min(left, 1 << 20)))
                    if not got:
                        return
                    left -= got
                received += n
                if b0 & 0x0F == 8:
                    self.request.sendall(_frame(8, b""))
                    return
                if time.monotonic() - last > 0.25:
                    last = time.monotonic()
                    self.request.sendall(_frame(1, self._measurement(int((last - start) * 1e6), received)))
        except (ConnectionError, OSError, ValueError):
            return


class TLSServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, handler, ctx):
        self.ctx = ctx
        super().__init__(("127.0.0.1", 0), handler)

    def get_request(self):
        sock, addr = self.socket.accept()
        return self.ctx.wrap_socket(sock, server_side=True), addr


class LibreSpeedHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    blob = os.urandom(1 << 20)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/speed/backend/garbage.php"):
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.blob) * 8))
            self.end_headers()
            try:
                for _ in range(8):
                    self.wfile.write(self.blob)
            except OSError:
                pass
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path.startswith("/speed/backend/empty.php"):
            left = int(self.headers.get("Content-Length", "0"))
            while left:
                got = len(self.rfile.read(min(left, 65536)))
                if not got:
                    break
                left -= got
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_error(404)


class LibreSpeedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def __init__(self, ctx):
        super().__init__(("127.0.0.1", 0), LibreSpeedHandler)
        self.socket = ctx.wrap_socket(self.socket, server_side=True)


def serve(server):
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def free_tmpdir():
    return tempfile.mkdtemp(prefix="deepin-speedtest-test-")


__all__ = ["make_cert", "server_context", "client_context", "Ndt7Handler", "TLSServer",
           "LibreSpeedServer", "serve", "free_tmpdir", "socket"]
