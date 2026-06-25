"""Install, refresh, and enable the bundled GNOME Shell extension.

Core owns the extension's lifecycle because both the mousegrid plugin and `core.tray`
drive it over D-Bus; [`ensure_extension`][core.gnome_extension.ensure_extension] runs
once at startup. The extension ships as package data — `extension.js`, the
`extension-helpers.js` it imports, and `metadata.json` — copied into the user's
extensions dir as a set. On Wayland GNOME only loads extension code at login, so the
startup copy is always one login behind; [a `oneshot` systemd user unit][systemd]
ordered before the shell re-copies it at the start of every login to close that gap. The
unit runs as the user, writes only to `$HOME`, and needs no privileges.

[systemd]: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
"""

import contextlib
import enum
import filecmp
import logging
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

logger = logging.getLogger(__name__)

EXTENSION_UUID = "easyspeak@local"
# Pre-rename UUID (the extension was "easyspeak-grid@local" when it was just a
# mouse grid). A leftover copy is cleaned up at startup; see migrate_legacy_extension.
LEGACY_EXTENSION_UUID = "easyspeak-grid@local"
REFRESH_UNIT_NAME = "easyspeak-extension-refresh.service"
REFRESH_UNIT_TEMPLATE = REFRESH_UNIT_NAME + ".in"  # packaged template file
PRE_SHELL_TARGET = "gnome-session-pre.target"  # reached before org.gnome.Shell@*

# Cap each helper subprocess so a wedged session/user bus can't hang startup.
SUBPROCESS_TIMEOUT = 5.0

# Bundled assets, installed as a set: extension.js imports extension-helpers.js,
# so they must travel together or the extension fails to load.
EXTENSION_ASSETS = ("extension.js", "extension-helpers.js", "metadata.json")


class RefreshResult(enum.Enum):
    """Outcome of a single refresh attempt.

    See [`refresh_extension_files`][core.gnome_extension.refresh_extension_files].
    """

    REFRESHED = "refreshed"
    UNCHANGED = "unchanged"
    ERROR = "error"


def extension_source_dir():
    """Return the package dir holding the bundled assets.

    Resolved relative to this module (`src/`) so it works in both editable and wheel
    installs.
    """
    return Path(__file__).resolve().parents[1]


def extensions_root():
    """User-local directory GNOME Shell reads installed extensions from."""
    return Path.home() / ".local" / "share" / "gnome-shell" / "extensions"


def extension_dest_dir():
    """User-local install location for the bundled extension."""
    return extensions_root() / EXTENSION_UUID


def _staged_tmp(dest_dir, name):
    return dest_dir / f".{name}.tmp"


def _discard_staged(dest_dir):
    """Remove any `.<asset>.tmp` files a previous refresh may have left."""
    for name in EXTENSION_ASSETS:
        with contextlib.suppress(OSError):
            _staged_tmp(dest_dir, name).unlink()


def refresh_extension_files(src_dir, dest_dir):
    """Copy the bundled assets into `dest_dir` when they differ from it.

    Best-effort: returns `REFRESHED` if written, `UNCHANGED` if already
    current, or `ERROR` (noted on stderr) when a source is missing or a copy
    fails. Assets are staged then moved into place (extension.js last), so a
    failure leaves any working install untouched and never installs extension.js
    without the helper it imports.
    """
    srcs = {name: src_dir / name for name in EXTENSION_ASSETS}
    if not all(s.is_file() for s in srcs.values()):
        logger.warning("bundled GNOME extension sources missing at %s", src_dir)
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
        logger.warning("could not write GNOME extension to %s (%s)", dest_dir, e)
        return RefreshResult.ERROR


def refresh_installed_extension():
    """Refresh the installed extension from the bundled copy.

    Run by the systemd user unit at each login.
    """
    return refresh_extension_files(extension_source_dir(), extension_dest_dir())


def _unit_path():
    return Path.home() / ".config" / "systemd" / "user" / REFRESH_UNIT_NAME


