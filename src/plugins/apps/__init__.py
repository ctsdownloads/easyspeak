"""Apps Plugin - Launch and close applications."""

import logging
import os
from pathlib import Path

from easyspeak.core.i18n import translator
from easyspeak.core.vocabulary import Vocabulary

_ = translator(__file__)
vocab = Vocabulary(__file__)
logger = logging.getLogger(__name__)

NAME = "apps"
DESCRIPTION = "Launch and close applications"

COMMANDS = [
    f"{vocab.say('open')} [app] - " + _("open an application"),
    f"{vocab.say('close', limit=1)} [app] - " + _("close an application"),
    _("Apps: {names}").format(
        names=", ".join(
            vocab.say(app, "apps", limit=1)
            for app in (
                "browser",
                "steam",
                "spotify",
                "calculator",
                "settings",
                "terminal",
            )
        )
    ),
]

# Flatpak apps
FLATPAK_APPS = {
    "firefox": "org.mozilla.firefox",
    "steam": "com.valvesoftware.Steam",
    "spotify": "com.spotify.Client",
    "calculator": "org.gnome.Calculator",
    "settings": "org.gnome.Settings",
}

# Local binary apps
LOCAL_APPS = {
    "alarm": "gnome-clocks",
    "browser": "qutebrowser",
    "calculator": "gnome-calculator",
    "calendar": "gnome-calendar",
    "camera": "snapshot",
    "characters": "gnome-characters",
    "clocks": "gnome-clocks",
    "connections": "gnome-connections",
    "contacts": "gnome-contacts",
    "editor": "gnome-text-editor",
    "epiphany": "epiphany",
    "extensions": "gnome-extensions-app",
    "gimp": "gimp",
    "inkscape": "inkscape",
    "logs": "gnome-logs",
    "maps": "gnome-maps",
    "music app": "gnome-music",
    "music player": "gnome-music",
    "nautilus": "nautilus",
    "radio": "shortwave",
    "scanner": "simple-scan",
    "settings": "gnome-control-center",
    "software": "gnome-software",
    "timer": "gnome-clocks",
    "video player": "showtime",
    "weather": "gnome-weather",
    "web": "epiphany",
}

# KDE Plasma's own apps, preferred there over the GNOME ones above; the first
# one installed wins.
KDE_APPS = {
    "alarm": ["kclock"],
    "calculator": ["kcalc"],
    "calendar": ["merkuro-calendar", "korganizer"],
    "camera": ["kamoso"],
    "characters": ["kcharselect"],
    "clocks": ["kclock"],
    "connections": ["krdc"],
    "contacts": ["merkuro-contact", "kaddressbook"],
    "editor": ["kwrite", "kate"],
    "logs": ["kjournaldbrowser"],
    "maps": ["marble"],
    "music app": ["elisa"],
    "music player": ["elisa"],
    "scanner": ["skanpage"],
    "settings": ["systemsettings"],
    "software": ["plasma-discover"],
    "timer": ["kclock"],
    "video player": ["haruna", "dragon"],
    "weather": ["kweather"],
}

TERMINAL_LAUNCHER = "xdg-terminal-exec"
TERMINAL_FALLBACKS = [
    # GNOME's official terminal (Console) and its aliases / predecessor first
    "kgx",  # GNOME Console (current official terminal) binary name
    "gnome-console",  # alias / package name for the same app
    "gnome-terminal",  # legacy GNOME terminal
    # then GTK / cross-platform terminals commonly used on GNOME, by popularity
    "ghostty",
    "alacritty",
    "kitty",
    "wezterm",
    "tilix",
    "terminator",
    "guake",
    "xterm",  # universal last-resort fallback
]

core = None


def setup(c):
    """Store the core reference and resolve the user's default terminal."""
    global core
    core = c
    _register_terminal(c)


def _has(binary, core):
    """Whether a binary is available in PATH."""
    return core.host_run(["which", binary]).returncode == 0


