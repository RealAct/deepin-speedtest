"""How the UI starts the engine, and strict validation of what it says back.

The engine is treated as untrusted: it parses network data, so if it were
ever compromised the UI must not be. Every event is size-limited, parsed,
and rebuilt from validated fields only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, Iterator, List, Optional

from .validate import (ValidationError, clean_text, finite_number, optional_number,
                       validate_hostname, validate_https_base, validate_ndt7_url)

MAX_LINE = 64 * 1024
PHASES = ("ping", "download", "upload")
SPEED_MAX = 1e6  # Mbit/s: 1 Tbit/s is a generous upper bound
MS_MAX = 600000.0


def engine_command() -> List[str]:
    """Command line that runs the engine in isolated mode (-I: ignore PYTHON*
    environment variables, user site-packages and the current directory)."""
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = "import sys;sys.path.insert(0,sys.argv[1]);from swiftlet.engine.main import main;sys.exit(main())"
    return [sys.executable, "-I", "-c", code, pkg_parent]


def engine_environment() -> Dict[str, str]:
    """A minimal environment: nothing like SSL_CERT_FILE or LD_PRELOAD leaks in."""
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    return env


def validate_server(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError("bad server entry")
    backend = raw.get("backend")
    if backend == "ndt7":
        custom = raw.get("custom") is True
        return {
            "backend": "ndt7",
            "custom": custom,
            "id": clean_text(raw.get("id", ""), 253),
            "name": clean_text(raw.get("name", ""), 120) or "ndt7 server",
            "host": validate_hostname(raw.get("host", "")),
            "provider": clean_text(raw.get("provider", ""), 40),
            "download_url": validate_ndt7_url(raw.get("download_url", ""), allow_any_host=custom,
                                              expected_test="download"),
            "upload_url": validate_ndt7_url(raw.get("upload_url", ""), allow_any_host=custom,
                                            expected_test="upload"),
        }
    if backend == "librespeed":
        return {
            "backend": "librespeed",
            "custom": True,
            "id": clean_text(raw.get("id", ""), 253),
            "name": clean_text(raw.get("name", ""), 120) or "LibreSpeed server",
            "host": validate_hostname(raw.get("host", "")),
            "provider": "LibreSpeed",
            "base_url": validate_https_base(raw.get("base_url", "")),
        }
    raise ValidationError("unknown backend")


def validate_event(line: bytes) -> Dict[str, Any]:
    if len(line) > MAX_LINE:
        raise ValidationError("engine message too long")
    try:
        ev = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValidationError("engine sent invalid JSON")
    if not isinstance(ev, dict):
        raise ValidationError("engine sent a non-object")
    kind = ev.get("type")
    if kind == "stage":
        return {"type": kind, "phase": _phase(ev.get("phase"))}
    if kind == "progress":
        phase = _phase(ev.get("phase"))
        hi = MS_MAX if phase == "ping" else SPEED_MAX
        return {"type": kind, "phase": phase, "value": finite_number(ev.get("value"), 0, hi),
                "fraction": finite_number(ev.get("fraction"), 0, 1)}
    if kind == "latency":
        return {"type": kind, "ping_ms": finite_number(ev.get("ping_ms"), 0, MS_MAX),
                "jitter_ms": finite_number(ev.get("jitter_ms"), 0, MS_MAX)}
    if kind == "measured":
        phase = _phase(ev.get("phase"))
        if phase == "ping":
            raise ValidationError("bad phase")
        return {"type": kind, "phase": phase, "value": finite_number(ev.get("value"), 0, SPEED_MAX)}
    if kind == "result":
        return {
            "type": kind,
            "timestamp": int(finite_number(ev.get("timestamp"), 0, 1e11)),
            "host": validate_hostname(ev.get("host", "")),
            "ping_ms": finite_number(ev.get("ping_ms"), 0, MS_MAX),
            "jitter_ms": finite_number(ev.get("jitter_ms"), 0, MS_MAX),
            "download_mbps": finite_number(ev.get("download_mbps"), 0, SPEED_MAX),
            "upload_mbps": finite_number(ev.get("upload_mbps"), 0, SPEED_MAX),
            "download_latency_ms": optional_number(ev.get("download_latency_ms"), 0, MS_MAX),
            "upload_latency_ms": optional_number(ev.get("upload_latency_ms"), 0, MS_MAX),
        }
    if kind == "servers":
        servers = ev.get("servers")
        if not isinstance(servers, list) or len(servers) > 16:
            raise ValidationError("bad server list")
        return {"type": kind, "servers": [validate_server(s) for s in servers]}
    if kind == "sandbox":
        abi = ev.get("landlock_abi")
        return {"type": kind, "landlock_abi": int(finite_number(abi, 0, 1000)),
                "no_new_privs": ev.get("no_new_privs") is True}
    if kind == "error":
        return {"type": kind, "message": clean_text(ev.get("message", ""), 300) or "Unknown error"}
    raise ValidationError("unknown engine message")


def _phase(value: Any) -> str:
    if value not in PHASES:
        raise ValidationError("bad phase")
    return value


def request_line(op: str, server: Optional[Dict[str, Any]] = None) -> bytes:
    req: Dict[str, Any] = {"op": op}
    if server is not None:
        req["server"] = server
    return (json.dumps(req, separators=(",", ":")) + "\n").encode("utf-8")


def run_engine(op: str, server: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
    """Run the engine synchronously (used by the CLI) and yield validated events."""
    proc = subprocess.Popen(engine_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=engine_environment(), cwd="/",
                            close_fds=True)
    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write(request_line(op, server))
        proc.stdin.close()
        while True:
            line = proc.stdout.readline(MAX_LINE + 1)
            if not line:
                break
            try:
                yield validate_event(line.rstrip(b"\n"))
            except ValidationError as exc:
                yield {"type": "error", "message": "Engine protocol error: %s" % exc}
                break
    finally:
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait(timeout=5)