def _is_ephemeral_interpreter(executable):
    """True when `executable` lives in a uv ephemeral build env.

    uv builds an ephemeral interpreter under its build cache (…/uv/builds-*/…)
    for each `uv run` / `nix run`, then garbage-collects it, so a unit pointing
    at it fails `203/EXEC` at every login; see `_stable_interpreter`. Packaged
    installs (Debian/RPM system python, a real venv) never live here, so this
    marker only ever matches the dev/`nix run` path.
    """
    return "/uv/builds-" in str(executable)


def _stable_interpreter():
    """Return a persistent interpreter path to bake into the login unit.

    `sys.executable` is fine for packaged installs but can point into a uv
    ephemeral build env under `uv run` / `nix run`. When it does, fall back to
    the base interpreter that env was built from (`sys._base_executable`, else
    the symlink target) — it persists, and the refresh entry point imports only
    the stdlib so a bare base interpreter runs it. Resolving deterministically
    keeps the rendered unit byte-stable, so re-running converges instead of
    flapping (and a unit left pointing at a vanished interpreter self-heals on
    the next start).
    """
    if not _is_ephemeral_interpreter(sys.executable):
        return sys.executable
    base = getattr(sys, "_base_executable", None)
    if base and not _is_ephemeral_interpreter(base):
        return base
    return str(Path(sys.executable).resolve())


def unit_text():
    """Render the systemd user unit, baking in the interpreter and module path.

    The unit body lives in a template shipped as package data (`easyspeak.data`)
    so it reads as a service file, not a Python string. A missing template is a
    broken install, so let the read error surface rather than masking it.

    Two non-obvious choices in the rendered unit: it's ordered before
    `gnome-session-pre.target` and the `org.gnome.Shell@*` services (missing ones
    are ignored) so a changed extension takes effect on this login, not the next
    — on Wayland the shell only loads extensions at login. And both ExecStart
    arguments are quoted, since systemd splits ExecStart on whitespace.
    """
    template = (resources.files("easyspeak.data") / REFRESH_UNIT_TEMPLATE).read_text()
    return template.format(
        target=PRE_SHELL_TARGET,
        python=_stable_interpreter(),
        script=Path(__file__).resolve(),
    )


def _run_systemctl(*args):
    """Run a `systemctl --user` command, or return None if it can't be run.

    An un-execable systemctl raises OSError despite `check=False`, and the refresh-unit
    install must stay non-fatal.
    """
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


def _system_unit_exists():
    """True when a packaged install provides the refresh unit system-wide.

    A packaged (Debian/RPM) install drops the unit in one of systemd's system
    directories and owns its lifecycle (enabling it via a
    gnome-session-pre.target.wants symlink), so the per-user generator stands
    down when one is present.
    """
    system_dirs = (
        "/usr/lib/systemd/user",
        "/usr/local/lib/systemd/user",
        "/etc/systemd/user",
    )
    return any((Path(d) / REFRESH_UNIT_NAME).is_file() for d in system_dirs)


def install_refresh_unit():
    """Install and enable the pre-shell refresh unit, idempotently.

    Returns a short status string, or None when nothing changed or it isn't applicable
    (no systemd, a packaged system unit already present, write/enable failure).
    """
    if shutil.which("systemctl") is None:
        return None

    unit_path = _unit_path()

    if _system_unit_exists():
        # The package owns the unit; don't shadow it with a user copy. Clear out a
        # stale one a prior pip/dev install left — `~/.config/systemd/user` takes
        # precedence over the packaged path and would point at a vanished
        # interpreter, so it must go for the packaged unit to take effect.
        if unit_path.is_file():
            _run_systemctl("disable", REFRESH_UNIT_NAME)
            with contextlib.suppress(OSError):
                unit_path.unlink()
        return None

    desired = unit_text()
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


