import os

import pytest

pytest.importorskip("PyQt5.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from PyQt5.QtWidgets import QApplication
    from deepin_speedtest.app import MainWindow
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    yield win
    win.close()
    app.processEvents()


def test_window_builds_and_handles_events(window):
    assert window.server_combo.count() == 1  # only the automatic M-Lab entry
    window.current_server = {"name": "Test", "host": "t.example.org", "backend": "ndt7", "provider": "x"}
    for ev in ({"type": "stage", "phase": "download"},
               {"type": "progress", "phase": "download", "value": 123.4, "fraction": 0.3},
               {"type": "result", "timestamp": 1763136000, "host": "t.example.org", "ping_ms": 8.0,
                "jitter_ms": 0.5, "download_mbps": 400.0, "upload_mbps": 50.0,
                "download_latency_ms": 20.0, "upload_latency_ms": None}):
        window._handle_event(ev)
    assert window.card_down.value.text() == "400"
    assert window.table.rowCount() == 1


def test_gauge_scale():
    from deepin_speedtest.gauge import value_to_fraction
    assert value_to_fraction(0) == 0
    assert value_to_fraction(1000) == 1
    assert 0 < value_to_fraction(5) < value_to_fraction(100) < value_to_fraction(999) < 1
