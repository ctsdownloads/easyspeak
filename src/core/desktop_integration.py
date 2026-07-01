"""Optional desktop integration for non-packaged (pip / dev) installs.

Debian/RPM packages ship the launcher, autostart entry, and refresh service as
system files, so users there need do nothing. A pip or `uv` install has no such
hooks, so `easyspeak --configure` writes the per-user equivalents under `$HOME`.

The GNOME extension and its refresh service are always set up — they're what
makes the panel/tray icon work — while the launcher and autostart entries are
opt-in, since not everyone wants EasySpeak in their menu or starting at login.
"""

import logging
import sys
from functools import partial
from pathlib import Path

from easyspeak.data import data_text

from .gnome_extension import (
    activate_extension,
    extension_dest_dir,
    extension_source_dir,
    install_refresh_unit,
    unit_path,
    unit_text,
)

logger = logging.getLogger(__name__)

# Bundled desktop files (package data), and the basename they install under. The
# autostart copy keeps the launcher's basename so a per-user file can override a
# packaged /etc/xdg/autostart entry of the same name.
AUTOSTART_TEMPLATE = "easyspeak-autostart.desktop"
DESKTOP_TEMPLATE = "easyspeak.desktop"
INSTALLED_DESKTOP_NAME = "easyspeak.desktop"


def autostart_path():
    """User-local autostart entry, read by the session at login."""
    return Path.home() / ".config" / "autostart" / INSTALLED_DESKTOP_NAME


def desktop_path():
    """User-local application launcher (app grid / menu)."""
    return Path.home() / ".local" / "share" / "applications" / INSTALLED_DESKTOP_NAME


def _install_data_file(template, dest):
    """Copy a bundled desktop file into `dest`, best-effort."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(data_text(template))
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
        "desktop": (partial(data_text, DESKTOP_TEMPLATE), desktop_path),
        "autostart": (partial(data_text, AUTOSTART_TEMPLATE), autostart_path),
    }[item]
    sys.stderr.write(f"TARGET: {path()}\n")
    sys.stdout.write(render())
