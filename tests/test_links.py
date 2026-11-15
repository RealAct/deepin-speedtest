import subprocess

from deepin_speedtest import links


def test_links_use_ascii_hosts():
    assert links.LINKS["https://deepinenespañol.org"] == (
        "https://" + "deepinenespañol.org".encode("idna").decode("ascii"))
    for url in links.LINKS.values():
        assert url.startswith("https://") and url.isascii()


def test_only_the_apps_own_links_can_be_opened(monkeypatch):
    calls = []
    monkeypatch.setattr(links, "_open_with_portal", lambda url: calls.append(("portal", url)) or True)
    monkeypatch.setattr(links, "_open_with_xdg_open", lambda url: calls.append(("xdg", url)) or True)
    for bad in ("https://example.org", "file:///etc/passwd", "https://realact.net/x",
                "https://realact.net@evil.example", "javascript:alert(1)", "", "https://deepinenespañol.org"):
        assert links.open_link(bad) is False
    assert calls == []
    assert links.open_link("https://realact.net") is True
    assert calls == [("portal", "https://realact.net")]


def test_falls_back_to_xdg_open_without_a_shell(monkeypatch):
    started = []

    def popen(argv, **kwargs):
        started.append((argv, kwargs))

    monkeypatch.setattr(links, "_open_with_portal", lambda url: False)
    monkeypatch.setattr(links.os, "access", lambda path, mode: path == links.XDG_OPEN)
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert links.open_link("https://xn--deepinenespaol-1nb.org") is True
    argv, kwargs = started[0]
    assert argv == ["/usr/bin/xdg-open", "https://xn--deepinenespaol-1nb.org"]
    assert not kwargs.get("shell") and kwargs["start_new_session"] is True

    monkeypatch.setattr(links.os, "access", lambda path, mode: False)
    assert links.open_link("https://realact.net") is False
