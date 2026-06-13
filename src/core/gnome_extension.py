"""Install, refresh, and enable the bundled GNOME Shell extension.

Core owns the extension's lifecycle because both the mousegrid plugin and
``core.tray`` drive it over D-Bus; :func:`ensure_extension` runs once at startup.
The extension ships as package data — ``extension.js``, the
``extension-helpers.js`` it imports, and ``metadata.json`` — copied into the
user's extensions dir as a set. On Wayland GNOME only loads extension code at
login, so the startup copy is always one login behind; a ``oneshot`` systemd
*user* unit ordered before the shell re-copies it at the start of every login to
close that gap. The unit runs as the user, writes only to ``$HOME``, and needs
no privileges.
"""

import contextlib
import enum
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

GRID_EXTENSION_UUID = "easyspeak-grid@local"
REFRESH_UNIT_NAME = "easyspeak-extension-refresh.service"
PRE_SHELL_TARGET = "gnome-session-pre.target"  # reached before org.gnome.Shell@*

# Cap each helper subprocess so a wedged session/user bus can't hang startup.
SUBPROCESS_TIMEOUT = 5.0

# Bundled assets, installed as a set: extension.js imports extension-helpers.js,
# so they must travel together or the extension fails to load.
EXTENSION_ASSETS = ("extension.js", "extension-helpers.js", "metadata.json")


class RefreshResult(enum.Enum):
    REFRESHED = "refreshed"
    UNCHANGED = "unchanged"
    ERROR = "error"


def extension_source_dir():
    """Package dir holding the bundled assets (``src/``), resolved relative to
    this module so it works in both editable and wheel installs."""
    return Path(__file__).resolve().parents[1]


def extension_dest_dir():
    """User-local install location GNOME Shell reads extensions from."""
    return (
        Path.home()
        / ".local"
        / "share"
        / "gnome-shell"
        / "extensions"
        / GRID_EXTENSION_UUID
    )


def _staged_tmp(dest_dir, name):
    return dest_dir / f".{name}.tmp"


def _discard_staged(dest_dir):
    """Remove any ``.<asset>.tmp`` files a previous refresh may have left."""
    for name in EXTENSION_ASSETS:
        with contextlib.suppress(OSError):
            _staged_tmp(dest_dir, name).unlink()


def refresh_extension_files(src_dir, dest_dir):
    """Copy the bundled assets into ``dest_dir`` when they differ from the
    installed copy. Best-effort: returns ``REFRESHED`` if written, ``UNCHANGED``
    if already current, or ``ERROR`` (noted on stderr) when a source is missing
    or a copy fails. Assets are staged then moved into place (extension.js last),
    so a failure leaves any working install untouched and never installs
    extension.js without the helper it imports."""
    srcs = {name: src_dir / name for name in EXTENSION_ASSETS}
    if not all(s.is_file() for s in srcs.values()):
        print(
            f"easyspeak: note: bundled GNOME extension sources missing at {src_dir}",
            file=sys.stderr,
        )
        return RefreshResult.ERROR
    # Clear temps an interrupted run may have left, so the dir self-heals even on
    # the UNCHANGED path below.
    _discard_staged(dest_dir)
    try:
        unchanged = all(
            (dest_dir / name).is_file()
            and filecmp.cmp(src, dest_dir / name, shallow=False)
            for name, src in srcs.items()
        )
        if unchanged:
            return RefreshResult.UNCHANGED
        dest_dir.mkdir(parents=True, exist_ok=True)
        staged = []
        for name, src in srcs.items():
            tmp = _staged_tmp(dest_dir, name)
            shutil.copy2(src, tmp)
            staged.append((tmp, dest_dir / name))
        for tmp, dest in reversed(staged):  # extension.js leads EXTENSION_ASSETS
            tmp.replace(dest)
        return RefreshResult.REFRESHED
    except OSError as e:
        _discard_staged(dest_dir)
        print(
            f"easyspeak: note: could not write GNOME extension to {dest_dir} ({e})",
            file=sys.stderr,
        )
        return RefreshResult.ERROR


def refresh_installed_extension():
    """Refresh the installed extension from the bundled copy; run by the systemd
    unit at each login."""
    return refresh_extension_files(extension_source_dir(), extension_dest_dir())


def _unit_path():
    return Path.home() / ".config" / "systemd" / "user" / REFRESH_UNIT_NAME


def _unit_text():
    """Render the systemd user unit, baking in the interpreter and module path."""
    python = sys.executable
    script = Path(__file__).resolve()
    return f"""\
[Unit]
Description=Refresh the EasySpeak GNOME Shell extension before GNOME Shell loads it
# Runs before the shell reads the extensions dir so a changed extension.js takes
# effect on this login, not the next (on Wayland the shell only loads extensions
# at login). Missing shell units are ignored.
Before={PRE_SHELL_TARGET}
Before=org.gnome.Shell@user.service
Before=org.gnome.Shell@wayland.service
Before=org.gnome.Shell@x11.service

[Service]
Type=oneshot
# Quoted: systemd splits ExecStart on whitespace.
ExecStart="{python}" "{script}"

[Install]
WantedBy={PRE_SHELL_TARGET}
"""


