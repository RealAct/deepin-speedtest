"""Open the app's own web links in the user's browser.

Only the fixed addresses in ``LINKS`` can be opened: nothing that comes from
a test server, the settings file or the network ever reaches this module.

The UI process runs with ``no_new_privs`` and a 077 umask, which a browser
started as its child would inherit. So the link is handed to the desktop
portal over D-Bus first (the browser is then started by the session, not by
this app). ``xdg-open`` is only the fallback for desktops without a portal.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

# Shown text -> address that is opened. Host names are in their ASCII (IDNA)
# form so that what is opened never depends on how a browser reads the text.
LINKS = {
    "https://deepinenespañol.org": "https://xn--deepinenespaol-1nb.org",
    "https://realact.net": "https://realact.net",
}

XDG_OPEN = "/usr/bin/xdg-open"
PORTAL_TIMEOUT_MS = 3000


def anchor(text: str) -> str:
    """HTML for one of the allow-listed links."""
    return '<a href="%s">%s</a>' % (LINKS[text], text)


def allowed(url: str) -> Optional[str]:
    """Return ``url`` if it is one of the app's own links, else None."""
    return url if url in LINKS.values() else None


def _open_with_portal(url: str) -> bool:
    try:
        from PyQt5.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
    except ImportError:
        return False
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    portal = QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                            "org.freedesktop.portal.OpenURI", bus)
    if not portal.isValid():
        return False
    portal.setTimeout(PORTAL_TIMEOUT_MS)
    reply = portal.call("OpenURI", "", url, {})
    return reply.type() == QDBusMessage.ReplyMessage


def _open_with_xdg_open(url: str) -> bool:
    if not os.access(XDG_OPEN, os.X_OK):
        return False
    try:
        subprocess.Popen([XDG_OPEN, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, cwd="/", close_fds=True,
                         start_new_session=True, preexec_fn=lambda: os.umask(0o022))
    except OSError:
        return False
    return True


def open_link(url: str) -> bool:
    """Open one of the app's own links. Returns False if it could not be opened."""
    target = allowed(url)
    if target is None:
        return False
    return _open_with_portal(target) or _open_with_xdg_open(target)
