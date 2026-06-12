"""Install, refresh, and enable the bundled GNOME Shell extension.

The extension is core infrastructure, not a single plugin's concern: the
mousegrid plugin drives it for pointer control, while ``core.tray`` drives the
same extension for the panel indicator (``SetState`` over D-Bus). Core therefore
owns its lifecycle — installing it, keeping the installed copy current, and
enabling it — and calls :func:`ensure_extension` once at startup.

The extension ships as package data inside the ``easyspeak`` package
(``extension.js`` + ``metadata.json``) and is copied into the user's extension
directory. GNOME only auto-installs on first run and, on Wayland, only loads
extension code at login — it never reloads a changed file in a running session.
Core's startup refresh runs *after* the
shell has already read the extensions directory, so on its own it is always one
login behind. To close that gap we also install a tiny ``oneshot`` systemd
*user* unit ordered *before* the shell (via ``gnome-session-pre.target``) that
re-copies the bundled extension at the start of every login. The unit runs as
the user and only writes to the user's home; it never runs on the GDM greeter
(a separate ``gdm`` user with its own shell) and needs no elevated privileges.
"""

import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

GRID_EXTENSION_UUID = "easyspeak-grid@local"

# systemd user unit that refreshes the extension before the shell loads it.
REFRESH_UNIT_NAME = "easyspeak-extension-refresh.service"
# Target reached early in the GNOME session, before org.gnome.Shell@*.service.
PRE_SHELL_TARGET = "gnome-session-pre.target"


def extension_source_dir():
    """Directory holding the bundled extension.js / metadata.json.

    The assets are package data inside the ``easyspeak`` package, so they live
    in ``src/`` — one level up from this module at ``src/core`` — which becomes
    ``site-packages/easyspeak/`` in an installed wheel. Resolving relative to
    the package (not the repo root) makes them findable in both editable and
    wheel installs.
    """
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


def refresh_extension_files(src_ext, src_meta, dest_dir):
    """Copy the bundled extension into ``dest_dir`` if it differs from the
    installed copy. Returns True if anything was written.

    GNOME only auto-installs on first run, so without this an installed copy
    from an older version lingers forever and improvements to extension.js
    (e.g. the tray indicator) never reach the user. Best-effort: a missing
    source or a write failure returns False rather than disturbing a working
    install.
    """
    if not (src_ext.is_file() and src_meta.is_file()):
        return False
    dest_ext = dest_dir / "extension.js"
    dest_meta = dest_dir / "metadata.json"
    try:
        unchanged = (
            dest_ext.is_file()
            and dest_meta.is_file()
            and filecmp.cmp(src_ext, dest_ext, shallow=False)
            and filecmp.cmp(src_meta, dest_meta, shallow=False)
        )
        if unchanged:
            return False
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_ext, dest_ext)
        shutil.copy2(src_meta, dest_meta)
        return True
    except OSError:
        return False


def refresh_installed_extension():
    """Refresh the installed extension from the bundled package-data copy.

    Path-resolving wrapper around :func:`refresh_extension_files`; this is what
    the systemd unit runs at the start of each login.
    """
    root = extension_source_dir()
    return refresh_extension_files(
        root / "extension.js",
        root / "metadata.json",
        extension_dest_dir(),
    )


def _unit_path():
    return Path.home() / ".config" / "systemd" / "user" / REFRESH_UNIT_NAME


def _unit_text():
    """Render the systemd user unit, baking in the current interpreter and the
    absolute path of this module so the oneshot runs identically at login."""
    python = sys.executable
    script = Path(__file__).resolve()
    return f"""\
[Unit]
Description=Refresh the EasySpeak GNOME Shell extension before GNOME Shell loads it
# Bring the installed copy of the bundled extension up to date *before* the
# shell reads the extensions directory, so a changed extension.js takes effect
# on this login instead of the next one. On Wayland the shell only loads
# extension code at login and never reloads it, so the startup refresh (which
# runs after login) is always one login behind. Running here closes that gap.
# Listed shell units that don't exist on a given session are ignored.
Before={PRE_SHELL_TARGET}
Before=org.gnome.Shell@user.service org.gnome.Shell@wayland.service org.gnome.Shell@x11.service

[Service]
Type=oneshot
# Quote both arguments: systemd splits ExecStart on whitespace, so an
# interpreter or module path containing spaces would otherwise break the unit.
ExecStart="{python}" "{script}"

[Install]
WantedBy={PRE_SHELL_TARGET}
"""


def _run_systemctl(*args):
    """Run a ``systemctl --user`` command, returning the CompletedProcess or
    None if it could not be executed.

    ``check=False`` already keeps non-zero exits from raising, but an
    un-execable systemctl (vanished after the initial ``which`` probe, a PATH
    race, an exec failure) still raises OSError. Swallowing it here keeps the
    refresh-unit install best-effort and non-fatal, so it can never abort
    startup from :func:`ensure_extension`.
    """
    try:
        return subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None


