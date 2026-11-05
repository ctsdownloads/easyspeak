"""The one-shot control file through which EasySpeak is handed commands.

The tray menu (the GNOME Shell extension or the StatusNotifierItem helper) and a
second launch of EasySpeak write a single command into it; the running daemon's
[`Tray`][core.tray.Tray] reads and deletes it. Only the standard library is used
here, so a second launch can write its request without loading the speech stack.
"""

from pathlib import Path

# Shared with the extension's ScreenshotManager, which creates ~/.cache/easyspeak.
CONTROL_FILE = Path.home() / ".cache" / "easyspeak" / "control"

# Menu commands the extension writes into the control file for the daemon.
COMMAND_QUIT = "quit"
COMMAND_MUTE = "mute"
COMMAND_UNMUTE = "unmute"
COMMAND_HELP = "help"  # open the documentation page in the default browser
COMMAND_ABOUT = "about"  # open the libadwaita About dialog
# Written by a second launch of EasySpeak (see core.instance), with or without -v.
COMMAND_PRESENT = "present"
COMMAND_PRESENT_VERBOSE = "present verbose"
