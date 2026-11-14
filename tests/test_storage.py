import csv
import json
import os
import stat

import pytest

from deepin_speedtest import storage

RESULT = {"timestamp": 1763136000, "host": "ndt.example.org", "ping_ms": 10.5, "jitter_ms": 1.2,
          "download_mbps": 300.0, "upload_mbps": 40.0, "download_latency_ms": 25.0,
          "upload_latency_ms": None}


@pytest.fixture(autouse=True)
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    old = os.umask(0o022)
    yield tmp_path
    os.umask(old)


def test_history_round_trip_and_permissions():
    h = storage.History()
    h.add(RESULT, "ndt7", "=HYPERLINK(\"http://evil\")")
    rows = h.rows()
    assert rows[0]["download_mbps"] == 300.0
    assert stat.S_IMODE(os.stat(h.path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(h.path)).st_mode) == 0o700
    h.delete(rows[0]["id"])
    assert h.rows() == []


def test_history_rejects_bad_numbers():
    h = storage.History()
    with pytest.raises(ValueError):
        h.add(dict(RESULT, download_mbps=float("nan")), "ndt7", "x")


def test_csv_export_neutralises_formulas(tmp_path):
    h = storage.History()
    h.add(RESULT, "ndt7", "=cmd|' /C calc'!A0")
    out = tmp_path / "out.csv"
    storage.export_csv(str(out), h.rows())
    rows = list(csv.reader(out.open()))
    assert rows[1][2].startswith("'=")


def test_csv_export_does_not_follow_symlinks(tmp_path):
    target = tmp_path / "victim"
    target.write_text("keep")
    link = tmp_path / "link.csv"
    link.symlink_to(target)
    with pytest.raises(OSError):
        storage.export_csv(str(link), [])
    assert target.read_text() == "keep"


def test_settings_ignore_malicious_content():
    s = storage.Settings()
    with open(s.path, "w") as fh:
        json.dump({"mlab_consent": "yes", "custom_servers": [
            {"backend": "ndt7", "custom": True, "host": "ok.example.org", "name": "ok",
             "download_url": "wss://ok.example.org/ndt/v7/download",
             "upload_url": "wss://ok.example.org/ndt/v7/upload"},
            {"backend": "ndt7", "custom": True, "host": "bad.example.org",
             "download_url": "ws://bad.example.org/ndt/v7/download",
             "upload_url": "ws://bad.example.org/ndt/v7/upload"},
            {"backend": "shell"}]}, fh)
    s.load()
    assert s["mlab_consent"] is False
    assert [x["host"] for x in s["custom_servers"]] == ["ok.example.org"]


def test_settings_save_is_private():
    s = storage.Settings()
    s["mlab_consent"] = True
    s.save()
    assert stat.S_IMODE(os.stat(s.path).st_mode) == 0o600
    assert storage.Settings()["mlab_consent"] is True


def test_refuses_symlinked_data_dir(xdg):
    (xdg / "data").mkdir()
    (xdg / "elsewhere").mkdir()
    (xdg / "data" / "deepin-speedtest").symlink_to(xdg / "elsewhere")
    with pytest.raises(PermissionError):
        storage.data_dir()