def _register_terminal(core):
    """Discover the default terminal and register it under the "terminal" key.

    The freedesktop launcher xdg-terminal-exec knows the user's configured default
    terminal but execs into it, so its own name never appears in the process list (which
    would break closing via pkill); ask it which binary it would actually run. If it is
    not installed, fall back to the first known terminal in PATH. When nothing is found
    no entry is added, so "open terminal" falls through to the normal
    unrecognized-command handling rather than trying to launch a missing binary.
    """
    if _has(TERMINAL_LAUNCHER, core):
        result = core.host_run([TERMINAL_LAUNCHER, "--print-cmd"])
        if result.returncode == 0:
            argv = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if _register_from_argv(argv, core):
                return
    terminal = next((t for t in TERMINAL_FALLBACKS if _has(t, core)), None)
    if terminal:
        LOCAL_APPS["terminal"] = terminal


def _register_from_argv(argv, core):
    """Register the terminal described by xdg-terminal-exec's argv output.

    The argv may be prefixed with env-var assignments or an "env" wrapper (both
    skipped). A flatpak terminal is registered by app-id so it launches and
    closes through the flatpak path; a snap terminal is registered by its name,
    which is itself an executable in PATH; a plain binary is registered as-is.

    The resolved target is validated (flatpak app installed, or binary in PATH)
    before registering. A stale or uninstalled default terminal returns False so
    the caller falls back to TERMINAL_FALLBACKS instead of registering a
    "terminal" entry whose launch would raise.
    """
    args = [a for a in argv if "=" not in a and Path(a).name != "env"]
    if not args:
        return False
    command = Path(args[0]).name
    if command in ("flatpak", "snap"):
        target = next(
            (a for a in args[1:] if a != "run" and not a.startswith("-")), None
        )
        if not target:
            return False
        if command == "flatpak":
            if core.host_run(["flatpak", "info", target]).returncode != 0:
                return False
            FLATPAK_APPS["terminal"] = target
        else:  # snap target is itself an executable in PATH
            if not _has(target, core):
                return False
            LOCAL_APPS["terminal"] = target
        return True
    if not _has(args[0], core):
        return False
    LOCAL_APPS["terminal"] = args[0]
    return True


def on_kde():
    """Whether the session is KDE Plasma."""
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")


def find_app(name, core):
    """Find an installed app - returns (type, id), or (None, None) if it's missing."""
    if on_kde():
        kde_app = next((app for app in KDE_APPS.get(name, []) if _has(app, core)), None)
        if kde_app:
            return ("local", kde_app)

    if name in FLATPAK_APPS and _has("flatpak", core):
        result = core.host_run(["flatpak", "info", FLATPAK_APPS[name]])
        if result.returncode == 0:
            return ("flatpak", FLATPAK_APPS[name])

    if name in LOCAL_APPS and _has(LOCAL_APPS[name], core):
        return ("local", LOCAL_APPS[name])

    if _has(name, core):
        return ("local", name)

    return (None, None)


def launch_app(name, core):
    """Launch the named app (flatpak or local binary); False if not found.

    Raises OSError if the app is there but can't be started.
    """
    app_type, app_id = find_app(name, core)
    if app_type == "flatpak":
        core.host_run(["flatpak", "run", app_id], background=True, clean_env=True)
        return True
    if app_type == "local":
        core.host_run([app_id], background=True, clean_env=True)
        return True
    return False


def close_app(name, core):
    """Close the named app (flatpak kill or pkill); False if not found."""
    app_type, app_id = find_app(name, core)
    if app_type == "flatpak":
        core.host_run(["flatpak", "kill", app_id])
        return True
    if app_type == "local":
        core.host_run(["pkill", "-f", app_id])
        return True
    return False


def handle(cmd, core):
    """Open or close an app named in the command; return None if none matched."""
    app = vocab.which(cmd, "apps")
    if app is None or (app not in FLATPAK_APPS and app not in LOCAL_APPS):
        return None

    if vocab.says(cmd, "open"):
        try:
            launched = launch_app(app, core)
        except OSError as exc:
            logger.warning("Couldn't start %s: %s", app, exc)
            core.speak(_("Sorry, I couldn't start {app}.").format(app=app))
            return True

        if launched:
            core.speak(_("Opening {app}.").format(app=app))
        else:
            core.speak(_("{app} not installed.").format(app=app))
        return True

    if vocab.says(cmd, "close"):
        close_app(app, core)
        core.speak(_("Closing {app}.").format(app=app))
        return True

    return None  # Not handled
