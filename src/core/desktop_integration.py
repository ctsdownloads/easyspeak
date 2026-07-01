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
from importlib import resources
from pathlib import Path

from .gnome_extension import (
    activate_extension,
    extension_source_dir,
    install_refresh_unit,
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


def _data_text(name):
    """Read a bundled data file (package data) as text."""
    return (resources.files("easyspeak.data") / name).read_text()


def _install_data_file(template, dest):
    """Copy a bundled desktop file into `dest`, best-effort."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_data_text(template))
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


def item_text(item):
    """Return the text a configure item creates or uses, for inspection.

    Backs `--preview`, and lets packaging capture e.g. the refresh-service unit as
    rendered for the running interpreter — without installing anything.
    """
    if item == "service":
        return unit_text()
    if item == "autostart":
        return _data_text(AUTOSTART_TEMPLATE)
    if item == "desktop":
        return _data_text(DESKTOP_TEMPLATE)
    # extension: its metadata.json manifest is the one representative file.
    return (extension_source_dir() / "metadata.json").read_text()


def preview(item):
    """Print the item's file content to stdout, with a trailing newline."""
    text = item_text(item)
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
