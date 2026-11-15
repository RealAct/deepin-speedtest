"""Deepin Speedtest desktop UI (PyQt5).

The UI process never opens network connections. All measurements run in
the sandboxed engine process (``deepin_speedtest.engine``), and every message it
sends back is validated by ``deepin_speedtest.protocol.validate_event``.
"""

from __future__ import annotations

import datetime
import os
import sys
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QByteArray, QObject, QProcess, QProcessEnvironment, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPalette
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog,
                             QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QPushButton, QRadioButton, QStackedWidget, QTabWidget, QTableWidget,
                             QTableWidgetItem,
                             QVBoxLayout, QWidget)

from . import APP_ID, APP_NAME, __version__, hardening, links
from .gauge import PillButton, SpeedGauge
from .protocol import (MAX_LINE, engine_command, engine_environment, request_line, validate_event,
                       validate_server)
from .storage import History, Settings, export_csv
from .validate import ValidationError, clean_text, parse_server_address, validate_https_base

ENGINE_WATCHDOG_MS = 120_000
AUTO = "auto"

MLAB_NOTICE = (
    "<p><b>About the public M-Lab servers</b></p>"
    "<p>By default Deepin Speedtest measures against servers run by "
    "<a href='https://www.measurementlab.net/'>Measurement Lab (M-Lab)</a>, an open, "
    "non-profit research platform. Using them is free and needs no account.</p>"
    "<p><b>Privacy:</b> M-Lab publishes every test as open data for research, "
    "<b>including your public IP address</b>. See M-Lab's "
    "<a href='https://www.measurementlab.net/privacy/'>privacy policy</a>.</p>"
    "<p>Deepin Speedtest itself collects nothing: no telemetry, no accounts, no ads. "
    "If you prefer, choose <i>Cancel</i> and add your own self-hosted ndt7 or "
    "LibreSpeed server instead.</p>"
)


NETWORK_NAMES = {"mlab": "M-Lab", "librespeed": "LibreSpeed"}

ABOUT_HTML = (
    "<h3>%s %s</h3>"
    "<p>Created by Eli Linares for %s</p>"
    "<p>An open-source internet speed test for Deepin and other Debian-based desktops.</p>"
    "<p>Measures latency, jitter, download and upload using the open ndt7 protocol "
    "(M-Lab or self-hosted) or LibreSpeed servers (public or self-hosted).</p>"
    "<p><b>Privacy:</b> no telemetry, no accounts. History is stored only on this computer.</p>"
    "<p><b>Engine sandbox:</b> %s</p>"
    "<p>A community project. Not affiliated with Deepin Technology, Ookla® or Speedtest®.</p>"
)

CREDITS_HTML = (
    "<h3>Credits</h3>"
    "<p>Created by Eli Linares<br><br>%s</p>"
    "<p>Test servers: Measurement Lab (M-Lab) and the LibreSpeed project and its "
    "volunteer server operators.</p>"
)


# -- engine process ----------------------------------------------------------

class EngineRun(QObject):
    """One run of the sandboxed engine process."""

    # Not named "event": that would shadow QObject.event() and crash Qt.
    message = pyqtSignal(dict)
    done = pyqtSignal()

    def __init__(self, op: str, server: Optional[Dict[str, Any]] = None, parent=None, *,
                 network: str = "mlab", high_speed: bool = False) -> None:
        super().__init__(parent)
        self._buf = QByteArray()
        self._done = False
        self._proc = QProcess(self)
        env = QProcessEnvironment()
        for k, v in engine_environment().items():
            env.insert(k, v)
        self._proc.setProcessEnvironment(env)
        self._proc.setWorkingDirectory("/")
        self._proc.setProcessChannelMode(QProcess.SeparateChannels)
        self._proc.setStandardErrorFile(QProcess.nullDevice())
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._timeout)
        self._request = request_line(op, server, network=network, high_speed=high_speed)
        cmd = engine_command()
        self._proc.start(cmd[0], cmd[1:])
        self._proc.write(self._request)
        self._proc.closeWriteChannel()
        self._watchdog.start(ENGINE_WATCHDOG_MS)

    def _read(self) -> None:
        self._buf += self._proc.readAllStandardOutput()
        while True:
            idx = self._buf.indexOf(b"\n")
            if idx < 0:
                if self._buf.size() > MAX_LINE:
                    self._fail("Engine sent an oversized message.")
                break
            line = bytes(self._buf.left(idx))
            self._buf.remove(0, idx + 1)
            try:
                ev = validate_event(line)
            except ValidationError as exc:
                self._fail("Engine protocol error: %s" % exc)
                return
            self.message.emit(ev)
            if ev["type"] == "error":
                self._done = True

    def _fail(self, message: str) -> None:
        if not self._done:
            self._done = True
            self.message.emit({"type": "error", "message": message})
        self.cancel()

    def _timeout(self) -> None:
        self._fail("The test took too long and was stopped.")

    def _on_error(self, err) -> None:
        if err == QProcess.FailedToStart:
            self._fail("Could not start the measurement engine.")

    def _on_finished(self, code: int, _status) -> None:
        self._watchdog.stop()
        self._read()
        if code != 0 and not self._done:
            self._done = True
            self.message.emit({"type": "error", "message": "The measurement engine stopped unexpectedly."})
        self.done.emit()

    def mark_done(self) -> None:
        self._done = True

    def cancel(self) -> None:
        self._done = True
        if self._proc.state() != QProcess.NotRunning:
            self._proc.kill()


