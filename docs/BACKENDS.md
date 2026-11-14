# Choosing a speed-test backend

Swiftlet uses only open, documented protocols and servers whose operators allow third-party
clients. It does **not** use Ookla's servers or private APIs: there is no public licence for
third-party clients, and using them without permission would breach their terms.

## Options considered

| | M-Lab ndt7 (public) | ndt7 self-hosted | LibreSpeed self-hosted | Ookla / Speedtest.net | fast.com (Netflix) |
| --- | --- | --- | --- | --- | --- |
| Open protocol | Yes ([spec](https://github.com/m-lab/ndt-server/blob/main/spec/ndt7-protocol.md)) | Yes | Yes (simple HTTP) | No (private) | No (undocumented) |
| Allowed for third-party apps | Yes, via the public Locate API | Yes | Yes | Only with a commercial licence | Not documented |
| Global server network | Yes, hundreds of sites | No | No | Yes | Yes |
| Cost | Free | Your hosting | Your hosting | Licence | n/a |
| TLS | `wss://` | `wss://` (your certificate) | `https://` (your certificate) | n/a | n/a |
| Privacy | **Results, including the client IP, are published as open data** | Stays with you | Stays with you | n/a | n/a |
| Measurement | One TCP stream per direction, ~10 s; kernel `TCP_INFO` from the server | Same | Several parallel HTTP streams | | |

## Decision

* **Default: M-Lab ndt7.** It is the only open, free, global network that explicitly welcomes
  third-party clients. Swiftlet finds servers with the documented Locate API
  (`locate.measurementlab.net/v2/nearest/ndt/ndt7`), which returns short-lived access tokens.
  Swiftlet only sends the `client_name` and `client_version` parameters that the spec asks for.
* **Self-hosted ndt7 and LibreSpeed** are first-class options for people who do not want their IP
  in a public dataset, for LAN and ISP testing, and for organisations.

## Trade-offs to know about

* **Privacy of M-Lab:** M-Lab publishes every test with the client IP address. Swiftlet shows this
  notice and asks for consent before the first M-Lab test (desktop and CLI).
* **Single stream vs. multi-stream:** ndt7 uses one TCP connection per direction. On very fast
  (multi-gigabit) or lossy, high-latency links, a single stream can read lower than the
  multi-stream tests most commercial services use. LibreSpeed uses 4 parallel streams.
* **Ping method:** Swiftlet times TCP handshakes rather than ICMP echo, because ICMP needs raw
  sockets (root or `CAP_NET_RAW`). Handshake times are a close, slightly higher, approximation of
  ICMP ping. "Loaded latency" comes from the server's kernel RTT estimate during the ndt7 transfer.
* **Upload rate:** for ndt7, Swiftlet reports the rate measured by the server
  (`TCPInfo.BytesReceived`), which is more accurate than counting bytes handed to the local kernel.
* **No plain HTTP / `ws://`:** self-hosted servers need a valid TLS certificate, for example from
  Let's Encrypt or an internal CA trusted by the system.
* **Proxies:** the engine ignores proxy environment variables (it runs with a minimal
  environment). Testing through a proxy measures the proxy anyway.
