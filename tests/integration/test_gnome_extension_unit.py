"""Real-execution check for the pre-login refresh systemd user unit.

The unit suite proves ``install_refresh_unit`` writes the right file and *calls*
``systemctl --user enable`` (subprocess is mocked there). Nothing in it proves a
real systemd user manager actually accepts and enables the generated unit. This
test closes that gap by installing through the genuine ``systemctl --user`` and
asserting the manager reports the unit ``enabled``.

It needs a running per-user systemd manager (the ``user_systemd`` fixture skips
otherwise, e.g. on headless CI). To avoid clobbering the user's real
``easyspeak-extension-refresh.service``, it redirects the module to a throwaway
unit name and removes it again in teardown.
"""

import subprocess

from easyspeak.core import gnome_extension

# A throwaway unit name so a developer's real installed unit is never touched.
TEST_UNIT = "easyspeak-extension-refresh-itest.service"


def _remove_test_unit(unit_path):
    """Best-effort teardown: disable, delete, and re-read so no state lingers."""
    subprocess.run(
        ["systemctl", "--user", "disable", TEST_UNIT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    unit_path.unlink(missing_ok=True)
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_install_refresh_unit_enables_via_real_systemctl(user_systemd, monkeypatch):
    """install_refresh_unit writes a unit a real user systemd manager enables."""
    monkeypatch.setattr(gnome_extension, "REFRESH_UNIT_NAME", TEST_UNIT)
    unit_path = gnome_extension.unit_path()

    _remove_test_unit(unit_path)  # clear any leftover from a prior failed run
    try:
        status = gnome_extension.install_refresh_unit()

        # The function reports a fresh install, and the file really landed where
        # the user systemd manager looks for it.
        assert status == f"installed systemd user unit {TEST_UNIT}"
        assert unit_path.is_file()

        # The genuine manager — not a mock — reports it enabled, which means the
        # unit parsed and `enable` created the gnome-session-pre.target.wants
        # symlink. A second call is a no-op (already current and enabled).
        probe = subprocess.run(
            ["systemctl", "--user", "is-enabled", TEST_UNIT],
            capture_output=True,
            text=True,
        )
        assert probe.stdout.strip() == "enabled"
        assert gnome_extension.install_refresh_unit() is None
    finally:
        _remove_test_unit(unit_path)