# -- dialogs ----------------------------------------------------------------

class AddServerDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a self-hosted server")
        self.result_server: Optional[Dict[str, Any]] = None
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("ndt7 server (m-lab/ndt-server)", "ndt7")
        self.kind.addItem("LibreSpeed server", "librespeed")
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.name.setPlaceholderText("Home lab")
        self.address = QLineEdit()
        self.address.setMaxLength(300)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hint")
        form.addRow("Type", self.kind)
        form.addRow("Name", self.name)
        form.addRow("Address", self.address)
        form.addRow("", self.hint)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self._update_hint)
        self._update_hint()

    def _update_hint(self) -> None:
        if self.kind.currentData() == "ndt7":
            self.address.setPlaceholderText("speed.example.org or speed.example.org:4443")
            self.hint.setText("Host name (and optional port) of an ndt7 server with a valid TLS "
                              "certificate. Plain ws:// is not supported.")
        else:
            self.address.setPlaceholderText("https://speed.example.org/")
            self.hint.setText("Base https:// URL of a LibreSpeed install (the folder that contains "
                              "backend/garbage.php). Plain http:// is not supported.")

    def _accept(self) -> None:
        try:
            name = clean_text(self.name.text(), 60)
            if self.kind.currentData() == "ndt7":
                host, port = parse_server_address(self.address.text())
                netloc = ("[%s]" % host if ":" in host else host) + ("" if port == 443 else ":%d" % port)
                raw = {"backend": "ndt7", "custom": True, "id": "custom:ndt7:" + netloc,
                       "name": name or host, "host": host, "provider": "Self-hosted",
                       "download_url": "wss://%s/ndt/v7/download" % netloc,
                       "upload_url": "wss://%s/ndt/v7/upload" % netloc}
            else:
                base = validate_https_base(self.address.text())
                from urllib.parse import urlsplit
                host = urlsplit(base).hostname or ""
                raw = {"backend": "librespeed", "id": "custom:librespeed:" + base,
                       "name": name or host, "host": host, "base_url": base}
            self.result_server = validate_server(raw)
        except ValidationError as exc:
            self.error.setText(str(exc).capitalize() + ".")
            return
        self.accept()


def _fit_height(dialog: QDialog) -> None:
    """Word-wrapped labels need the dialog height computed for its width."""
    layout = dialog.layout()
    dialog.setMinimumHeight(layout.totalHeightForWidth(dialog.width()))
    dialog.resize(dialog.width(), dialog.minimumHeight())


