"""Files Plugin - Open folders in file manager."""

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


def handle(cmd, core):
    """Open a named folder, or the file manager itself; None if neither matched."""
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