def _is_enabled():
    result = _run_systemctl("is-enabled", REFRESH_UNIT_NAME)
    return (
        result is not None
        and result.returncode == 0
        and result.stdout.strip() == "enabled"
    )


def install_refresh_unit():
    """Install and enable the pre-shell refresh unit. Returns a short status
    string describing what changed, or None when there was nothing to do or the
    operation is not applicable (no systemd, write/enable failure).

    Idempotent: rewrites the unit only when its rendered content changed, and
    only runs ``enable`` when the unit is new/changed or not yet enabled.
    """
    if shutil.which("systemctl") is None:
        return None  # not a systemd session

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
        return None  # already installed, current, and enabled

    enabled = _run_systemctl("enable", REFRESH_UNIT_NAME)
    if enabled is None or enabled.returncode != 0:
        return None
    return (
        f"{'installed' if changed else 'enabled'} systemd user unit {REFRESH_UNIT_NAME}"
    )


def ensure_extension():
    """Install the GNOME Shell extension if needed, enable it, and keep it
    current.

    Installs/enables the pre-shell refresh unit, then probes state with
    ``gnome-extensions list`` (covers both system and user paths) and
    ``gnome-extensions list --enabled``, reporting exactly what it did: found it
    already enabled, refreshed a changed bundle, enabled a previously disabled
    install (e.g. the user toggled it off or a GNOME Shell version bump
    auto-disabled it), or freshly installed and enabled. Silently skipped on
    non-GNOME systems. Non-fatal on missing source files or write failures —
    emits a polite note and lets startup proceed.
    """
    if shutil.which("gnome-extensions") is None:
        return  # not a GNOME-based desktop

    # Install/enable the systemd user unit that refreshes the bundled extension
    # before GNOME Shell loads it at login, so a changed extension.js takes
    # effect on the next login rather than the one after (the refresh below runs
    # after the shell has already read the extensions directory).
    unit_status = install_refresh_unit()
    if unit_status:
        print(f"easyspeak: {unit_status}", file=sys.stderr)

    try:
        listed = subprocess.run(
            ["gnome-extensions", "list"],
            capture_output=True,
            text=True,
            check=False,
        )
        listed_enabled = subprocess.run(
            ["gnome-extensions", "list", "--enabled"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return
    if listed.returncode != 0:
        return

    installed = GRID_EXTENSION_UUID in listed.stdout.split()
    # If the --enabled probe failed we don't know; fall through and try
    # enabling (a no-op when it's already on).
    already_enabled = (
        listed_enabled.returncode == 0
        and GRID_EXTENSION_UUID in listed_enabled.stdout.split()
    )
    dest_dir = extension_dest_dir()

    root = extension_source_dir()
    src_ext = root / "extension.js"
    src_meta = root / "metadata.json"

    if installed and already_enabled:
        # Steady state — but still refresh the on-disk copy if the bundled
        # extension changed since it was installed (GNOME only copies on first
        # run). The refreshed code loads at the next login on Wayland.
        if refresh_extension_files(src_ext, src_meta, dest_dir):
            print(
                f"easyspeak: updated GNOME extension {GRID_EXTENSION_UUID} to "
                f"the bundled version — log out and back in to load it",
                file=sys.stderr,
            )
        else:
            print(
                f"easyspeak: GNOME extension {GRID_EXTENSION_UUID} "
                f"already installed and enabled",
                file=sys.stderr,
            )
        return

    if not installed:
        if not (src_ext.is_file() and src_meta.is_file()):
            print(
                f"easyspeak: note: could not auto-install GNOME extension — "
                f"source files not found at {root}. The panel indicator and "
                f"grid commands will not work until the extension is installed "
                f"manually.",
                file=sys.stderr,
            )
            return

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_ext, dest_dir / "extension.js")
            shutil.copy2(src_meta, dest_dir / "metadata.json")
        except OSError as e:
            print(
                f"easyspeak: note: could not install GNOME extension to "
                f"{dest_dir} ({e}). The panel indicator and grid commands will "
                f"not work until it is installed manually.",
                file=sys.stderr,
            )
            return

    # First-time installs require GNOME Shell to rescan, which on Wayland
    # only happens at login. `enable` will fail with "Unknown extension"
    # until then — we treat that as "installed, log back in to use".
    try:
        enabled = subprocess.run(
            ["gnome-extensions", "enable", GRID_EXTENSION_UUID],
            capture_output=True,
            text=True,
            check=False,
        )
        ok = enabled.returncode == 0
    except OSError:
        ok = False

    if installed:
        # Was installed but disabled — we just flipped it on (or tried to).
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
