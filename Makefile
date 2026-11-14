# Plain install rules, used directly or by debhelper (dh_auto_install).
PREFIX  ?= /usr
DESTDIR ?=
PYTHON  ?= python3
APPID   := io.github.realact.DeepinSpeedtest
PKGDIR  := $(DESTDIR)$(PREFIX)/share/deepin-speedtest

.PHONY: all install test lint clean

all:
	@true

install:
	install -d $(PKGDIR)/deepin_speedtest/engine
	install -m 0644 deepin_speedtest/*.py $(PKGDIR)/deepin_speedtest/
	install -m 0644 deepin_speedtest/engine/*.py $(PKGDIR)/deepin_speedtest/engine/
	install -D -m 0755 bin/deepin-speedtest $(DESTDIR)$(PREFIX)/bin/deepin-speedtest
	install -D -m 0644 data/$(APPID).desktop $(DESTDIR)$(PREFIX)/share/applications/$(APPID).desktop
	install -D -m 0644 data/$(APPID).metainfo.xml $(DESTDIR)$(PREFIX)/share/metainfo/$(APPID).metainfo.xml
	install -D -m 0644 data/icons/$(APPID).svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/$(APPID).svg
	install -D -m 0644 man/deepin-speedtest.1 $(DESTDIR)$(PREFIX)/share/man/man1/deepin-speedtest.1

test:
	$(PYTHON) -m pytest -q -p no:cacheprovider tests

lint:
	$(PYTHON) tools/check_py38.py

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
