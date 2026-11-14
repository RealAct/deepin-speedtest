"""Set the application and package version everywhere it appears.

Usage: python3 tools/set_version.py 1.2.3 [SOURCE_DIR]

Used by the release workflow so that the .deb version always matches the
release tag. Only plain MAJOR.MINOR.PATCH versions are accepted.
"""
import pathlib
import re
import sys

version = sys.argv[1] if len(sys.argv) in (2, 3) else ""
if not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", version):
    sys.exit("usage: set_version.py MAJOR.MINOR.PATCH [SOURCE_DIR]")
root = (pathlib.Path(sys.argv[2]) if len(sys.argv) == 3
        else pathlib.Path(__file__).resolve().parent.parent).resolve()


def sub(rel, pattern, repl, count=1):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, repl, text, count=count, flags=re.M)
    if n == 0:
        sys.exit("version pattern not found in %s" % rel)
    path.write_text(new, encoding="utf-8")


sub("swiftlet/__init__.py", r'^__version__ = "[^"]*"', '__version__ = "%s"' % version)
sub("debian/changelog", r"^swiftlet \([^)]*\)", "swiftlet (%s)" % version)
sub("man/swiftlet.1", r'"swiftlet [0-9.]+"', '"swiftlet %s"' % version)
sub("data/io.github.realact.Swiftlet.metainfo.xml", r'<release version="[^"]*"', '<release version="%s"' % version)
print("version set to", version)