def _run_systemctl(*args):
    """Run a ``systemctl --user`` command, or return None if it can't be exec'd —
    an un-execable systemctl raises OSError despite ``check=False``, and the
    refresh-unit install must stay non-fatal."""
    try:
        return subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _is_enabled():
    result = _run_systemctl("is-enabled", REFRESH_UNIT_NAME)
    return (
        result is not None
        and result.returncode == 0
        and result.stdout.strip() == "enabled"
    )


def install_refresh_unit():
    """Install and enable the pre-shell refresh unit, returning a short status
    string or None when nothing changed or it isn't applicable (no systemd,
    write/enable failure). Idempotent."""
    if shutil.which("systemctl") is None:
        return None

    unit_path = _unit_path()
    desired = _unit_text()
    try:
        current = unit_path.read_text() if unit_path.is_file() else None
    except OSError:
        current = None

    changed = current != desired
    if changed:
        try:
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(desired)
        except OSError:
            return None
        _run_systemctl("daemon-reload")
    elif _is_enabled():
        return None

    enabled = _run_systemctl("enable", REFRESH_UNIT_NAME)
    if enabled is None or enabled.returncode != 0:
        return None
    return (
        f"{'installed' if changed else 'enabled'} systemd user unit {REFRESH_UNIT_NAME}"
    )


def ensure_extension():
    """Install the bundled extension if missing, keep the installed copy current,
    and enable it, reporting what it did. Skipped on non-GNOME desktops; non-fatal
    on missing sources or write failures."""
    if shutil.which("gnome-extensions") is None:
        return

    unit_status = install_refresh_unit()
    if unit_status:
        print(f"easyspeak: {unit_status}", file=sys.stderr)

    try:
        listed = subprocess.run(
            ["gnome-extensions", "list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT,
        )
        listed_enabled = subprocess.run(
            ["gnome-extensions", "list", "--enabled"],
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if listed.returncode != 0:
        return

    installed = GRID_EXTENSION_UUID in listed.stdout.split()
    # A failed --enabled probe leaves this False, so we fall through and try
    # enabling (a no-op when it's already on).
    already_enabled = (
        listed_enabled.returncode == 0
        and GRID_EXTENSION_UUID in listed_enabled.stdout.split()
    )
    dest_dir = extension_dest_dir()
    root = extension_source_dir()

    if installed and already_enabled:
        result = refresh_extension_files(root, dest_dir)
        if result is RefreshResult.REFRESHED:
            print(
                f"easyspeak: updated GNOME extension {GRID_EXTENSION_UUID} to "
                f"the bundled version — log out and back in to load it",
                file=sys.stderr,
            )
        elif result is RefreshResult.UNCHANGED:
            print(
                f"easyspeak: GNOME extension {GRID_EXTENSION_UUID} "
                f"already installed and enabled",
                file=sys.stderr,
            )
        # ERROR was already noted by refresh_extension_files; stay quiet rather
        # than claim a healthy install.
        return

    if not installed:
        if not all((root / name).is_file() for name in EXTENSION_ASSETS):
            print(
                f"easyspeak: note: could not auto-install GNOME extension — "
                f"source files not found at {root}. The panel indicator and "
                f"grid commands will not work until the extension is installed "
                f"manually.",
                file=sys.stderr,
            )
            return

        if refresh_extension_files(root, dest_dir) is RefreshResult.ERROR:
            # refresh_extension_files already reported the write error (with the
            # OSError detail) on stderr; add only the consequence, not a second
            # description of the same failure.
            print(
                "easyspeak: note: the panel indicator and grid commands will "
                "not work until the GNOME extension is installed manually.",
                file=sys.stderr,
            )
            return

    # On Wayland GNOME only rescans at login, so enable fails with "Unknown
    # extension" until then — treated as "installed, log back in to use".
    try:
        enabled = subprocess.run(
            ["gnome-extensions", "enable", GRID_EXTENSION_UUID],
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT,
        )
        ok = enabled.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False

    if installed:
        if ok:
            print(
                f"easyspeak: enabled GNOME extension {GRID_EXTENSION_UUID} "
                f"(was installed but disabled)",
                file=sys.stderr,
            )
        else:
            print(
                f"easyspeak: note: GNOME extension {GRID_EXTENSION_UUID} is "
                f"installed but disabled, and could not be enabled. Try: "
                f"gnome-extensions enable {GRID_EXTENSION_UUID}",
                file=sys.stderr,
            )
        return

    if ok:
        print(
            f"easyspeak: installed and enabled GNOME extension "
            f"{GRID_EXTENSION_UUID} at {dest_dir}",
            file=sys.stderr,
        )
    else:
        print(
            f"easyspeak: installed GNOME extension to {dest_dir} — "
            f"log out and back in to finish enabling it.",
            file=sys.stderr,
        )


def main():
    refresh_installed_extension()
    return 0


if __name__ == "__main__":
    sys.exit(main())
