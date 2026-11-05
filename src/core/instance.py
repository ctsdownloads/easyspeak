"""One EasySpeak per desktop session.

Starting EasySpeak while it already runs, e.g. from the application menu after it
started at login, would have two copies compete for the microphone. So, the first
copy holds a lock for as long as it runs. A later one asks it to come forward,
through the control file the tray menu also writes to, and quits.
"""

import fcntl
import os
from pathlib import Path

from .control import COMMAND_PRESENT, COMMAND_PRESENT_VERBOSE, CONTROL_FILE

LOCK_FILE = (
    Path(os.environ.get("XDG_RUNTIME_DIR") or CONTROL_FILE.parent) / "easyspeak.lock"
)


def acquire():
    """Take the lock for this copy: the open lock file, or None if one runs already.

    The lock lasts while the file is open, so keep the returned file. The system
    releases it when the process ends, even when it crashes.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK_FILE.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def present(verbose=False):
    """Ask the running copy to come forward and greet, with details if `verbose`.

    The request is written beside the control file and then renamed onto it, so
    the running copy never reads a half-written, empty request and discards it.
    """
    CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
    request = CONTROL_FILE.with_name(f".{CONTROL_FILE.name}.{os.getpid()}")
    request.write_text(COMMAND_PRESENT_VERBOSE if verbose else COMMAND_PRESENT)
    request.replace(CONTROL_FILE)