def migrate_legacy_extension():
    """Remove the pre-rename extension install so it can't double-load.

    The extension's UUID changed from `easyspeak-grid@local` to
    `easyspeak@local` (it long outgrew being just a mouse grid). A leftover
    copy under the old UUID would stay enabled and add a second panel indicator
    and grid that the daemon no longer drives, so clean it up: disable it (so
    GNOME drops it from the enabled set) then delete its directory. Best-effort
    throughout — returns True if a legacy install was found and removed.

    One-off migration shim: once users have had a release or two to upgrade past
    `easyspeak-grid@local` this can be removed (call site and tests included).
    """
    legacy_dir = extensions_root() / LEGACY_EXTENSION_UUID
    if not legacy_dir.is_dir():
        return False
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["gnome-extensions", "disable", LEGACY_EXTENSION_UUID],
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT,
        )
    shutil.rmtree(legacy_dir, ignore_errors=True)
    logger.info(
        "removed the legacy %s extension (renamed to %s) — log out and back in "
        "to load the new one",
        LEGACY_EXTENSION_UUID,
        EXTENSION_UUID,
    )
    return True


def ensure_extension():
    """Startup hook: install the refresh service and activate the extension.

    Composes the two independently-runnable activities `core.desktop_integration`
    also exposes. Skipped on non-GNOME desktops.
    """
    if shutil.which("gnome-extensions") is None:
        return
    unit_status = install_refresh_unit()
    if unit_status:
        logger.info("%s", unit_status)
    activate_extension()


def activate_extension():
    """Install, refresh, and enable the bundled extension, reporting what it did.

    Installs it if missing, keeps the installed copy current, and enables it. Skipped on
    non-GNOME desktops; non-fatal on missing sources or write failures.
    """
    if shutil.which("gnome-extensions") is None:
        return

    migrate_legacy_extension()

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

    installed = EXTENSION_UUID in listed.stdout.split()
    # A failed --enabled probe leaves this False, so we fall through and try
    # enabling (a no-op when it's already on).
    already_enabled = (
        listed_enabled.returncode == 0
        and EXTENSION_UUID in listed_enabled.stdout.split()
    )
    dest_dir = extension_dest_dir()
    root = extension_source_dir()

    if installed and already_enabled:
        result = refresh_extension_files(root, dest_dir)
        if result is RefreshResult.REFRESHED:
            logger.info(
                "updated GNOME extension %s to the bundled version — "
                "log out and back in to load it",
                EXTENSION_UUID,
            )
        elif result is RefreshResult.UNCHANGED:
            logger.info(
                "GNOME extension %s already installed and enabled",
                EXTENSION_UUID,
            )
        # ERROR was already noted by refresh_extension_files; stay quiet rather
        # than claim a healthy install.
        return

    if not installed:
        if not all((root / name).is_file() for name in EXTENSION_ASSETS):
            logger.warning(
                "could not auto-install GNOME extension — source files not "
                "found at %s. The panel indicator and grid commands will not "
                "work until the extension is installed manually.",
                root,
            )
            return

        if refresh_extension_files(root, dest_dir) is RefreshResult.ERROR:
            # refresh_extension_files already reported the write error (with the
            # OSError detail) on stderr; add only the consequence, not a second
            # description of the same failure.
            logger.warning(
                "the panel indicator and grid commands will not work until "
                "the GNOME extension is installed manually."
            )
            return

    # On Wayland GNOME only rescans at login, so enable fails with "Unknown
    # extension" until then — treated as "installed, log back in to use".
    try:
        enabled = subprocess.run(
            ["gnome-extensions", "enable", EXTENSION_UUID],
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
            logger.info(
                "enabled GNOME extension %s (was installed but disabled)",
                EXTENSION_UUID,
            )
        else:
            logger.warning(
                "GNOME extension %s is installed but disabled, and could not "
                "be enabled. Try: gnome-extensions enable %s",
                EXTENSION_UUID,
                EXTENSION_UUID,
            )
        return

    if ok:
        logger.info(
            "installed and enabled GNOME extension %s at %s",
            EXTENSION_UUID,
            dest_dir,
        )
    else:
        logger.info(
            "installed GNOME extension to %s — "
            "log out and back in to finish enabling it.",
            dest_dir,
        )


def main():
    """Refresh the installed extension; entry point for the systemd unit."""
    refresh_installed_extension()
    return 0


if __name__ == "__main__":
    sys.exit(main())
