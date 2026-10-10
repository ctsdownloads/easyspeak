"""Whether EasySpeak starts at login, and the switch to change that.

Follows the freedesktop autostart specification: the packages install a
system-wide entry, and a user overrides it with their own copy of the same name,
marked `Hidden=true` to turn it off. `X-GNOME-Autostart-enabled` is kept in step,
as GNOME's own settings and the GNOME extension's settings read that key. This is
the tray menu's "Start at Login" on desktops other than GNOME; the extension's
settings do the same in JavaScript.
"""

import os
import re
from pathlib import Path

from easyspeak.data import data_text

ENTRY_NAME = "easyspeak.desktop"
TEMPLATE = "easyspeak-autostart.desktop"


def user_entry():
    """The user's own autostart entry, which overrides the system-wide one.

    It lives in the XDG user config directory, `~/.config` unless
    `XDG_CONFIG_HOME` says otherwise, where the desktop looks for it too.
    """
    config = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config) / "autostart" / ENTRY_NAME


def system_entries():
    """Where packages put the system-wide autostart entry, most important first."""
    dirs = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    return [Path(d) / "autostart" / ENTRY_NAME for d in dirs.split(":") if d]


def read(path):
    """Return a file's text, or None if it's missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def value(text, key):
    """Return a key's value in a desktop entry, or None if it's not set."""
    match = re.search(rf"^{re.escape(key)}\s*=\s*(\S+)", text, re.MULTILINE)
    return match.group(1).lower() if match else None


def enabled_in(text):
    """Whether a desktop entry says to start at login."""
    return value(text, "Hidden") != "true" and (
        value(text, "X-GNOME-Autostart-enabled") != "false"
    )


def with_value(text, key, new):
    """Return a desktop entry with `key` set to `new`, appended if it was missing."""
    line = f"{key}={new}"
    pattern = rf"^{re.escape(key)}\s*=.*$"
    if re.search(pattern, text, re.MULTILINE):
        return re.sub(pattern, line, text, flags=re.MULTILINE)
    return (text if text.endswith("\n") else text + "\n") + line + "\n"


def is_enabled():
    """Whether EasySpeak starts at login: the user's entry decides, else the system's.

    With neither, nothing starts it, e.g. after a pip install without
    `easyspeak --configure autostart`.
    """
    for path in (user_entry(), *system_entries()):
        text = read(path)
        if text is not None:
            return enabled_in(text)
    return False


def set_enabled(enabled):
    """Turn starting at login on or off, through the user's own entry.

    The entry is based on the user's existing one, so hand edits survive, else
    on the system-wide one, else on the template EasySpeak ships.
    """
    sources = (read(path) for path in (user_entry(), *system_entries()))
    text = next((t for t in sources if t is not None), None) or data_text(TEMPLATE)
    flag = "true" if enabled else "false"
    text = with_value(text, "Hidden", "false" if enabled else "true")
    text = with_value(text, "X-GNOME-Autostart-enabled", flag)
    entry = user_entry()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(text, encoding="utf-8")
