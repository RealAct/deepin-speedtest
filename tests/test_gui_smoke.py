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


def _wait(app, condition, timeout=20.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_start_button_runs_a_full_test_through_the_engine_process(window, monkeypatch):
    """Regression test for v1.0.1: pressing Start crashed the app because a
    signal named ``event`` shadowed QObject.event()."""
    import sys
    from PyQt5.QtWidgets import QApplication
    import deepin_speedtest.app as appmod

    fake = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_engine.py")
    monkeypatch.setattr(appmod, "engine_command", lambda: [sys.executable, "-I", fake])
    window.settings["mlab_consent"] = True
    app = QApplication.instance()

    window.start_btn.click()
    assert _wait(app, lambda: window.table.rowCount() == 1 and window.run is None), window.status.text()
    assert window.card_down.value.text() == "250"
    assert window.card_up.value.text() == "40.0"
    assert window.card_ping.value.text() == "9.5"
    assert window.start_btn.text() == "Start test"
    assert window.sandbox_info["landlock_abi"] == 4
    assert "Amsterdam" in window.status.text()


def test_engine_failure_is_shown_not_fatal(window, monkeypatch):
    import sys
    from PyQt5.QtWidgets import QApplication
    import deepin_speedtest.app as appmod

    monkeypatch.setattr(appmod, "engine_command",
                        lambda: [sys.executable, "-I", "-c", "print('not json'); raise SystemExit(3)"])
    window.settings["mlab_consent"] = True
    app = QApplication.instance()
    window.start_btn.click()
    assert _wait(app, lambda: window.run is None and "protocol error" in window.status.text())
    assert window.start_btn.text() == "Start test"


def test_consent_dialog_and_nav_focus(window, monkeypatch):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec_", lambda self: QMessageBox.Cancel)
    assert window._ensure_consent() is False
    monkeypatch.setattr(QMessageBox, "exec_", lambda self: QMessageBox.Ok)
    assert window._ensure_consent() is True
    for button in window.nav_group.buttons():
        assert button.focusPolicy() == Qt.TabFocus


def test_dialogs_and_history_actions(window, monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QFileDialog, QMessageBox
    from deepin_speedtest.app import AddServerDialog

    shown = []
    monkeypatch.setattr(QMessageBox, "about", lambda *a: shown.append(a[2]))
    window.show_about()
    window.sandbox_info = {"landlock_abi": 0, "no_new_privs": True}
    window.show_about()
    assert len(shown) == 2 and "Landlock unavailable" in shown[1]

    for kind, address, ok in ((0, "speed.example.org:4443", True), (0, "http://x.example.org", False),
                              (1, "https://speed.example.org/ls", True), (1, "http://speed.example.org", False)):
        dlg = AddServerDialog(window)
        dlg.kind.setCurrentIndex(kind)
        dlg.address.setText(address)
        dlg._accept()
        assert (dlg.result_server is not None) == ok
        if ok:
            window.settings["custom_servers"] = window.settings["custom_servers"] + [dlg.result_server]
    window._populate_servers()
    assert window.server_combo.count() == 3
    window.server_combo.setCurrentIndex(2)
    window._server_chosen(2)
    assert window.remove_btn.isEnabled()
    window.remove_server()
    assert window.server_combo.count() == 2

    window.current_server = {"name": "T", "host": "t.example.org", "backend": "ndt7", "provider": "x"}
    window._handle_event({"type": "result", "timestamp": 1763136000, "host": "t.example.org", "ping_ms": 8.0,
                          "jitter_ms": 0.5, "download_mbps": 400.0, "upload_mbps": 50.0,
                          "download_latency_ms": None, "upload_latency_ms": None})
    out = tmp_path / "h.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    window.export_history()
    assert "t.example.org" in out.read_text()
    window.table.selectRow(0)
    window.delete_selected()
    assert window.table.rowCount() == 0
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.clear_history()
    window._switch_page(1)
    window.gauge.repaint()
