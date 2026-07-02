"""Files Plugin - Open folders in file manager."""

from pathlib import Path

NAME = "files"
DESCRIPTION = "Folder navigation"

COMMANDS = [
    "open [folder] - open a folder in your default file manager",
    "open files / file manager - open your default file manager",
    "Folders: documents, downloads, pictures, music, videos, projects, home, desktop",
]

OPEN_VERBS = ("open", "go to", "show", "browse")
FILE_MANAGER_PHRASES = ("file manager", "file browser", "files")

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
    if not any(verb in cmd for verb in OPEN_VERBS):
        return None

    for folder, path in FOLDERS.items():
        if folder in cmd:
            _open(path, folder, core)
            return True

    if any(phrase in cmd for phrase in FILE_MANAGER_PHRASES):
        _open("~", "files", core)
        return True

    return None  # Not handled


def _open(path, label, core):
    """Open path in the file manager and announce it, or report none is found."""
    if open_folder(path, core):
        core.speak(f"Opening {label}.")
    else:
        core.speak("No file manager found.")
