import sys


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        from . import APP_NAME, __version__
        print("%s %s" % (APP_NAME, __version__))
        return 0
    if args[:1] == ["--cli"]:
        from .cli import main as cli_main
        return cli_main(args[1:])
    if args[:1] in (["-h"], ["--help"]):
        from .i18n import tr
        print(tr("usage: deepin-speedtest [--cli [options] | --version]\n"
                 "Run without arguments for the desktop app; "
                 "'deepin-speedtest --cli --help' for the terminal."))
        return 0
    from .hardening import refuse_root
    refuse_root()  # before Qt is even imported
    from .app import main as gui_main
    return gui_main(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
