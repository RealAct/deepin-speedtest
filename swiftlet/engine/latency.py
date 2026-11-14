"""Unprivileged latency measurement.

ICMP ping needs raw sockets (CAP_NET_RAW or a setuid helper), which would
break the "no privileges" rule. Instead we time TCP handshakes to the test
server: the kernel answers SYN/SYN-ACK without involving the server
application, so the connect time is a close approximation of one network
round trip.
"""

from __future__ import annotations

import socket
import statistics
import time
from typing import Callable, Dict, List, Optional

Emit = Callable[[Dict[str, object]], None]


def resolve(host: str, port: int) -> tuple:
    """Resolve once so that DNS time is not counted in the samples."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    if not infos:
        raise OSError("could not resolve %s" % host)
    family, socktype, proto, _, addr = infos[0]
    return family, socktype, proto, addr


def tcp_rtt_samples(host: str, port: int, count: int = 10, timeout: float = 3.0,
                    gap: float = 0.1, emit: Optional[Emit] = None) -> List[float]:
    family, socktype, proto, addr = resolve(host, port)
    samples: List[float] = []
    for i in range(count):
        s = socket.socket(family, socktype, proto)
        s.settimeout(timeout)
        try:
            t0 = time.perf_counter()
            s.connect(addr)
            samples.append((time.perf_counter() - t0) * 1000.0)
        except OSError:
            pass
        finally:
            s.close()
        if emit is not None and samples:
            emit({"type": "progress", "phase": "ping", "value": samples[-1],
                  "fraction": (i + 1) / count})
        time.sleep(gap)
    if len(samples) < max(3, count // 3):
        raise OSError("server did not answer enough latency probes")
    return samples


def summarize(samples: List[float]) -> Dict[str, float]:
    ping = statistics.median(samples)
    diffs = [abs(b - a) for a, b in zip(samples, samples[1:])]
    jitter = statistics.mean(diffs) if diffs else 0.0
    return {"ping_ms": round(ping, 2), "jitter_ms": round(jitter, 2), "min_ms": round(min(samples), 2)}
