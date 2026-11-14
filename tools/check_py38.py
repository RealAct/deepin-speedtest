"""Fail if any source file uses syntax newer than Python 3.8 (Ubuntu 20.04 / Mint 20)."""
import ast
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent.parent
bad = 0
for path in sorted(list((root / "swiftlet").rglob("*.py")) + [root / "bin" / "swiftlet"]):
    try:
        ast.parse(path.read_text(encoding="utf-8"), str(path), feature_version=(3, 8))
    except SyntaxError as exc:
        print("%s: %s" % (path, exc))
        bad += 1
sys.exit(1 if bad else 0)
