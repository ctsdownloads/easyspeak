"""Optional desktop integration for non-packaged (pip / dev) installs.

Debian/RPM packages ship the launcher, autostart entry, and refresh service as
system files, so users there need do nothing. A pip or `uv` install has no such
hooks, so `easyspeak --configure` writes the per-user equivalents under `$HOME`.

The GNOME extension and its refresh service are always set up, because they are
what makes the panel/tray icon work. The launcher and autostart entries stay
opt-in, since not everyone wants EasySpeak in their menu or starting at login.
"""

import logging
import os
import re
import sys
from functools import partial
from pathlib import Path

from easyspeak.data import data_text

from .autostart import user_entry, with_value
from .gnome_extension import (
    activate_extension,
    extension_dest_dir,
    extension_source_dir,
    install_refresh_unit,
    unit_path,
    unit_text,
)

logger = logging.getLogger(__name__)

AUTOSTART_TEMPLATE = "easyspeak-autostart.desktop"
DESKTOP_TEMPLATE = "easyspeak.desktop"
INSTALLED_DESKTOP_NAME = "easyspeak.desktop"
# Characters that need quoting in an `Exec` argument, per the specification.
EXEC_RESERVED = frozenset(" \t\n\"'\\><~|&;$*?#()`")


def autostart_path():
    """User-local autostart entry, read by the session at login."""
    return user_entry()


def desktop_path():
    """User-local application launcher (app grid / menu)."""
    return Path.home() / ".local" / "share" / "applications" / INSTALLED_DESKTOP_NAME


def executable():
    """The `easyspeak` program of this install, for a desktop entry's `Exec`.

    A launcher that wraps EasySpeak, such as the Nix one, names itself in
    `EASYSPEAK_LAUNCHER`, so the entry starts EasySpeak through it, with the
    environment it sets up. Otherwise it is the program next to the running
    interpreter, by its full path, so the desktop finds it where it isn't on the
    session's `PATH`, as in a project's virtual environment run by `uv run`: GLib
    rejects an entry whose program it can't find, and the desktop then neither
    lists EasySpeak nor groups its notifications. Falls back to the bare name where
    there is no such program, e.g. with `python -m`.
    """
    if launcher := os.environ.get("EASYSPEAK_LAUNCHER"):
        return exec_argument(launcher)
    program = Path(sys.executable).with_name("easyspeak")
    return exec_argument(str(program)) if program.is_file() else "easyspeak"


def exec_argument(argument):
    """Write `argument` as a desktop entry's `Exec` value spells it.

    Following the Desktop Entry Specification: a literal `%` is doubled; an
    argument with a reserved character is put in double quotes, with each double
    quote, backtick, dollar sign and backslash in it escaped by a backslash; and the
    value as a whole is escaped as a string, which doubles each backslash again.
    GLib looks for the program before it undoes the doubled `%`, so it still can't
    find one whose path has a `%`.
    """
    argument = argument.replace("%", "%%")
    if any(c in EXEC_RESERVED for c in argument):
        argument = '"' + re.sub(r'(["`$\\])', r"\\\1", argument) + '"'
    return (
        argument.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def entry_text(template):
    """A bundled desktop entry, set to start this install's `easyspeak`."""
    return with_value(data_text(template), "Exec", executable())


def _install_data_file(template, dest):
    """Write a bundled desktop entry into `dest`, best-effort."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(entry_text(template))
    except OSError as e:
        logger.warning("could not write %s (%s)", dest, e)
        return False
    logger.info("installed %s", dest)
    return True


def install_autostart_file():
    """Write the per-user autostart entry so EasySpeak starts at login."""
    return _install_data_file(AUTOSTART_TEMPLATE, autostart_path())


def install_desktop_file():
    """Write the per-user application launcher."""
    return _install_data_file(DESKTOP_TEMPLATE, desktop_path())


def configure(items: set[str]):
    """Run the requested setup activities, then return.

    Each activity in `items` is independent, so callers get exactly what they ask
    for and nothing implicitly. The CLI fills in its own default set, so an empty
    `items` here simply does nothing.
    """
    if "extension" in items:
        activate_extension()
    if "service" in items:
        # install_refresh_unit only reports when it changes something; say so
        # either way, so this item is never silent.
        logger.info(install_refresh_unit() or "refresh service already configured")
    if "desktop" in items:
        install_desktop_file()
    if "autostart" in items:
        install_autostart_file()


def _manifest_text():
    """The GNOME extension's `metadata.json`, its one representative file."""
    return (extension_source_dir() / "metadata.json").read_text()


def preview(item):
    """Write an item's content to stdout and its target install path to stderr.

    Backs `--preview`. The `TARGET:` line goes to stderr so packaging can capture
    just the content off stdout; the content is written verbatim, since adding a
    trailing newline is packaging's concern, not this function's.
    """
    render, path = {
        "extension": (_manifest_text, extension_dest_dir),
        "service": (unit_text, unit_path),
        "desktop": (partial(entry_text, DESKTOP_TEMPLATE), desktop_path),
        "autostart": (partial(entry_text, AUTOSTART_TEMPLATE), autostart_path),
    }[item]
    sys.stderr.write(f"TARGET: {path()}\n")
    sys.stdout.write(render())
