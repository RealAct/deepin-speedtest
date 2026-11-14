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
    sys.stderr.write(NOTICE)
    if not assume_yes:
        if not sys.stdin.isatty():
            sys.stderr.write("Re-run with --accept-mlab-privacy to continue.\n")
            return False
        answer = input("Continue with M-Lab servers? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            return False
    settings["mlab_consent"] = True
    try:
        settings.save()
    except OSError:
        pass
    return True


def _collect(op: str, server: Optional[Dict[str, Any]], quiet: bool) -> List[Dict[str, Any]]:
    events = []
    for ev in run_engine(op, server):
        events.append(ev)
        if quiet:
            continue
        if ev["type"] == "stage":
            sys.stderr.write("\n%-9s" % ev["phase"].capitalize())
        elif ev["type"] == "progress" and ev["phase"] != "ping":
            sys.stderr.write("\r%-9s %8.1f Mbit/s" % (ev["phase"].capitalize(), ev["value"]))
        sys.stderr.flush()
    if not quiet:
        sys.stderr.write("\n")
    return events


def main(argv: Optional[List[str]] = None) -> int:
    hardening.refuse_root()
    hardening.harden_process()
    p = argparse.ArgumentParser(prog="deepin-speedtest --cli", description="%s %s command-line speed test" % (
        APP_NAME, __version__))
    p.add_argument("--list-servers", action="store_true", help="list nearby M-Lab servers")
    p.add_argument("--ndt7-server", metavar="HOST[:PORT]", help="use a self-hosted ndt7 server")
    p.add_argument("--librespeed", metavar="URL", help="use a self-hosted LibreSpeed server (https://...)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument("--no-save", action="store_true", help="do not add the result to the history")
    p.add_argument("--accept-mlab-privacy", action="store_true", help="accept the M-Lab data notice")
    args = p.parse_args(argv)

    settings = Settings()
    try:
        server = _custom_server(args)
    except ValidationError as exc:
        p.error(str(exc))
        return 2
    if server is None and not _consent(settings, args.accept_mlab_privacy):
        return 1

    if args.list_servers:
        events = _collect("locate", None, quiet=True)
        last = events[-1] if events else {"type": "error", "message": "no answer from engine"}
        if last["type"] != "servers":
            sys.stderr.write("error: %s\n" % last.get("message"))
            return 1
        for s in last["servers"]:
            print("%-45s %s" % (s["host"], s["name"]))
        return 0

    if server is None:
        events = _collect("locate", None, quiet=True)
        last = events[-1] if events else {"type": "error", "message": "no answer from engine"}
        if last["type"] != "servers":
            sys.stderr.write("error: %s\n" % last.get("message"))
            return 1
        server = last["servers"][0]
        if not args.json:
            sys.stderr.write("Server: %s (%s)\n" % (server["name"], server["host"]))

    events = _collect("run", server, quiet=args.json)
    result = next((e for e in events if e["type"] == "result"), None)
    if result is None:
        err = next((e for e in events if e["type"] == "error"), {"message": "test failed"})
        sys.stderr.write("error: %s\n" % err["message"])
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
        print("Ping      %8.1f ms   (jitter %.1f ms)" % (result["ping_ms"], result["jitter_ms"]))
        print("Download  %8.1f Mbit/s" % result["download_mbps"])
        print("Upload    %8.1f Mbit/s" % result["upload_mbps"])
    return 0
