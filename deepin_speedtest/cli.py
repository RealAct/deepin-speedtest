"""Command-line interface: ``deepin-speedtest --cli``.

Uses exactly the same sandboxed engine and validation as the desktop UI.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from . import APP_NAME, __version__, hardening
from .i18n import tr
from .protocol import run_engine, validate_server
from .storage import History, Settings
from .validate import ValidationError, parse_server_address, validate_https_base

NOTICE = """\
Deepin Speedtest uses the public servers of Measurement Lab (M-Lab) by default.
M-Lab publishes every test as open research data, INCLUDING YOUR PUBLIC IP
ADDRESS (https://www.measurementlab.net/privacy/). Deepin Speedtest itself collects
nothing. Use --ndt7-server or --librespeed to test against your own server.
"""


def _custom_server(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if args.ndt7_server:
        host, port = parse_server_address(args.ndt7_server)
        netloc = ("[%s]" % host if ":" in host else host) + ("" if port == 443 else ":%d" % port)
        return validate_server({"backend": "ndt7", "custom": True, "id": "cli", "name": host, "host": host,
                                "provider": "Self-hosted",
                                "download_url": "wss://%s/ndt/v7/download" % netloc,
                                "upload_url": "wss://%s/ndt/v7/upload" % netloc})
    if args.librespeed:
        base = validate_https_base(args.librespeed)
        host = urlsplit(base).hostname or ""
        return validate_server({"backend": "librespeed", "id": "cli", "name": host, "host": host,
                                "base_url": base})
    return None


def _consent(settings: Settings, assume_yes: bool) -> bool:
    if settings["mlab_consent"]:
        return True
    sys.stderr.write(tr(NOTICE))
    if not assume_yes:
        if not sys.stdin.isatty():
            sys.stderr.write(tr("Re-run with --accept-mlab-privacy to continue.\n"))
            return False
        answer = input(tr("Continue with M-Lab servers? [y/N] ")).strip().lower()
        if answer not in ("y", "yes", "s", "si", "sí"):
            return False
    settings["mlab_consent"] = True
    try:
        settings.save()
    except OSError:
        pass
    return True


def _phase(phase: str) -> str:
    return {"ping": tr("Ping"), "download": tr("Download"), "upload": tr("Upload")}.get(phase, phase)


def _collect(op: str, server: Optional[Dict[str, Any]], quiet: bool, network: str = "mlab",
             high_speed: bool = False) -> List[Dict[str, Any]]:
    events = []
    for ev in run_engine(op, server, network=network, high_speed=high_speed):
        events.append(ev)
        if quiet:
            continue
        if ev["type"] == "stage":
            sys.stderr.write("\n%-9s" % _phase(ev["phase"]))
        elif ev["type"] == "progress" and ev["phase"] != "ping":
            sys.stderr.write("\r%-9s %8.1f Mbit/s" % (_phase(ev["phase"]), ev["value"]))
        sys.stderr.flush()
    if not quiet:
        sys.stderr.write("\n")
    return events


def main(argv: Optional[List[str]] = None) -> int:
    hardening.refuse_root()
    hardening.harden_process()
    p = argparse.ArgumentParser(prog="deepin-speedtest --cli", description=tr("%s %s command-line speed test") % (
        APP_NAME, __version__))
    p.add_argument("--list-servers", action="store_true", help=tr("list nearby public servers"))
    p.add_argument("--network", choices=("mlab", "librespeed"),
                   help=tr("public server network (default: the one chosen in Options, else mlab)"))
    p.add_argument("--high-speed", action="store_true",
                   help=tr("tune for lines faster than 1 Gbit/s (more parallel streams with LibreSpeed)"))
    p.add_argument("--ndt7-server", metavar="HOST[:PORT]", help=tr("use a self-hosted ndt7 server"))
    p.add_argument("--librespeed", metavar="URL", help=tr("use a self-hosted LibreSpeed server (https://...)"))
    p.add_argument("--json", action="store_true", help=tr("print the result as JSON"))
    p.add_argument("--no-save", action="store_true", help=tr("do not add the result to the history"))
    p.add_argument("--accept-mlab-privacy", action="store_true", help=tr("accept the M-Lab data notice"))
    args = p.parse_args(argv)

    settings = Settings()
    try:
        server = _custom_server(args)
    except ValidationError as exc:
        p.error(tr(str(exc)))
        return 2
    network = args.network or settings["network"]
    high_speed = args.high_speed or settings["max_speed"] > 1000
    if server is None and network == "mlab" and not _consent(settings, args.accept_mlab_privacy):
        return 1

    if args.list_servers:
        events = _collect("locate", None, quiet=True, network=network)
        last = events[-1] if events else {"type": "error", "message": "no answer from engine"}
        if last["type"] != "servers":
            sys.stderr.write(tr("error: %s\n") % tr(str(last.get("message"))))
            return 1
        for s in last["servers"]:
            print("%-45s %s" % (s["host"], s["name"]))
        return 0

    if server is None:
        events = _collect("locate", None, quiet=True, network=network)
        last = events[-1] if events else {"type": "error", "message": "no answer from engine"}
        if last["type"] != "servers":
            sys.stderr.write(tr("error: %s\n") % tr(str(last.get("message"))))
            return 1
        server = last["servers"][0]
        if not args.json:
            sys.stderr.write(tr("Server: %s (%s)\n") % (server["name"], server["host"]))

    events = _collect("run", server, quiet=args.json, high_speed=high_speed)
    result = next((e for e in events if e["type"] == "result"), None)
    if result is None:
        err = next((e for e in events if e["type"] == "error"), {"message": "test failed"})
        sys.stderr.write(tr("error: %s\n") % tr(err["message"]))
        return 1
    if not args.no_save:
        try:
            History().add(result, server["backend"], server["name"])
        except Exception:  # noqa: BLE001 - history is optional
            pass
    if args.json:
        out = dict(result)
        out.pop("type", None)
        out["server"] = {"name": server["name"], "backend": server["backend"]}
        print(json.dumps(out, indent=2))
    else:
        print("%-9s %8.1f ms   (%s %.1f ms)" % (
            tr("Ping"), result["ping_ms"], tr("jitter"), result["jitter_ms"]))
        print("%-9s %8.1f Mbit/s" % (tr("Download"), result["download_mbps"]))
        print("%-9s %8.1f Mbit/s" % (tr("Upload"), result["upload_mbps"]))
    return 0
