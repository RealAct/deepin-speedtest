import json

import pytest

from deepin_speedtest.engine.mlab import parse_locate
from deepin_speedtest.protocol import validate_event
from deepin_speedtest.validate import (ValidationError, clean_text, parse_server_address,
                               validate_hostname, validate_https_base, validate_ndt7_url)

TOKEN = "eyJhbGciOiJFZERTQSJ9.eyJhdWQiOlsibWxhYjEifX0.c2ln"


def locate_doc(machine="mlab1-ams03.mlab-oti.measurement-lab.org", host=None):
    host = host or "ndt-" + machine
    return json.dumps({"results": [{
        "machine": machine,
        "location": {"city": "Amsterdam", "country": "NL"},
        "urls": {
            "wss:///ndt/v7/download": "wss://%s/ndt/v7/download?access_token=%s" % (host, TOKEN),
            "wss:///ndt/v7/upload": "wss://%s/ndt/v7/upload?access_token=%s" % (host, TOKEN),
            "ws:///ndt/v7/download": "ws://%s/ndt/v7/download" % host,
        }}]}).encode()


def test_locate_parses_valid_response():
    (server,) = parse_locate(locate_doc())
    assert server["name"] == "Amsterdam, NL"
    assert server["download_url"].startswith("wss://ndt-mlab1-ams03.mlab-oti.measurement-lab.org/")


@pytest.mark.parametrize("host", ["evil.example.com", "measurement-lab.org.evil.com",
                                  "xmeasurement-lab.org"])
def test_locate_rejects_foreign_hosts(host):
    with pytest.raises(ValidationError):
        parse_locate(locate_doc(host=host))


@pytest.mark.parametrize("body", [b"", b"[]", b'{"results": 5}', b"\xff", b'{"results": [1, "x"]}'])
def test_locate_rejects_garbage(body):
    with pytest.raises(ValidationError):
        parse_locate(body)


@pytest.mark.parametrize("url", [
    "ws://ndt.measurement-lab.org/ndt/v7/download",
    "https://ndt.measurement-lab.org/ndt/v7/download",
    "wss://user:pw@ndt.measurement-lab.org/ndt/v7/download",
    "wss://ndt.measurement-lab.org/ndt/v7/upload",
    "wss://ndt.measurement-lab.org/ndt/v7/download?x=<script>",
    "wss://ndt.measurement-lab.org:99999/ndt/v7/download",
])
def test_ndt7_url_rejections(url):
    with pytest.raises(ValidationError):
        validate_ndt7_url(url, allow_any_host=False, expected_test="download")


@pytest.mark.parametrize("text,expected", [
    ("speed.example.org", ("speed.example.org", 443)),
    ("Speed.Example.org:4443", ("speed.example.org", 4443)),
    ("wss://speed.example.org", ("speed.example.org", 443)),
    ("192.0.2.7:8443", ("192.0.2.7", 8443)),
    ("[2001:db8::1]:443", ("2001:db8::1", 443)),
])
def test_server_address_ok(text, expected):
    assert parse_server_address(text) == expected


@pytest.mark.parametrize("text", ["http://speed.example.org", "speed.example.org/path", "a:b@host.org",
                                  "host.org:0", "host.org:70000", "-bad-.org", "localhost", "", "x" * 300,
                                  "speed.example.org?x=1", "999.1.1.1"])
def test_server_address_bad(text):
    with pytest.raises(ValidationError):
        parse_server_address(text)


def test_https_base():
    assert validate_https_base("https://speed.example.org/lib") == "https://speed.example.org/lib/"
    for bad in ("http://speed.example.org/", "https://speed.example.org/../x", "https://h.org/?a=1",
                "https://u@h.org/", "file:///etc/passwd", "https://h.org/a b"):
        with pytest.raises(ValidationError):
            validate_https_base(bad)


def test_clean_text_strips_controls_and_bidi():
    assert clean_text("ab\x00c‮d\nX") == "abcdX"
    assert len(clean_text("y" * 1000)) == 256


def test_hostname_idna():
    assert validate_hostname("bücher.example") == "xn--bcher-kva.example"


@pytest.mark.parametrize("line", [
    b'{"type":"progress","phase":"download","value":NaN,"fraction":0.5}',
    b'{"type":"progress","phase":"download","value":1e99,"fraction":0.5}',
    b'{"type":"progress","phase":"exfil","value":1,"fraction":0.5}',
    b'{"type":"result"}',
    b'{"type":"shell","cmd":"rm -rf ~"}',
    b'["not","an","object"]',
    b"x" * 70000,
])
def test_engine_events_rejected(line):
    with pytest.raises(ValidationError):
        validate_event(line)


def test_engine_event_rebuilt_without_extra_fields():
    ev = validate_event(b'{"type":"error","message":"bad\\u0007 thing","extra":"<b>x</b>"}')
    assert ev == {"type": "error", "message": "bad thing"}


SAMPLE_LIBRESPEED = json.dumps([
    {"id": 1, "name": "Amsterdam, Netherlands", "server": "//ams.speedtest.example.net/",
     "dlURL": "garbage.php", "ulURL": "empty.php", "pingURL": "empty.php", "getIpURL": "getIP.php",
     "sponsorName": "Example Hosting", "sponsorURL": "https://example.net"},
    {"id": 2, "name": "Frankfurt", "server": "https://fra.example.org/speed", "dlURL": "backend/garbage.php",
     "ulURL": "backend/empty.php"},
    {"id": 3, "name": "Plain HTTP", "server": "http://insecure.example.org/", "dlURL": "garbage.php",
     "ulURL": "empty.php"},
    {"id": 4, "name": "Traversal", "server": "https://ok.example.org/", "dlURL": "../../etc/passwd",
     "ulURL": "empty.php"},
    {"id": 5, "name": "Odd port", "server": "https://ok.example.org:8443/", "dlURL": "garbage.php",
     "ulURL": "empty.php"},
    {"id": 6, "name": "Query", "server": "https://ok.example.org/", "dlURL": "garbage.php?x=1",
     "ulURL": "empty.php"},
    "junk", {"server": 7},
]).encode()


def test_librespeed_public_list_parsing():
    from deepin_speedtest.engine.librespeed_public import parse_list
    from deepin_speedtest.protocol import validate_server

    servers = parse_list(SAMPLE_LIBRESPEED)
    assert [s["host"] for s in servers] == ["ams.speedtest.example.net", "fra.example.org"]
    assert servers[0]["base_url"] == "https://ams.speedtest.example.net/"
    assert servers[0]["dl_path"] == "garbage.php" and servers[0]["custom"] is False
    assert servers[1]["base_url"] == "https://fra.example.org/speed/"
    assert validate_server(servers[0])["provider"] == "LibreSpeed · Example Hosting"
    for bad in (b"{}", b"[]", b"nope", b'[{"server": "http://x.example.org/"}]'):
        with pytest.raises(ValidationError):
            parse_list(bad)


@pytest.mark.parametrize("path", ["../x", "/abs", "a//b", "a/./b", "x?y=1", "", "a b", "x" * 200, None])
def test_rel_path_rejections(path):
    from deepin_speedtest.validate import validate_rel_path
    with pytest.raises(ValidationError):
        validate_rel_path(path)
