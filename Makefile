# Plain install rules, used directly or by debhelper (dh_auto_install).
PREFIX  ?= /usr
DESTDIR ?=
PYTHON  ?= python3
APPID   := io.github.realact.Swiftlet
PKGDIR  := $(DESTDIR)$(PREFIX)/share/swiftlet

.PHONY: all install test lint clean

all:
	@true

install:
	install -d $(PKGDIR)/swiftlet/engine
	install -m 0644 swiftlet/*.py $(PKGDIR)/swiftlet/
	install -m 0644 swiftlet/engine/*.py $(PKGDIR)/swiftlet/engine/
	install -D -m 0755 bin/swiftlet $(DESTDIR)$(PREFIX)/bin/swiftlet
	install -D -m 0644 data/$(APPID).desktop $(DESTDIR)$(PREFIX)/share/applications/$(APPID).desktop
	install -D -m 0644 data/$(APPID).metainfo.xml $(DESTDIR)$(PREFIX)/share/metainfo/$(APPID).metainfo.xml
	install -D -m 0644 data/icons/$(APPID).svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/$(APPID).svg
	install -D -m 0644 man/swiftlet.1 $(DESTDIR)$(PREFIX)/share/man/man1/swiftlet.1

test:
	$(PYTHON) -m pytest -q -p no:cacheprovider tests

lint:
	$(PYTHON) tools/check_py38.py

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
