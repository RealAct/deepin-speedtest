"""Process hardening and sandboxing, using only the Python standard library.

Two layers are used:

* ``harden_process()`` runs in every Deepin Speedtest process: restrictive umask,
  no core dumps, not ptrace-able by other processes of the same user, and
  ``no_new_privs`` so nothing we start can ever gain privileges (setuid,
  file capabilities).
* ``sandbox_engine()`` runs in the measurement engine, the only process
  that parses data from the network. It uses Landlock (Linux 5.13+) to deny
  all file system writes, deny reads outside system directories (so a
  compromised engine cannot read ``~/.ssh`` or browser profiles), deny
  ``execve``, and on Linux 6.7+ restrict outgoing TCP to the ports the test
  needs. Resource limits cap file size, open files and memory.

Every step is best effort: on kernels without Landlock the app still works
and reports which protections are active.
"""

from __future__ import annotations

import ctypes
import os
import resource
import sys
from typing import Dict, Iterable, List, Optional

PR_SET_DUMPABLE = 4
PR_SET_NO_NEW_PRIVS = 38

SYS_landlock_create_ruleset = 444  # identical on all Linux architectures
SYS_landlock_add_rule = 445
SYS_landlock_restrict_self = 446
LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
LANDLOCK_RULE_PATH_BENEATH = 1
LANDLOCK_RULE_NET_PORT = 2

FS_EXECUTE = 1 << 0
FS_WRITE_FILE = 1 << 1
FS_READ_FILE = 1 << 2
FS_READ_DIR = 1 << 3
FS_ABI1_ALL = (1 << 13) - 1
FS_REFER = 1 << 13        # ABI 2
FS_TRUNCATE = 1 << 14     # ABI 3
FS_IOCTL_DEV = 1 << 15    # ABI 5
NET_BIND_TCP = 1 << 0     # ABI 4
NET_CONNECT_TCP = 1 << 1  # ABI 4
SCOPE_ABSTRACT_UNIX = 1 << 0  # ABI 6
SCOPE_SIGNAL = 1 << 1         # ABI 6

READ_ONLY_ROOTS = (
    "/usr", "/lib", "/lib32", "/lib64", "/libx32", "/bin", "/sbin", "/etc", "/proc/self",
    # resolv.conf is often a symlink into one of these:
    "/run/systemd/resolve", "/run/NetworkManager", "/run/resolvconf", "/run/connman",
    "/var/run/NetworkManager",
)
READ_ONLY_FILES = ("/dev/null", "/dev/urandom", "/dev/random")


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64),
                ("handled_access_net", ctypes.c_uint64),
                ("scoped", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class _NetPortAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("port", ctypes.c_uint64)]


_LIBC: Optional[ctypes.CDLL] = None


def _libc() -> Optional[ctypes.CDLL]:
    # CDLL(None) exposes the symbols already linked into the interpreter,
    # including libc, without running ldconfig/gcc like find_library() does.
    global _LIBC
    if _LIBC is None:
        try:
            _LIBC = ctypes.CDLL(None, use_errno=True)
        except OSError:
            return None
    return _LIBC


def refuse_root() -> None:
    """Exit if started as root: Deepin Speedtest never needs privileges."""
    if os.geteuid() == 0 or os.getegid() == 0:
        sys.stderr.write("deepin-speedtest: refusing to run as root; start it as a normal user.\n")
        raise SystemExit(2)


def harden_process() -> Dict[str, bool]:
    report = {"umask": False, "no_core": False, "not_dumpable": False, "no_new_privs": False}
    os.umask(0o077)
    report["umask"] = True
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        report["no_core"] = True
    except (ValueError, OSError):
        pass
    libc = _libc()
    if libc is not None:
        report["not_dumpable"] = libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
        report["no_new_privs"] = libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0
    return report


def landlock_abi() -> int:
    libc = _libc()
    if libc is None:
        return 0
    abi = libc.syscall(SYS_landlock_create_ruleset, None, ctypes.c_size_t(0),
                       ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION))
    return abi if abi > 0 else 0


def _extra_read_paths() -> List[str]:
    """Interpreter and package locations outside /usr (venvs, source checkouts)."""
    pkg_parent = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    paths = {pkg_parent, os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix),
             os.path.dirname(os.path.realpath(sys.executable))}
    return sorted(p for p in paths if p and p != "/")


def apply_landlock(tcp_ports: Iterable[int]) -> int:
    """Restrict this process with Landlock. Returns the ABI used (0 = not applied)."""
    abi = landlock_abi()
    if abi == 0:
        return 0
    libc = _libc()
    assert libc is not None

    fs = FS_ABI1_ALL
    if abi >= 2:
        fs |= FS_REFER
    if abi >= 3:
        fs |= FS_TRUNCATE
    if abi >= 5:
        fs |= FS_IOCTL_DEV
    net = (NET_BIND_TCP | NET_CONNECT_TCP) if abi >= 4 else 0
    scoped = (SCOPE_ABSTRACT_UNIX | SCOPE_SIGNAL) if abi >= 6 else 0
    attr = _RulesetAttr(fs, net, scoped)
    size = 8 if abi < 4 else (16 if abi < 6 else 24)

    ruleset = libc.syscall(SYS_landlock_create_ruleset, ctypes.byref(attr),
                           ctypes.c_size_t(size), ctypes.c_uint32(0))
    if ruleset < 0:
        return 0
    try:
        for path in list(READ_ONLY_ROOTS) + _extra_read_paths() + list(READ_ONLY_FILES):
            _allow_path(libc, ruleset, path)
        if net:
            for port in sorted(set(tcp_ports)):
                rule = _NetPortAttr(NET_CONNECT_TCP, port)
                if libc.syscall(SYS_landlock_add_rule, ctypes.c_int(ruleset),
                                ctypes.c_int(LANDLOCK_RULE_NET_PORT), ctypes.byref(rule),
                                ctypes.c_uint32(0)) != 0:
                    return 0
        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            return 0
        if libc.syscall(SYS_landlock_restrict_self, ctypes.c_int(ruleset), ctypes.c_uint32(0)) != 0:
            return 0
    finally:
        os.close(ruleset)
    return abi


def _allow_path(libc: ctypes.CDLL, ruleset: int, path: str) -> None:
    try:
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except OSError:
        return
    try:
        allowed = FS_READ_FILE | (FS_READ_DIR if os.path.isdir(path) else 0)
        rule = _PathBeneathAttr(allowed, fd)
        libc.syscall(SYS_landlock_add_rule, ctypes.c_int(ruleset),
                     ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH), ctypes.byref(rule), ctypes.c_uint32(0))
    finally:
        os.close(fd)


def sandbox_engine(tcp_ports: Iterable[int]) -> Dict[str, object]:
    """Lock down the measurement engine before it touches the network."""
    report: Dict[str, object] = dict(harden_process())
    limits = {
        "RLIMIT_FSIZE": (0, 0),             # cannot write to any regular file
        "RLIMIT_NOFILE": (64, 64),
        "RLIMIT_AS": (2 << 30, 2 << 30),   # 2 GiB of address space
    }
    for name, value in limits.items():
        try:
            resource.setrlimit(getattr(resource, name), value)
            report[name.lower()] = True
        except (ValueError, OSError, AttributeError):
            report[name.lower()] = False
    ports = set(tcp_ports) | {53}  # DNS over TCP fallback
    report["landlock_abi"] = apply_landlock(ports)
    return report
