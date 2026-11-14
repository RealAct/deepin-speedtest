import os
import sys

import pytest


from swiftlet.engine import librespeed, ndt7  # noqa: E402
from swiftlet.engine.wsclient import WebSocket, WebSocketError  # noqa: E402

from fakeservers import (LibreSpeedServer, Ndt7Handler, TLSServer, client_context,  # noqa: E402
                         make_cert, serve, server_context)


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    return make_cert(str(tmp_path_factory.mktemp("tls")))


def _ndt7(certs, behaviour="normal"):
    handler = type("H", (Ndt7Handler,), {"behaviour": behaviour, "duration": 1.0})
    srv = serve(TLSServer(handler, server_context(*certs)))
    port = srv.server_address[1]
    return srv, "wss://127.0.0.1:%d/ndt/v7/" % port


def test_ndt7_download_and_upload(certs, monkeypatch):
    monkeypatch.setattr(ndt7, "UPLOAD_DURATION", 1.0)
    srv, base = _ndt7(certs)
    events = []
    try:
        down = ndt7.download(base + "download", events.append, ssl_context=client_context(certs[0]))
        up = ndt7.upload(base + "upload", events.append, ssl_context=client_context(certs[0]))
    finally:
        srv.shutdown()
    assert down["download_mbps"] > 1
    assert down["download_latency_ms"] == 12.0
    assert up["upload_mbps"] > 1
    assert up["upload_latency_ms"] == 12.0
    assert any(e["phase"] == "download" for e in events)


def test_untrusted_certificate_is_rejected(certs):
    srv, base = _ndt7(certs)
    try:
        with pytest.raises(Exception) as info:
            ndt7.download(base + "download", lambda e: None)  # system CAs only
        assert "certificate" in str(info.value).lower()
    finally:
        srv.shutdown()


@pytest.mark.parametrize("behaviour", ["bad_accept", "no_proto", "masked", "huge"])
def test_protocol_violations_are_rejected(certs, behaviour):
    srv, base = _ndt7(certs, behaviour)
    try:
        with pytest.raises(WebSocketError):
            ndt7.download(base + "download", lambda e: None, ssl_context=client_context(certs[0]))
    finally:
        srv.shutdown()


def test_plain_ws_is_refused():
    with pytest.raises(WebSocketError):
        WebSocket("ws://example.org/ndt/v7/download", "x")


def test_librespeed(certs, monkeypatch):
    monkeypatch.setattr(librespeed, "DURATION", 1.0)
    srv = serve(LibreSpeedServer(server_context(*certs)))
    base = "https://127.0.0.1:%d/speed/" % srv.server_address[1]
    try:
        down = librespeed.download(base, lambda e: None, ssl_context=client_context(certs[0]))
        up = librespeed.upload(base, lambda e: None, ssl_context=client_context(certs[0]))
    finally:
        srv.shutdown()
    assert down["download_mbps"] > 1
    assert up["upload_mbps"] > 1
