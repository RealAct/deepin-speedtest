"""Stand-in for the engine process in GUI tests: replays canned, valid events."""
import json
import sys

HOST = "ndt-mlab1-ams03.mlab-oti.measurement-lab.org"
req = json.loads(sys.stdin.readline())


def emit(ev):
    sys.stdout.write(json.dumps(ev) + "\n")
    sys.stdout.flush()


emit({"type": "sandbox", "landlock_abi": 4, "no_new_privs": True})
if req["op"] == "locate":
    emit({"type": "servers", "servers": [{
        "backend": "ndt7", "id": "mlab1-ams03.mlab-oti.measurement-lab.org", "name": "Amsterdam, NL",
        "host": "mlab1-ams03.mlab-oti.measurement-lab.org", "provider": "M-Lab",
        "download_url": "wss://%s/ndt/v7/download?access_token=abc" % HOST,
        "upload_url": "wss://%s/ndt/v7/upload?access_token=abc" % HOST}]})
else:
    emit({"type": "stage", "phase": "ping"})
    emit({"type": "progress", "phase": "ping", "value": 9.5, "fraction": 0.5})
    emit({"type": "latency", "ping_ms": 9.5, "jitter_ms": 0.7})
    for phase, value in (("download", 250.0), ("upload", 40.0)):
        emit({"type": "stage", "phase": phase})
        emit({"type": "progress", "phase": phase, "value": value, "fraction": 0.5})
        emit({"type": "measured", "phase": phase, "value": value})
    emit({"type": "result", "timestamp": 1763136000, "host": HOST, "ping_ms": 9.5, "jitter_ms": 0.7,
          "download_mbps": 250.0, "upload_mbps": 40.0, "download_latency_ms": 20.0,
          "upload_latency_ms": None})
