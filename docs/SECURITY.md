# Security design

## Assets and threats

| Asset | Threat |
| --- | --- |
| The user's account and files (SSH keys, browser profiles, documents) | A malicious or compromised test server, or a network attacker, exploits a parsing bug to run code or read files |
| The user's privacy (IP address, usage) | Telemetry, tracking, or test data sent to third parties without consent |
| Integrity of results | A network attacker (MITM) changes results or redirects tests |
| The system | Privilege escalation through a setuid helper, root daemon or package scripts |

The **test server and the network are untrusted**. The user and their own settings files are
trusted, but their contents are still validated.

## Architecture

```
┌────────────────────────── user session (unprivileged) ─────────────────────────┐
│                                                                                │
│  deepin-speedtest (Qt UI)                      deepin-speedtest engine (child process)         │
│  - no network access                   - Landlock: no file writes, no exec,    │
│  - umask 077, not dumpable,              reads limited to system dirs,         │
│    no core dumps, no_new_privs           TCP connect only to needed ports      │
│  - validates every engine event ◄──────- RLIMIT_FSIZE=0, NOFILE=128, AS=2GiB   │
│    (size, type, range, charset)  JSON  - python3 -I, empty environment, cwd=/ │
│  - history: SQLite 0600          lines - strict WebSocket/TLS client ──────────┼──► wss:// / https://
│  - settings: JSON 0600, atomic         - kills itself on protocol violations   │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Least privilege

* Both processes refuse to run as root. There are no setuid binaries, capabilities, daemons,
  systemd units, polkit rules or package maintainer scripts.
* Latency is measured by timing TCP handshakes, so no `CAP_NET_RAW` is needed for ICMP.
* `PR_SET_NO_NEW_PRIVS` is set, so no child process can ever gain privileges.
* `PR_SET_DUMPABLE=0` and `RLIMIT_CORE=0`: other processes of the same user cannot ptrace
  Deepin Speedtest, and no core files are written.

### Sandbox (engine)

The engine is the only code that parses network data, so it is confined before the first
connection (`deepin_speedtest/hardening.py`):

* **Landlock** (Linux ≥ 5.13; features are used up to the kernel's ABI):
  * file system: read-only access to `/usr`, `/lib*`, `/etc`, `/proc/self`, resolver directories
    under `/run`, and the interpreter/package location; **no** writes, deletes, creating files,
    `execve`, or device ioctls anywhere. Your home directory is not readable.
  * network (ABI ≥ 4, Linux 6.7+): TCP `connect` only to the server's port(s) and 53 (DNS over
    TCP), and no `bind`.
  * scoping (ABI ≥ 6): no abstract UNIX sockets and no signals to processes outside the sandbox.
* **Resource limits:** `RLIMIT_FSIZE=0` (cannot write regular files even without Landlock),
  `RLIMIT_NOFILE=128`, `RLIMIT_AS=2 GiB`.
* **Isolated interpreter:** `python3 -I` ignores `PYTHON*` variables, the user site directory and
  the working directory. The environment is replaced by a minimal one, so variables such as
  `LD_PRELOAD`, `SSL_CERT_FILE` or `https_proxy` cannot change its behaviour.
* The UI kills the engine on a protocol error, an oversized message, or after a 2-minute watchdog.

On kernels without Landlock (for example the 5.10 kernel of the end-of-life Debian 11), the rest still applies and the
*About* dialog shows which protections are active.

### TLS and protocol handling

* `wss://` and `https://` only, with no option to disable verification. The system CA store is
  used, with hostname checking and TLS 1.2 as the minimum.
* HTTP redirects are never followed.
* M-Lab URLs from the Locate API must be `wss://` on a `*.measurement-lab.org` host with the exact
  ndt7 path. Any other entry is dropped.
* WebSocket client (`deepin_speedtest/engine/wsclient.py`): checks `Sec-WebSocket-Accept` and the
  subprotocol, rejects extensions, masked server frames, reserved bits, unknown opcodes, oversized
  control frames, messages over 16 MiB and text over 64 KiB. Binary data is counted and thrown away,
  never stored. Handshake responses are limited to 16 KiB.
* Every client frame uses a fresh random masking key from `secrets`. Upload filler is random data
  sent pre-masked, which RFC 6455 allows, because its content is irrelevant.

### Input validation

All untrusted input goes through `deepin_speedtest/validate.py` or `deepin_speedtest/protocol.py`:

* host names (IDNA, label syntax, length), ports and URLs (scheme allow-list, no credentials, no
  `..`, no query or fragment for base URLs);
* numbers must be finite and inside a range (no NaN or Infinity);
* text has control, format and bidi-override characters removed and is length-limited;
* engine events are rebuilt from allow-listed fields only, so unknown fields are dropped.

### Local data

* Settings (`~/.config/deepin-speedtest/settings.json`) and history
  (`~/.local/share/deepin-speedtest/history.sqlite3`) are created 0600 in 0700 directories. They are
  refused if they are symlinks or owned by someone else, and every entry is re-validated on load.
* SQL uses parameters only. `secure_delete` overwrites deleted rows, and "Clear all" runs `VACUUM`.
* CSV export opens with `O_NOFOLLOW` and escapes cells that start with `= + - @` (formula
  injection).

### Supply chain

* Runtime dependencies are `python3`, `python3-pyqt5` and `ca-certificates`, all from the
  distribution's archive with its security updates. There are no pip packages, vendored libraries,
  or downloads at runtime.
* GitHub Actions are pinned to commit SHAs, the workflow token is read-only, and checkout does
  not persist credentials.

## Known limitations and future work

* **No seccomp filter yet.** Python's standard library has no seccomp bindings, and adding
  libseccomp would add a dependency. Landlock plus resource limits cover file and network access.
* **AppArmor profile:** not shipped yet. An enforced profile for the engine would add protection
  on kernels without Landlock (such as Debian 11), but it needs testing on each distribution first.
* **The UI process is not sandboxed** beyond the hardening above, because Qt needs broad access
  (fonts, themes, input methods, file dialogs). It never parses network data.
* **Flatpak / Linglong** packaging would add namespace isolation and is a natural next step for
  Deepin 23's Linglong format.
