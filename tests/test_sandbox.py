import json
import os
import socket
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deepin_speedtest import hardening  # noqa: E402
from deepin_speedtest.protocol import engine_command, engine_environment, request_line, validate_event  # noqa: E402

PROBE = textwrap.dedent("""
    import json, os, socket, sys
    sys.path.insert(0, sys.argv[1])
    from deepin_speedtest import hardening
    secret, allowed, blocked = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    report = hardening.sandbox_engine([allowed])
    out = {"abi": report["landlock_abi"]}
    def attempt(fn):
        try:
            fn(); return "ok"
        except OSError as e:
            return e.__class__.__name__
    out["read_secret"] = attempt(lambda: open(secret).read())
    out["write_tmp"] = attempt(lambda: open("/tmp/deepin-speedtest-probe-%d" % os.getpid(), "w").write("x"))
    out["read_usr"] = attempt(lambda: os.listdir("/usr"))
    out["exec"] = attempt(lambda: os.execv("/bin/true", ["true"]))
    def conn(p):
        s = socket.create_connection(("127.0.0.1", p), timeout=2); s.close()
    out["connect_allowed"] = attempt(lambda: conn(allowed))
    out["connect_blocked"] = attempt(lambda: conn(blocked))
    print(json.dumps(out))
""")


def _listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    return s


@pytest.mark.skipif(hardening.landlock_abi() == 0, reason="kernel has no Landlock")
def test_engine_sandbox_blocks_files_exec_and_ports(tmp_path):
    secret = tmp_path / "id_secret"
    secret.write_text("top secret")
    a, b = _listener(), _listener()
    try:
        res = subprocess.run([sys.executable, "-I", "-c", PROBE, ROOT, str(secret),
                              str(a.getsockname()[1]), str(b.getsockname()[1])],
                             capture_output=True, text=True, timeout=30)
    finally:
        a.close()
        b.close()
    out = json.loads(res.stdout)
    assert out["abi"] >= 1
    assert out["read_secret"] == "PermissionError"
    assert out["write_tmp"] in ("PermissionError", "OSError")
    assert out["read_usr"] == "ok"
    assert out["exec"] == "PermissionError"
    if out["abi"] >= 4:
        assert out["connect_allowed"] == "ok"
        assert out["connect_blocked"] == "PermissionError"


needs_non_root = pytest.mark.skipif(os.geteuid() == 0, reason="the engine refuses to run as root")


def test_engine_refuses_root_or_runs():
    proc = subprocess.run(engine_command(), input=b"{}\n", capture_output=True,
                          env=engine_environment(), cwd="/", timeout=30)
    if os.geteuid() == 0:
        assert proc.returncode == 2 and b"refusing to run as root" in proc.stderr
    else:
        assert proc.returncode == 1


@needs_non_root
def test_engine_rejects_bad_request_and_never_crashes():
    proc = subprocess.run(engine_command(), input=b'{"op":"run","server":{"backend":"ndt7",'
                          b'"download_url":"ws://evil.example/ndt/v7/download"}}\n',
                          capture_output=True, env=engine_environment(), cwd="/", timeout=30)
    events = [validate_event(line) for line in proc.stdout.splitlines()]
    assert events[-1]["type"] == "error"
    assert "wss" in events[-1]["message"]
    assert proc.returncode == 1


@needs_non_root
def test_engine_rejects_non_mlab_host_from_locate_path():
    server = {"backend": "ndt7", "custom": False,
              "download_url": "wss://attacker.example/ndt/v7/download",
              "upload_url": "wss://attacker.example/ndt/v7/upload"}
    proc = subprocess.run(engine_command(), input=request_line("run", server), capture_output=True,
                          env=engine_environment(), cwd="/", timeout=30)
    events = [validate_event(line) for line in proc.stdout.splitlines()]
    assert events[-1] == {"type": "error", "message": "server is not an M-Lab host"}
