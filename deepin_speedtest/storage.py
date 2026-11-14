"""Local, private storage for settings and result history.

Nothing ever leaves the machine. Files live in the XDG directories of the
current user, are created with 0700/0600 permissions, are refused if they
are symlinks or owned by someone else, and are always read through a
validator.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import stat
import tempfile
from typing import Any, Dict, List, Optional

from .validate import ValidationError, clean_text, finite_number, optional_number

APP_DIR = "deepin-speedtest"
MAX_HISTORY = 5000
MAX_SETTINGS_BYTES = 256 * 1024
MAX_CUSTOM_SERVERS = 32


def _xdg(var: str, fallback: str) -> str:
    value = os.environ.get(var, "")
    if not value or not os.path.isabs(value):
        value = os.path.join(os.path.expanduser("~"), fallback)
    return value


def _private_dir(base: str) -> str:
    os.makedirs(base, mode=0o700, exist_ok=True)
    path = os.path.join(base, APP_DIR)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise PermissionError("%s is not a directory owned by you" % path)
    if st.st_mode & 0o077:
        os.chmod(path, 0o700)
    return path


def data_dir() -> str:
    return _private_dir(_xdg("XDG_DATA_HOME", ".local/share"))


def config_dir() -> str:
    return _private_dir(_xdg("XDG_CONFIG_HOME", ".config"))


def _check_file(path: str) -> None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise PermissionError("%s is not a regular file owned by you" % path)
    if st.st_mode & 0o077:
        os.chmod(path, 0o600)


# -- settings ---------------------------------------------------------------

DEFAULT_SETTINGS: Dict[str, Any] = {
    "mlab_consent": False,
    "selected_server": "auto",
    "custom_servers": [],
}


class Settings:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.path.join(config_dir(), "settings.json")
        self.values: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        from .protocol import validate_server

        try:
            _check_file(self.path)
            with open(self.path, "rb") as fh:
                raw = fh.read(MAX_SETTINGS_BYTES + 1)
        except FileNotFoundError:
            return
        if len(raw) > MAX_SETTINGS_BYTES:
            return
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(doc, dict):
            return
        self.values["mlab_consent"] = doc.get("mlab_consent") is True
        sel = doc.get("selected_server")
        if isinstance(sel, str):
            self.values["selected_server"] = clean_text(sel, 300) or "auto"
        servers = []
        stored = doc.get("custom_servers")
        for item in stored[:MAX_CUSTOM_SERVERS] if isinstance(stored, list) else []:
            try:
                servers.append(validate_server(item))
            except ValidationError:
                continue
        self.values["custom_servers"] = servers

    def save(self) -> None:
        directory = os.path.dirname(self.path)
        fd, tmp = tempfile.mkstemp(prefix=".settings-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.values, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.values[key] = value


# -- history ----------------------------------------------------------------

COLUMNS = ("ts", "backend", "server_name", "host", "ping_ms", "jitter_ms", "download_mbps",
           "upload_mbps", "download_latency_ms", "upload_latency_ms")


class History:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.path.join(data_dir(), "history.sqlite3")
        _check_file(self.path)
        self.db = sqlite3.connect(self.path)
        os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA secure_delete = ON")  # deleted rows are overwritten
        self.db.execute("PRAGMA trusted_schema = OFF")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS results ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts INTEGER NOT NULL, backend TEXT NOT NULL, server_name TEXT NOT NULL,"
            " host TEXT NOT NULL, ping_ms REAL, jitter_ms REAL, download_mbps REAL,"
            " upload_mbps REAL, download_latency_ms REAL, upload_latency_ms REAL)")
        self.db.commit()

    def add(self, result: Dict[str, Any], backend: str, server_name: str) -> None:
        row = (
            int(finite_number(result["timestamp"], 0, 1e11)),
            clean_text(backend, 20),
            clean_text(server_name, 120),
            clean_text(result["host"], 253),
            finite_number(result["ping_ms"]),
            finite_number(result["jitter_ms"]),
            finite_number(result["download_mbps"]),
            finite_number(result["upload_mbps"]),
            optional_number(result.get("download_latency_ms")),
            optional_number(result.get("upload_latency_ms")),
        )
        with self.db:
            self.db.execute("INSERT INTO results (%s) VALUES (%s)" % (
                ",".join(COLUMNS), ",".join("?" * len(COLUMNS))), row)
            self.db.execute("DELETE FROM results WHERE id NOT IN "
                            "(SELECT id FROM results ORDER BY id DESC LIMIT ?)", (MAX_HISTORY,))

    def rows(self, limit: int = MAX_HISTORY) -> List[Dict[str, Any]]:
        cur = self.db.execute("SELECT id, %s FROM results ORDER BY ts DESC, id DESC LIMIT ?" %
                              ",".join(COLUMNS), (int(limit),))
        return [dict(zip(("id",) + COLUMNS, r)) for r in cur.fetchall()]

    def delete(self, row_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM results WHERE id = ?", (int(row_id),))

    def clear(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM results")
        self.db.execute("VACUUM")

    def close(self) -> None:
        self.db.close()


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection (=, +, -, @, tab, CR)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return "" if value is None else value


def export_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow([_csv_safe(row.get(c)) for c in COLUMNS])
