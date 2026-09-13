"""Files Plugin - Open folders in file manager."""

import os
from pathlib import Path

from easyspeak.core.i18n import translator
from easyspeak.core.vocabulary import Vocabulary

_ = translator(__file__)
vocab = Vocabulary(__file__)

NAME = "files"
DESCRIPTION = "Folder navigation"

COMMANDS = [
    f"{vocab.say('open', limit=1)} [folder] - "
    + _("open a folder in your default file manager"),
    f"{vocab.say('open', limit=1)} {vocab.say('file_manager')} - "
    + _("open your default file manager"),
    f"{vocab.say('close', limit=1)} {vocab.say('file_manager', limit=1)} - "
    + _("close your default file manager"),
    _("Folders: {names}").format(
        names=", ".join(
            vocab.say(folder, "folders", limit=1) for folder in vocab.keys("folders")
        )
    ),
]

FOLDERS = {
    "documents": "~/Documents",
    "downloads": "~/Downloads",
    "pictures": "~/Pictures",
    "music": "~/Music",
    "videos": "~/Videos",
    "projects": "~/Projects",
    "home": "~",
    "desktop": "~/Desktop",
}

core = None


def setup(c):
    """Store the core reference for use by the plugin's handlers."""
    global core
    core = c


def open_folder(path, core):
    """Open a folder in the user's default file manager; False if unavailable.

    Delegates to xdg-open so whichever file manager the desktop is configured
    for is honoured, rather than hardcoding one. Launched with a clean
    environment (see core.host_run) so it doesn't inherit EasySpeak's library
    paths.
    """
    expanded = Path(path).expanduser()
    if core.host_run(["which", "xdg-open"]).returncode != 0:
        return False
    core.host_run(["xdg-open", expanded], background=True, clean_env=True)
    return True


def default_file_manager(core):
    """Return the process name of the configured default file manager, or None.

    The same manager `xdg-open` opens folders with: `xdg-mime` names its desktop
    entry, and the entry's Exec line names the program, which is what `pkill`
    matches. A Flatpak's Exec runs `flatpak`, so its app id is taken instead,
    which is how the process list shows it.
    """
    query = core.host_run(["xdg-mime", "query", "default", "inode/directory"])
    entry = query.stdout.strip() if query.returncode == 0 else ""
    if not entry:
        return None
    data_home = os.environ.get("XDG_DATA_HOME") or str(
        Path("~/.local/share").expanduser()
    )
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for directory in [data_home, *data_dirs.split(":")]:
        desktop = Path(directory) / "applications" / entry
        if not desktop.is_file():
            continue
        for line in desktop.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Exec="):
                words = line[len("Exec=") :].split()
                if not words:
                    return None
                program = Path(words[0]).name
                if program != "flatpak":
                    return program
                return next(
                    (w for w in words[1:] if "." in w and not w.startswith("-")), None
                )
    return None


def close_file_manager(core):
    """Close the configured default file manager; False if none can be named."""
    program = default_file_manager(core)
    if program is None:
        return False
    core.host_run(["pkill", "-f", program])
    return True


def handle(cmd, core):
    """Open a named folder or the file manager, or close the file manager.

    None if neither matched.
    """
    if vocab.says(cmd, "close") and vocab.says(cmd, "file_manager"):
        if close_file_manager(core):
            core.speak(_("Closing the file manager."))
        else:
            core.speak(_("No file manager found."))
        return True

    if not vocab.says(cmd, "open"):
        return None

    folder = vocab.which(cmd, "folders")
    if folder in FOLDERS:
        _open(FOLDERS[folder], folder, core)
        return True

    if vocab.says(cmd, "file_manager"):
        _open("~", "files", core)
        return True

    return None  # Not handled


def _open(path, label, core):
    """Open path in the file manager and announce it, or report none is found."""
    if open_folder(path, core):
        core.speak(_("Opening {label}.").format(label=label))
    else:
        core.speak(_("No file manager found."))
