"""Command-line entry point: parse arguments, set up logging, run the app."""

import argparse

from . import log
from .main import EasySpeak


def parse_args(argv=None):
    """Parse EasySpeak's command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="easyspeak", description="Voice control for Linux desktops."
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", action="store_true", help="show debug output"
    )
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="show only warnings and errors"
    )
    return parser.parse_args(argv)


def run(argv=None):
    """Start the application."""
    args = parse_args(argv)
    log.configure(log.resolve_level(verbose=args.verbose, quiet=args.quiet))
    EasySpeak().run()