class OptionsDialog(QDialog):
    """Server network and speed range."""

    def __init__(self, network: str, max_speed: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.setFixedWidth(480)
        self.network = network
        self.max_speed = max_speed
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        lay.addWidget(self._heading("Public test servers"))
        self.radio_mlab = QRadioButton("M-Lab (Measurement Lab)")
        self.radio_librespeed = QRadioButton("LibreSpeed public servers")
        (self.radio_librespeed if network == "librespeed" else self.radio_mlab).setChecked(True)
        lay.addWidget(self.radio_mlab)
        lay.addWidget(self._hint(
            "Open research platform using the ndt7 protocol, one connection per direction. "
            "M-Lab publishes every test, including your IP address, as open data."))
        lay.addWidget(self.radio_librespeed)
        lay.addWidget(self._hint(
            "Volunteer-run open-source servers, several parallel connections. Results are not "
            "published, but the server operator sees your IP address. Best choice for "
            "multi-gigabit lines."))

        lay.addWidget(self._heading("Maximum speed"))
        self.speed = QComboBox()
        for label, value in (("Up to 1 Gbit/s", 1000), ("Up to 2.5 Gbit/s", 2500), ("Up to 5 Gbit/s", 5000)):
            self.speed.addItem(label, value)
        self.speed.setCurrentIndex(max(0, self.speed.findData(max_speed)))
        self.speed.setAccessibleName("Maximum speed")
        lay.addWidget(self.speed)
        lay.addWidget(self._hint(
            "Sets the range of the dial. Above 1 Gbit/s, LibreSpeed tests also use more parallel "
            "connections and larger transfers. Results depend on the server's own capacity: "
            "few public servers can deliver 5 Gbit/s."))

        lay.addWidget(self._hint(
            "Speedtest.net servers are not offered: Ookla does not license them for "
            "third-party apps. Your own ndt7 or LibreSpeed server can be added with “Add…”."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        _fit_height(self)

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel("<b>%s</b>" % text)
        return label

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("hint")
        return label

    def _accept(self) -> None:
        self.network = "librespeed" if self.radio_librespeed.isChecked() else "mlab"
        self.max_speed = int(self.speed.currentData())
        self.accept()


class AboutDialog(QDialog):
    """About and Credits. The two links open in the user's browser; only the
    fixed addresses in ``links.LINKS`` can be opened (see ``links.py``)."""

    def __init__(self, sandbox: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About %s" % APP_NAME)
        self.setFixedWidth(480)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._page(ABOUT_HTML % (
            APP_NAME, __version__, links.anchor("https://deepinenespañol.org"), sandbox)), "About")
        tabs.addTab(self._page(CREDITS_HTML % links.anchor("https://realact.net")), "Credits")
        lay.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)
        self.tabs = tabs
        _fit_height(self)

    def _page(self, html: str) -> QWidget:
        page = QWidget()
        inner = QVBoxLayout(page)
        label = QLabel(html)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        # Links are handled by _open_link, never by Qt itself.
        label.setOpenExternalLinks(False)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        label.linkActivated.connect(self._open_link)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        inner.addWidget(label)
        inner.addStretch(1)
        return page

    def _open_link(self, url: str) -> None:
        if not links.open_link(url):
            QMessageBox.information(
                self, APP_NAME,
                "The link could not be opened. Copy it into your browser instead:\n\n%s" % url)


# -- main window -------------------------------------------------------------

def _fmt(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "–"
    return ("%.0f" % value) if value >= 100 else ("%.*f" % (digits, value))


class MetricCard(QFrame):
    def __init__(self, title: str, unit: str) -> None:
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.title = QLabel(title.upper())
        self.title.setObjectName("cardTitle")
        self.value = QLabel("–")
        self.value.setObjectName("cardValue")
        self.unit = QLabel(unit)
        self.unit.setObjectName("cardUnit")
        self.extra = QLabel("")
        self.extra.setObjectName("cardUnit")
        for w in (self.title, self.value, self.unit, self.extra):
            lay.addWidget(w)
        self.setAccessibleName(title)

    def set(self, value: Optional[float], extra: str = "") -> None:
        self.value.setText(_fmt(value))
        self.extra.setText(extra)

    def set_active(self, on: bool) -> None:
        self.setProperty("active", on)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(520, 640)
        self.settings = Settings()
        self.history = History()
        self.public_servers: List[Dict[str, Any]] = []
        self.run: Optional[EngineRun] = None
        self.current_server: Optional[Dict[str, Any]] = None
        self.sandbox_info: Optional[Dict[str, Any]] = None
        self._pending_selection: Optional[str] = None

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        # header
        head = QHBoxLayout()
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        self.brand = brand
        head.addWidget(brand)
        head.addStretch(1)
        self.nav_group = QButtonGroup(self)
        for i, text in enumerate(("Speed test", "History")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setObjectName("nav")
            b.setFocusPolicy(Qt.TabFocus)  # no focus frame after a mouse click
            self.nav_group.addButton(b, i)
            head.addWidget(b)
        self.nav_group.button(0).setChecked(True)
        for text, slot in (("Options", self.show_options), ("About", self.show_about)):
            extra = QPushButton(text)
            extra.setObjectName("nav")
            extra.setFocusPolicy(Qt.TabFocus)
            extra.clicked.connect(slot)
            head.addWidget(extra)
        outer.addLayout(head)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_test_page())
        self.pages.addWidget(self._build_history_page())
        if hasattr(self.nav_group, "idClicked"):  # Qt >= 5.15
            self.nav_group.idClicked.connect(self._switch_page)
        else:
            self.nav_group.buttonClicked[int].connect(self._switch_page)
        outer.addWidget(self.pages, 1)
        self.setCentralWidget(root)

        self._apply_theme()
        self.brand.ensurePolished()   # never clip the title next to the tab buttons
        self.brand.setMinimumWidth(self.brand.fontMetrics().boundingRect(APP_NAME).width() + 12)
        self._populate_servers()
        self.refresh_history()
        self.start_btn.setFocus()  # keep initial keyboard focus off the tab buttons

    # -- layout --------------------------------------------------------

    def _build_test_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        row = QHBoxLayout()
        self.server_combo = QComboBox()
        self.server_combo.setAccessibleName("Test server")
        self.server_combo.setMinimumContentsLength(24)
        self.server_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.server_combo.activated.connect(self._server_chosen)
        refresh = QPushButton("Find servers")
        refresh.setToolTip("Look up nearby public M-Lab servers")
        refresh.clicked.connect(self.find_servers)
        add = QPushButton("Add…")
        add.setToolTip("Add your own self-hosted ndt7 or LibreSpeed server")
        add.clicked.connect(self.add_server)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_server)
        row.addWidget(self.server_combo, 1)
        row.addWidget(refresh)
        row.addWidget(add)
        row.addWidget(self.remove_btn)
        lay.addLayout(row)

        self.gauge = SpeedGauge()
        lay.addWidget(self.gauge, 1)

        self.start_btn = PillButton("Start test")
        self.start_btn.clicked.connect(self.toggle_test)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.start_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.card_ping = MetricCard("Ping", "ms")
        self.card_jitter = MetricCard("Jitter", "ms")
        self.card_down = MetricCard("Download", "Mbit/s")
        self.card_up = MetricCard("Upload", "Mbit/s")
        grid.addWidget(self.card_ping, 0, 0)
        grid.addWidget(self.card_jitter, 0, 1)
        grid.addWidget(self.card_down, 0, 2)
        grid.addWidget(self.card_up, 0, 3)
        lay.addLayout(grid)

        self.status = QLabel("Choose a server and press Start.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)
        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Date", "Server", "Ping", "Jitter", "Down", "Up"])
        for col, tip in ((2, "Idle latency, ms"), (3, "Jitter, ms"), (4, "Download, Mbit/s"),
                         (5, "Upload, Mbit/s")):
            self.table.horizontalHeaderItem(col).setToolTip(tip)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        lay.addWidget(self.table, 1)
        self.history_summary = QLabel("")
        self.history_summary.setObjectName("status")
        self.history_summary.setWordWrap(True)
        lay.addWidget(self.history_summary)
        row = QHBoxLayout()
        row.addStretch(1)
        for text, slot in (("Export CSV…", self.export_history), ("Delete", self.delete_selected),
                           ("Clear all", self.clear_history)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        return page

    def _switch_page(self, idx: int) -> None:
        self.pages.setCurrentIndex(idx)
        if idx == 1:
            self.refresh_history()

    def _apply_theme(self) -> None:
        dark = self.palette().color(QPalette.Window).lightness() < 128
        accent = QColor("#2dd4bf" if dark else "#0d9488")
        accent2 = QColor("#fbbf24" if dark else "#d97706")
        self.gauge.set_colors(accent, accent2)
        self.gauge.set_max_speed(self.settings["max_speed"])
        self.start_btn.set_colors(accent, accent.darker(112) if dark else accent.lighter(112),
                                  QColor("#042f2e" if dark else "#ffffff"))
        card = "rgba(255,255,255,0.06)" if dark else "rgba(0,0,0,0.04)"
        border = "rgba(255,255,255,0.10)" if dark else "rgba(0,0,0,0.08)"
        self.setStyleSheet("""
            QLabel#brand { font-size: 15pt; font-weight: 700; }
            QPushButton#nav { border: none; outline: none; padding: 6px 8px; border-radius: 8px;
                              background: transparent; }
            QPushButton#nav:focus { outline: none; border: none; }
            QPushButton#nav:checked { background: %(card)s; font-weight: 600; }
            QFrame#card { background: %(card)s; border: 1px solid %(border)s; border-radius: 12px; }
            QFrame#card[active="true"] { border: 1px solid %(accent)s; }
            QLabel#cardTitle { font-size: 8pt; font-weight: 600; letter-spacing: 1px; opacity: 0.7; }
            QLabel#cardValue { font-size: 18pt; font-weight: 600; }
            QLabel#cardUnit, QLabel#hint { font-size: 8pt; }
            QLabel#status { font-size: 9pt; }
            QLabel#error { color: #dc2626; }
        """ % {"card": card, "border": border, "accent": accent.name(),
             "accent2": accent2.darker(110).name()})

    # -- servers -------------------------------------------------------

    def _all_servers(self) -> List[Dict[str, Any]]:
        return list(self.public_servers) + list(self.settings["custom_servers"])

    def _populate_servers(self) -> None:
        self.server_combo.clear()
        network = NETWORK_NAMES[self.settings["network"]]
        self.server_combo.addItem("Nearest public server (%s, automatic)" % network, AUTO)
        for s in self.public_servers:
            self.server_combo.addItem("%s · %s" % (network, s["name"]), s["id"])
        for s in self.settings["custom_servers"]:
            kind = "ndt7" if s["backend"] == "ndt7" else "LibreSpeed"
            self.server_combo.addItem("%s · %s (self-hosted %s)" % (s["name"], s["host"], kind), s["id"])
        wanted = self._pending_selection or self.settings["selected_server"]
        idx = self.server_combo.findData(wanted)
        self.server_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._update_remove()

    def _update_remove(self) -> None:
        sid = self.server_combo.currentData()
        self.remove_btn.setEnabled(isinstance(sid, str) and sid.startswith("custom:"))

    def _server_chosen(self, _idx: int) -> None:
        self.settings["selected_server"] = self.server_combo.currentData()
        self._save_settings()
        self._update_remove()

    def _save_settings(self) -> None:
        try:
            self.settings.save()
        except OSError as exc:
            self.status.setText("Could not save settings: %s" % exc.strerror)

    def _ensure_consent(self) -> bool:
        if self.settings["network"] != "mlab" or self.settings["mlab_consent"]:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Public test servers")
        box.setTextFormat(Qt.RichText)
        box.setText(MLAB_NOTICE)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText("Use M-Lab servers")
        if box.exec_() != QMessageBox.Ok:
            return False
        self.settings["mlab_consent"] = True
        self._save_settings()
        return True

    def find_servers(self) -> None:
        if self.run is not None or not self._ensure_consent():
            return
        self.status.setText("Looking up nearby %s servers…" % NETWORK_NAMES[self.settings["network"]])
        self._start_engine("locate", None, on_servers=self._servers_found)

    def _servers_found(self, servers: List[Dict[str, Any]]) -> None:
        self.public_servers = servers
        self._pending_selection = self.server_combo.currentData()
        self._populate_servers()
        self._pending_selection = None
        self.status.setText("Found %d nearby servers." % len(servers))
        self.server_combo.showPopup()

    def add_server(self) -> None:
        dlg = AddServerDialog(self)
        if dlg.exec_() != QDialog.Accepted or dlg.result_server is None:
            return
        server = dlg.result_server
        custom = [s for s in self.settings["custom_servers"] if s["id"] != server["id"]]
        custom.append(server)
        self.settings["custom_servers"] = custom[-32:]
        self.settings["selected_server"] = server["id"]
        self._save_settings()
        self._populate_servers()

    def remove_server(self) -> None:
        sid = self.server_combo.currentData()
        self.settings["custom_servers"] = [s for s in self.settings["custom_servers"] if s["id"] != sid]
        self.settings["selected_server"] = AUTO
        self._save_settings()
        self._populate_servers()

    # -- running a test ------------------------------------------------

    def toggle_test(self) -> None:
        if self.run is not None:
            self.run.cancel()
            self.status.setText("Test cancelled.")
            return
        sid = self.server_combo.currentData()
        custom = next((s for s in self.settings["custom_servers"] if s["id"] == sid), None)
        if custom is not None:
            self._run_test(custom)
            return
        if not self._ensure_consent():
            return
        # M-Lab access tokens are short-lived, so always locate right before testing.
        self.status.setText("Finding the best server…")
        self._set_running(True)

        def picked(servers: List[Dict[str, Any]]) -> None:
            self.public_servers = servers
            chosen = next((s for s in servers if s["id"] == sid), servers[0])
            self._populate_servers()
            QTimer.singleShot(0, lambda: self._run_test(chosen))

        self._start_engine("locate", None, on_servers=picked)

    def _run_test(self, server: Dict[str, Any]) -> None:
        self.current_server = server
        for c in (self.card_ping, self.card_jitter, self.card_down, self.card_up):
            c.set(None)
            c.set_active(False)
        self.gauge.reset()
        self.status.setText("Testing with %s (%s)…" % (server["name"], server["host"]))
        self._start_engine("run", server)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setText("Stop" if running else "Start test")
        self.server_combo.setEnabled(not running)

    def _start_engine(self, op: str, server: Optional[Dict[str, Any]], on_servers=None) -> None:
        self._set_running(True)
        run = EngineRun(op, server, self, network=self.settings["network"],
                        high_speed=self.settings["max_speed"] > 1000)
        self.run = run

        def on_event(ev: Dict[str, Any]) -> None:
            if self.run is not run:
                return
            kind = ev["type"]
            if kind == "servers" and on_servers is not None:
                run.mark_done()
                on_servers(ev["servers"])
            else:
                self._handle_event(ev)

        def on_finished() -> None:
            if self.run is run:
                self.run = None
                self._set_running(False)
            run.deleteLater()

        run.message.connect(on_event)
        run.done.connect(on_finished)

    def _handle_event(self, ev: Dict[str, Any]) -> None:
        kind = ev["type"]
        if kind == "sandbox":
            self.sandbox_info = ev
        elif kind == "stage":
            phase = ev["phase"]
            caption = {"ping": "Measuring latency", "download": "Download", "upload": "Upload"}[phase]
            self.gauge.set_caption(caption)
            self.gauge.reset()
            cards = {"ping": self.card_ping, "download": self.card_down, "upload": self.card_up}
            for name, card in cards.items():
                card.set_active(name == phase)
        elif kind == "progress":
            if ev["phase"] == "ping":
                self.gauge.set_value(ev["value"], "ms")
            else:
                self.gauge.set_value(ev["value"], "Mbit/s")
                card = self.card_down if ev["phase"] == "download" else self.card_up
                card.set(ev["value"])
        elif kind == "latency":
            self.card_ping.set(ev["ping_ms"])
            self.card_jitter.set(ev["jitter_ms"])
        elif kind == "measured":
            card = self.card_down if ev["phase"] == "download" else self.card_up
            card.set(ev["value"])
        elif kind == "result":
            self._finish(ev)
        elif kind == "error":
            self.gauge.set_caption("Error")
            self.gauge.reset()
            self.status.setText(ev["message"])

    def _finish(self, res: Dict[str, Any]) -> None:
        server = self.current_server or {}
        for c in (self.card_ping, self.card_jitter, self.card_down, self.card_up):
            c.set_active(False)
        self.card_ping.set(res["ping_ms"])
        self.card_jitter.set(res["jitter_ms"])
        self.card_down.set(res["download_mbps"], "loaded latency %s ms" % _fmt(res["download_latency_ms"])
                           if res["download_latency_ms"] is not None else "")
        self.card_up.set(res["upload_mbps"], "loaded latency %s ms" % _fmt(res["upload_latency_ms"])
                         if res["upload_latency_ms"] is not None else "")
        self.gauge.set_caption("Done")
        self.gauge.set_value(res["download_mbps"])
        self.status.setText("Tested with %s (%s) · %s" % (
            server.get("name", res["host"]), server.get("provider", ""),
            datetime.datetime.fromtimestamp(res["timestamp"]).strftime("%Y-%m-%d %H:%M")))
        try:
            self.history.add(res, server.get("backend", "ndt7"), server.get("name", res["host"]))
        except Exception as exc:  # history is non-critical
            self.status.setText(self.status.text() + " (not saved: %s)" % exc.__class__.__name__)
        self.refresh_history()

    # -- history -------------------------------------------------------

    def refresh_history(self) -> None:
        rows = self.history.rows()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            date = datetime.datetime.fromtimestamp(row["ts"]).strftime("%Y-%m-%d %H:%M")
            values = [date, row["server_name"], _fmt(row["ping_ms"]), _fmt(row["jitter_ms"]),
                      _fmt(row["download_mbps"]), _fmt(row["upload_mbps"])]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setData(Qt.UserRole, row["id"])
                if c == 1:
                    item.setToolTip("%s · %s" % (row["host"], row["backend"]))
                if 2 <= c <= 5:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        if rows:
            avg_d = sum(r["download_mbps"] for r in rows) / len(rows)
            avg_u = sum(r["upload_mbps"] for r in rows) / len(rows)
            self.history_summary.setText("%d tests · average %s↓ / %s↑ Mbit/s" % (
                len(rows), _fmt(avg_d), _fmt(avg_u)))
        else:
            self.history_summary.setText("No tests yet. Results are stored only on this computer.")

    def export_history(self) -> None:
        default = os.path.join(os.path.expanduser("~"), "deepin-speedtest-history.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export history", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            export_csv(path, list(reversed(self.history.rows())))
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, "Could not export: %s" % (exc.strerror or exc))

    def delete_selected(self) -> None:
        ids = {self.table.item(i.row(), 0).data(Qt.UserRole) for i in self.table.selectedIndexes()}
        for row_id in ids:
            self.history.delete(int(row_id))
        self.refresh_history()

    def clear_history(self) -> None:
        if QMessageBox.question(self, APP_NAME, "Delete all saved results?") == QMessageBox.Yes:
            self.history.clear()
            self.refresh_history()

    # -- about ---------------------------------------------------------

    def _sandbox_text(self) -> str:
        if self.sandbox_info is None:
            return "Run a test to see the engine sandbox status."
        abi = self.sandbox_info["landlock_abi"]
        if abi:
            return "Landlock ABI %d active (files, exec%s restricted)" % (
                abi, ", TCP ports" if abi >= 4 else "")
        return "Landlock unavailable on this kernel; resource limits and no_new_privs active"

    def show_about(self) -> None:
        AboutDialog(self._sandbox_text(), self).exec_()

    def show_options(self) -> None:
        if self.run is not None:
            self.status.setText("Stop the running test before changing options.")
            return
        dlg = OptionsDialog(self.settings["network"], self.settings["max_speed"], self)
        if dlg.exec_() != QDialog.Accepted:
            return
        if dlg.network != self.settings["network"]:
            self.settings["network"] = dlg.network
            self.public_servers = []          # the list belongs to the other network
            if not str(self.settings["selected_server"]).startswith("custom:"):
                self.settings["selected_server"] = AUTO
        self.settings["max_speed"] = dlg.max_speed
        self._save_settings()
        self.gauge.set_max_speed(dlg.max_speed)
        self._populate_servers()
        self.status.setText("Options saved.")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.run is not None:
            self.run.cancel()
        self.history.close()
        super().closeEvent(event)


def main(argv: Optional[List[str]] = None) -> int:
    hardening.refuse_root()
    hardening.harden_process()
    argv = list(sys.argv if argv is None else argv)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon.fromTheme(APP_ID))
    font = app.font()
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    win = MainWindow()

    def on_exception(kind, value, tb) -> None:
        # PyQt aborts the whole process on an unhandled exception in a slot
        # unless a hook is installed. Report it and keep the window alive.
        import traceback
        traceback.print_exception(kind, value, tb)
        try:
            win.status.setText("Internal error: %s" % clean_text(repr(value), 200))
        except Exception:  # noqa: BLE001 - never raise from the hook
            pass

    sys.excepthook = on_exception
    win.resize(600, 760)
    win.show()
    return app.exec_()
