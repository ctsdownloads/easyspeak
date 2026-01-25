"""
Files Plugin - Open folders in file manager
"""

import os

NAME = "files"
DESCRIPTION = "Folder navigation"

COMMANDS = [
    "open [folder] - open folder in file manager",
    "Folders: documents, downloads, pictures, music, videos, home, desktop",
]

FOLDERS = {
    "documents": "~/Documents",
    "downloads": "~/Downloads",
    "pictures": "~/Pictures",
    "music": "~/Music",
    "videos": "~/Videos",
    "home": "~",
    "desktop": "~/Desktop",
}

core = None


def setup(c):
    global core
    core = c


def open_folder(path, core):
    """Open folder in file manager"""
    expanded = os.path.expanduser(path)

    file_managers = [
        ("nautilus", [expanded]),
        ("dolphin", [expanded]),
        ("thunar", [expanded]),
        ("nemo", [expanded]),
        ("xdg-open", [expanded]),
    ]

    for fm, args in file_managers:
        result = core.host_run(["which", fm])
        if result.returncode == 0:
            core.host_run([fm] + args, background=True)
            return True
    return False


def handle(cmd, core):
    for folder, path in FOLDERS.items():
        if folder in cmd and (
            "open" in cmd or "go to" in cmd or "show" in cmd or "browse" in cmd
        ):
            if open_folder(path, core):
                core.speak(f"Opening {folder}.")
            else:
                core.speak("No file manager found.")
            return True

    return None  # Not handled
