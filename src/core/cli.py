"""Command-line entry point: parse arguments, set up logging, run the app.

Verbosity comes from the mutually exclusive `-v`/`--verbose` and `-q`/`--quiet`
flags, or — with neither — the `EASYSPEAK_LOG_LEVEL` environment variable, which
the flags override (see [`resolve_level`][core.log.resolve_level]). The one-shot
`--configure` and `--show` subcommands set up or print the desktop-integration
files and exit. All `EASYSPEAK_*` variables are listed in [`core.config`][core.config].
"""

import argparse

from . import log


def parse_args(argv=None):
    """Parse EasySpeak's command-line arguments."""
    config_items = {"extension", "service", "autostart", "desktop"}
    config_defaults = {"extension", "service"}

    parser = argparse.ArgumentParser(
        prog="easyspeak", description="Voice control for Linux desktops."
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="show only warnings and errors"
    )
    verbosity.add_argument(
        "-v", "--verbose", action="store_true", help="show debug output"
    )
    parser.add_argument(
        "--configure",
        nargs="*",
        choices=config_items,
        help=(
            "set up the listed activities and exit "
            f"(default: {' '.join(config_defaults)})"
        ),
    )
    parser.add_argument(
        "--show",
        nargs="*",
        choices=config_items,
        help="print the listed items' files to stdout and exit (default: all)",
    )
    args = parser.parse_args(argv)

    if args.configure is not None:
        args.configure = set(args.configure) or config_defaults
    if args.show is not None:
        args.show = set(args.show) or config_items

    return args


def run(argv=None):
    """Start the application, or run a one-shot subcommand and exit.

    `EasySpeak` is imported lazily so the one-shot subcommands work without the
    audio stack (pyopen-wakeword, pyaudio, …) that `core.main` pulls in.
    """
    args = parse_args(argv)

    if args.show is not None:
        from .desktop_integration import show

        show(args.show)
        return

    log.configure(log.resolve_level(verbose=args.verbose, quiet=args.quiet))

    if args.configure is not None:
        from .desktop_integration import configure

        configure(args.configure)
        return

    from .main import EasySpeak

    EasySpeak().run()
