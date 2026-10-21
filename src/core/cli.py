"""Command-line entry point: parse arguments, set up logging, run the app.

Verbosity comes from the mutually exclusive `-v`/`--verbose` and `-q`/`--quiet`
flags, or, with neither, the `EASYSPEAK_LOG_LEVEL` environment variable, which
the flags override (see [`resolve_level`][core.log.resolve_level]). `--language`
is the command-line form of `EASYSPEAK_LANGUAGE` and overrides it. The one-shot
`--configure` and `--preview` subcommands set up or print the desktop-integration
files and exit. All `EASYSPEAK_*` variables are listed in [`core.config`][core.config].
"""

import argparse
import logging
import os

from . import log
from .about import app_version

logger = logging.getLogger(__name__)


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
        "--preview",
        choices=config_items,
        help="print the file content that would be configured and exit",
    )
    parser.add_argument(
        "--language",
        metavar="CODE",
        help=(
            "language to dictate and be answered in, e.g. de; "
            "alternatively set EASYSPEAK_LANGUAGE (default: en)"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {app_version()}",
        help="show the installed version and exit",
    )
    args = parser.parse_args(argv)

    if args.configure is not None:
        args.configure = set(args.configure) or config_defaults

    return args


def run(argv=None):
    """Start the application, or run a one-shot subcommand and exit.

    `EasySpeak` is imported lazily so the one-shot subcommands work without the
    audio stack (pyopen-wakeword, pyaudio, …) that `core.main` pulls in. Ctrl+C
    ends EasySpeak quietly even while that stack or its models are still loading.
    """
    args = parse_args(argv)

    if args.preview is not None:
        from .desktop_integration import preview

        preview(args.preview)
        return

    log.configure(log.resolve_level(verbose=args.verbose, quiet=args.quiet))

    if args.language:
        # The config reads the variable when it is imported, below.
        os.environ["EASYSPEAK_LANGUAGE"] = args.language

    if args.configure is not None:
        from .desktop_integration import configure

        configure(args.configure)
        return

    try:
        from .main import EasySpeak

        EasySpeak().run()
    except KeyboardInterrupt:
        logger.info("\nStopped (Ctrl+C).")
