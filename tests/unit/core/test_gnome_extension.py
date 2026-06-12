"""Tests for the easyspeak.core.gnome_extension module."""

import subprocess
import sys
from unittest.mock import Mock, patch

import pytest
from easyspeak.core import gnome_extension

UNIT_NAME = "easyspeak-extension-refresh.service"


# --- refresh_extension_files -------------------------------------------------


def test_refresh_extension_files_installs_when_dest_missing(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "extension.js").write_text("new")
    (src / "metadata.json").write_text("{}")
    dest = tmp_path / "dest"  # does not exist yet

    refreshed = gnome_extension.refresh_extension_files(
        src / "extension.js", src / "metadata.json", dest
    )

    assert refreshed is gnome_extension.RefreshResult.REFRESHED
    assert (dest / "extension.js").read_text() == "new"
    assert (dest / "metadata.json").read_text() == "{}"


def test_refresh_extension_files_overwrites_when_changed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "extension.js").write_text("new")
    (src / "metadata.json").write_text("{}")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "extension.js").write_text("old")
    (dest / "metadata.json").write_text("{}")

    refreshed = gnome_extension.refresh_extension_files(
        src / "extension.js", src / "metadata.json", dest
    )

    assert refreshed is gnome_extension.RefreshResult.REFRESHED
    assert (dest / "extension.js").read_text() == "new"


def test_refresh_extension_files_noop_when_identical(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "extension.js").write_text("same")
    (src / "metadata.json").write_text("{}")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "extension.js").write_text("same")
    (dest / "metadata.json").write_text("{}")

    refreshed = gnome_extension.refresh_extension_files(
        src / "extension.js", src / "metadata.json", dest
    )

    assert refreshed is gnome_extension.RefreshResult.UNCHANGED


@patch.object(gnome_extension.shutil, "copy2", side_effect=PermissionError("ro"))
def test_refresh_extension_files_write_failure_returns_error(
    mock_copy, tmp_path, capsys
):
    """A write error (e.g. read-only dest) is swallowed and noted on stderr,
    leaving the existing install untouched rather than crashing startup."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "extension.js").write_text("new")
    (src / "metadata.json").write_text("{}")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "extension.js").write_text("old")
    (dest / "metadata.json").write_text("{}")

    refreshed = gnome_extension.refresh_extension_files(
        src / "extension.js", src / "metadata.json", dest
    )

    assert refreshed is gnome_extension.RefreshResult.ERROR
    assert (dest / "extension.js").read_text() == "old"
    assert "could not refresh GNOME extension" in capsys.readouterr().err


def test_refresh_extension_files_no_partial_overwrite_on_midway_failure(tmp_path):
    """A copy failing partway through leaves the existing install untouched and
    no temp files behind, since files are staged then moved."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "extension.js").write_text("new")
    (src / "metadata.json").write_text("new")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "extension.js").write_text("old")
    (dest / "metadata.json").write_text("old")

    real_copy = gnome_extension.shutil.copy2
    calls = {"n": 0}

    def flaky_copy(s, d, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # fail the second copy, mid-refresh
            raise OSError("disk full")
        return real_copy(s, d, *a, **k)

    with patch.object(gnome_extension.shutil, "copy2", side_effect=flaky_copy):
        refreshed = gnome_extension.refresh_extension_files(
            src / "extension.js", src / "metadata.json", dest
        )

    assert refreshed is gnome_extension.RefreshResult.ERROR
    assert (dest / "extension.js").read_text() == "old"
    assert (dest / "metadata.json").read_text() == "old"
    assert not list(dest.glob(".*.tmp"))


def test_refresh_extension_files_missing_source(tmp_path, capsys):
    src = tmp_path / "src"  # no files created
    dest = tmp_path / "dest"

    refreshed = gnome_extension.refresh_extension_files(
        src / "extension.js", src / "metadata.json", dest
    )

    assert refreshed is gnome_extension.RefreshResult.ERROR
    assert not dest.exists()
    assert "sources missing" in capsys.readouterr().err


# --- path helpers ------------------------------------------------------------


def test_extension_source_dir_holds_bundled_assets():
    src = gnome_extension.extension_source_dir()
    # Assets are package data in src/ (the easyspeak package), next to core/.
    assert (src / "extension.js").is_file()
    assert (src / "metadata.json").is_file()
    assert (src / "core" / "gnome_extension.py").is_file()


def test_extension_dest_dir(tmp_path):
    with patch.object(gnome_extension.Path, "home", return_value=tmp_path):
        dest = gnome_extension.extension_dest_dir()
    assert dest == (
        tmp_path
        / ".local"
        / "share"
        / "gnome-shell"
        / "extensions"
        / gnome_extension.GRID_EXTENSION_UUID
    )


def test_refresh_installed_extension_delegates():
    from pathlib import Path

    with (
        patch.object(
            gnome_extension, "extension_source_dir", return_value=Path("/repo")
        ),
        patch.object(gnome_extension, "extension_dest_dir", return_value=Path("/dest")),
        patch.object(
            gnome_extension,
            "refresh_extension_files",
            return_value=gnome_extension.RefreshResult.REFRESHED,
        ) as mock_refresh,
    ):
        result = gnome_extension.refresh_installed_extension()

    assert result is gnome_extension.RefreshResult.REFRESHED
    args = mock_refresh.call_args.args
    assert args[0].name == "extension.js"
    assert args[1].name == "metadata.json"
    assert str(args[2]) == "/dest"


# --- unit rendering ----------------------------------------------------------


def test_unit_text_contains_ordering_and_execstart():
    text = gnome_extension._unit_text()
    assert f"WantedBy={gnome_extension.PRE_SHELL_TARGET}" in text
    assert f"Before={gnome_extension.PRE_SHELL_TARGET}" in text
    assert "org.gnome.Shell@user.service" in text
    assert "Type=oneshot" in text
    # Both ExecStart arguments are quoted so a space in the interpreter or
    # module path can't make systemd mis-split the command.
    assert f'ExecStart="{sys.executable}" "' in text
    assert "gnome_extension.py" in text


def test_unit_path(tmp_path):
    with patch.object(gnome_extension.Path, "home", return_value=tmp_path):
        assert gnome_extension._unit_path() == (
            tmp_path / ".config" / "systemd" / "user" / UNIT_NAME
        )


# --- _is_enabled -------------------------------------------------------------


def test_is_enabled_true():
    with patch.object(
        gnome_extension.subprocess,
        "run",
        return_value=Mock(returncode=0, stdout="enabled\n"),
    ):
        assert gnome_extension._is_enabled() is True


def test_is_enabled_false_when_disabled():
    with patch.object(
        gnome_extension.subprocess,
        "run",
        return_value=Mock(returncode=1, stdout="disabled\n"),
    ):
        assert gnome_extension._is_enabled() is False


def test_is_enabled_false_when_systemctl_unexecable():
    """An OSError from systemctl (vanished/exec failure) reports 'not enabled'
    rather than propagating and crashing startup."""
    with patch.object(
        gnome_extension.subprocess, "run", side_effect=OSError("no exec")
    ):
        assert gnome_extension._is_enabled() is False


def test_is_enabled_false_when_systemctl_times_out():
    """A wedged user bus times out instead of hanging startup."""
    with patch.object(
        gnome_extension.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=5),
    ):
        assert gnome_extension._is_enabled() is False


# --- install_refresh_unit ----------------------------------------------------


def test_install_refresh_unit_no_systemd():
    with patch.object(gnome_extension.shutil, "which", return_value=None):
        assert gnome_extension.install_refresh_unit() is None


def test_install_refresh_unit_new_install(tmp_path):
    with (
        patch.object(
            gnome_extension.shutil, "which", return_value="/usr/bin/systemctl"
        ),
        patch.object(gnome_extension.Path, "home", return_value=tmp_path),
        patch.object(
            gnome_extension.subprocess, "run", return_value=Mock(returncode=0)
        ) as mock_run,
    ):
        status = gnome_extension.install_refresh_unit()

    unit = tmp_path / ".config" / "systemd" / "user" / UNIT_NAME
    assert unit.is_file()
    assert unit.read_text() == gnome_extension._unit_text()
    assert status == f"installed systemd user unit {UNIT_NAME}"
    cmds = [call.args[0] for call in mock_run.call_args_list]
    assert ["systemctl", "--user", "daemon-reload"] in cmds
    assert ["systemctl", "--user", "enable", UNIT_NAME] in cmds


def test_install_refresh_unit_systemctl_unexecable_returns_none(tmp_path):
    """If systemctl can't be executed (OSError on the enable call), the install
    is a no-op rather than crashing — the unit file is still written, but no
    status is reported since it couldn't be enabled."""
    with (
        patch.object(
            gnome_extension.shutil, "which", return_value="/usr/bin/systemctl"
        ),
        patch.object(gnome_extension.Path, "home", return_value=tmp_path),
        patch.object(gnome_extension.subprocess, "run", side_effect=OSError("no exec")),
    ):
        status = gnome_extension.install_refresh_unit()

    assert status is None


def test_install_refresh_unit_noop_when_current_and_enabled(tmp_path):
    unit = tmp_path / ".config" / "systemd" / "user" / UNIT_NAME
    unit.parent.mkdir(parents=True)
    unit.write_text(gnome_extension._unit_text())

    with (
        patch.object(
            gnome_extension.shutil, "which", return_value="/usr/bin/systemctl"
        ),
        patch.object(gnome_extension.Path, "home", return_value=tmp_path),
        patch.object(
            gnome_extension.subprocess,
            "run",
            return_value=Mock(returncode=0, stdout="enabled\n"),
        ) as mock_run,
    ):
        status = gnome_extension.install_refresh_unit()

    assert status is None
    # Only the is-enabled probe ran — no rewrite, no daemon-reload, no enable.
    cmds = [call.args[0] for call in mock_run.call_args_list]
    assert cmds == [["systemctl", "--user", "is-enabled", UNIT_NAME]]


def test_install_refresh_unit_current_but_disabled_enables(tmp_path):
    unit = tmp_path / ".config" / "systemd" / "user" / UNIT_NAME
    unit.parent.mkdir(parents=True)
    unit.write_text(gnome_extension._unit_text())

    with (
        patch.object(
            gnome_extension.shutil, "which", return_value="/usr/bin/systemctl"
        ),
        patch.object(gnome_extension.Path, "home", return_value=tmp_path),
        patch.object(
            gnome_extension.subprocess,
            "run",
            side_effect=[
                Mock(returncode=1, stdout="disabled\n"),  # is-enabled
                Mock(returncode=0),  # enable
            ],
        ) as mock_run,
    ):
        status = gnome_extension.install_refresh_unit()

    assert status == f"enabled systemd user unit {UNIT_NAME}"
    cmds = [call.args[0] for call in mock_run.call_args_list]
    assert cmds == [
        ["systemctl", "--user", "is-enabled", UNIT_NAME],
        ["systemctl", "--user", "enable", UNIT_NAME],
    ]


def test_install_refresh_unit_rewrites_when_changed(tmp_path):
    unit = tmp_path / ".config" / "systemd" / "user" / UNIT_NAME
    unit.parent.mkdir(parents=True)
    unit.write_text("[Unit]\n# stale content\n")

    with (
        patch.object(
            gnome_extension.shutil, "which", return_value="/usr/bin/systemctl"
        ),
        patch.object(gnome_extension.Path, "home", return_value=tmp_path),
        patch.object(
            gnome_extension.subprocess, "run", return_value=Mock(returncode=0)
        ),
    ):
        status = gnome_extension.install_refresh_unit()

    assert unit.read_text() == gnome_extension._unit_text()
    assert status == f"installed systemd user unit {UNIT_NAME}"


def test_install_refresh_unit_read_error_treated_as_changed(tmp_path):
    unit = tmp_path / ".config" / "systemd" / "user" / UNIT_NAME
    unit.parent.mkdir(parents=True)
    unit.write_text("whatever")

    with (
        patch.object(
            gnome_extension.shutil, "which", return_value="/usr/bin/systemctl"
        ),
        patch.object(gnome_extension.Path, "home", return_value=tmp_path),
        patch.object(gnome_extension.Path, "read_text", side_effect=OSError("boom")),
        patch.object(
            gnome_extension.subprocess, "run", return_value=Mock(returncode=0)
        ),
    ):
        status = gnome_extension.install_refresh_unit()

    assert status == f"installed systemd user unit {UNIT_NAME}"


def test_install_refresh_unit_write_failure_returns_none(tmp_path):
    with (
        patch.object(
            gnome_extension.shutil, "which", return_value="/usr/bin/systemctl"
        ),
        patch.object(gnome_extension.Path, "home", return_value=tmp_path),
        patch.object(gnome_extension.Path, "write_text", side_effect=OSError("ro")),
        patch.object(gnome_extension.subprocess, "run") as mock_run,
    ):
        status = gnome_extension.install_refresh_unit()

    assert status is None
    mock_run.assert_not_called()


def test_install_refresh_unit_enable_failure_returns_none(tmp_path):
    with (
        patch.object(
            gnome_extension.shutil, "which", return_value="/usr/bin/systemctl"
        ),
        patch.object(gnome_extension.Path, "home", return_value=tmp_path),
        patch.object(
            gnome_extension.subprocess,
            "run",
            side_effect=[
                Mock(returncode=0),  # daemon-reload
                Mock(returncode=1),  # enable fails
            ],
        ),
    ):
        status = gnome_extension.install_refresh_unit()

    assert status is None


# --- main --------------------------------------------------------------------


def test_main_refreshes_and_returns_zero():
    with patch.object(
        gnome_extension, "refresh_installed_extension", return_value=True
    ) as mock_refresh:
        assert gnome_extension.main() == 0
    mock_refresh.assert_called_once_with()


# --- ensure_extension --------------------------------------------------------


class TestEnsureExtension:
    """Tests for the GNOME-extension install/enable lifecycle.

    The pre-shell refresh unit is stubbed here so these tests never touch real
    systemctl or the user's home; install_refresh_unit has its own tests above.
    """

    @pytest.fixture(autouse=True)
    def _stub_refresh_unit(self):
        with patch.object(gnome_extension, "install_refresh_unit", return_value=None):
            yield

    @patch.object(gnome_extension.shutil, "which", return_value=None)
    def test_no_gnome_cli(self, mock_which, capsys):
        """No gnome-extensions on PATH (non-GNOME): silent no-op."""
        gnome_extension.ensure_extension()

        assert capsys.readouterr().err == ""

    @patch.object(gnome_extension.subprocess, "run", side_effect=OSError("nope"))
    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_list_oserror(self, mock_which, mock_run, capsys):
        """`gnome-extensions list` raising OSError is swallowed silently."""
        gnome_extension.ensure_extension()

        assert capsys.readouterr().err == ""

    @patch.object(
        gnome_extension.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd="gnome-extensions", timeout=5),
    )
    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_list_timeout(self, mock_which, mock_run, capsys):
        """A wedged `gnome-extensions` probe times out instead of hanging."""
        gnome_extension.ensure_extension()

        assert capsys.readouterr().err == ""

    @patch.object(
        gnome_extension.subprocess, "run", return_value=Mock(returncode=1, stdout="")
    )
    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_list_returncode_nonzero(self, mock_which, mock_run, capsys):
        """`gnome-extensions list` returning non-zero: silent no-op."""
        gnome_extension.ensure_extension()

        assert capsys.readouterr().err == ""

    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_already_installed_and_enabled(self, mock_which, capsys):
        """UUID in both `list` and `list --enabled`, bundle unchanged: announce."""
        listed = Mock(
            returncode=0, stdout="other@one.com\neasyspeak-grid@local\nthird@two.org\n"
        )
        listed_enabled = Mock(
            returncode=0, stdout="easyspeak-grid@local\nother-on@two.org\n"
        )
        with (
            patch.object(
                gnome_extension.subprocess,
                "run",
                side_effect=[listed, listed_enabled],
            ) as mock_run,
            patch.object(
                gnome_extension,
                "refresh_extension_files",
                return_value=gnome_extension.RefreshResult.UNCHANGED,
            ),
        ):
            gnome_extension.ensure_extension()

        captured = capsys.readouterr()
        assert "already installed and enabled" in captured.err
        assert "easyspeak-grid@local" in captured.err
        # No `enable` call needed — only the two probe calls.
        assert mock_run.call_count == 2

    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_already_installed_refreshes_changed_bundle(self, mock_which, capsys):
        """Installed+enabled but the bundled extension changed: refresh and tell
        the user to re-login so GNOME loads the new code."""
        listed = Mock(returncode=0, stdout="easyspeak-grid@local\n")
        listed_enabled = Mock(returncode=0, stdout="easyspeak-grid@local\n")
        with (
            patch.object(
                gnome_extension.subprocess,
                "run",
                side_effect=[listed, listed_enabled],
            ) as mock_run,
            patch.object(
                gnome_extension,
                "refresh_extension_files",
                return_value=gnome_extension.RefreshResult.REFRESHED,
            ),
        ):
            gnome_extension.ensure_extension()

        captured = capsys.readouterr()
        assert "updated GNOME extension easyspeak-grid@local" in captured.err
        assert "log out and back in" in captured.err
        # Still only the two probe calls — refresh is file I/O, not a subprocess.
        assert mock_run.call_count == 2

    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_reports_unit_install(self, mock_which, capsys):
        """ensure_extension surfaces whatever install_refresh_unit reports."""
        listed = Mock(returncode=0, stdout="easyspeak-grid@local\n")
        listed_enabled = Mock(returncode=0, stdout="easyspeak-grid@local\n")
        with (
            patch.object(
                gnome_extension.subprocess,
                "run",
                side_effect=[listed, listed_enabled],
            ),
            patch.object(
                gnome_extension,
                "refresh_extension_files",
                return_value=gnome_extension.RefreshResult.UNCHANGED,
            ),
            patch.object(
                gnome_extension,
                "install_refresh_unit",
                return_value=f"installed systemd user unit {UNIT_NAME}",
            ) as mock_unit,
        ):
            gnome_extension.ensure_extension()

        mock_unit.assert_called_once_with()
        assert f"installed systemd user unit {UNIT_NAME}" in capsys.readouterr().err

    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_installed_but_disabled_enable_succeeds(self, mock_which, capsys):
        """UUID in `list` but not in `list --enabled`: flip it on and announce."""
        listed = Mock(returncode=0, stdout="other@one.com\neasyspeak-grid@local\n")
        listed_enabled = Mock(returncode=0, stdout="other-on@two.org\n")
        enabled = Mock(returncode=0, stdout="")
        with patch.object(
            gnome_extension.subprocess,
            "run",
            side_effect=[listed, listed_enabled, enabled],
        ) as mock_run:
            gnome_extension.ensure_extension()

        captured = capsys.readouterr()
        assert "enabled GNOME extension easyspeak-grid@local" in captured.err
        assert "was installed but disabled" in captured.err
        assert mock_run.call_count == 3
        assert mock_run.call_args_list[2].args[0] == [
            "gnome-extensions",
            "enable",
            "easyspeak-grid@local",
        ]

    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_installed_but_disabled_enable_fails(self, mock_which, capsys):
        """Installed-but-disabled and `enable` fails: hint, no log-out wording."""
        listed = Mock(returncode=0, stdout="easyspeak-grid@local\n")
        listed_enabled = Mock(returncode=0, stdout="")
        enabled = Mock(returncode=1, stdout="")
        with patch.object(
            gnome_extension.subprocess,
            "run",
            side_effect=[listed, listed_enabled, enabled],
        ):
            gnome_extension.ensure_extension()

        captured = capsys.readouterr()
        assert "installed but disabled, and could not be enabled" in captured.err
        assert "gnome-extensions enable easyspeak-grid@local" in captured.err
        # The "log out and back in" hint is only for fresh installs.
        assert "log out" not in captured.err

    @patch.object(gnome_extension.Path, "is_file", return_value=False)
    @patch.object(
        gnome_extension.subprocess, "run", return_value=Mock(returncode=0, stdout="")
    )
    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_source_files_missing(self, mock_which, mock_run, mock_is_file, capsys):
        """When extension source files aren't at the project root: polite note."""
        gnome_extension.ensure_extension()

        captured = capsys.readouterr()
        assert "easyspeak: note:" in captured.err
        assert "source files not found" in captured.err

    @patch.object(
        gnome_extension.subprocess, "run", return_value=Mock(returncode=0, stdout="")
    )
    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    @patch.object(gnome_extension.shutil, "copy2", side_effect=PermissionError("ro"))
    def test_copy_fails(
        self, mock_copy, mock_which, mock_run, tmp_path, monkeypatch, capsys
    ):
        """copy2 raising OSError: polite note, no enable attempt."""
        monkeypatch.setenv("HOME", str(tmp_path))

        gnome_extension.ensure_extension()

        captured = capsys.readouterr()
        assert "easyspeak: note:" in captured.err
        assert "could not install GNOME extension" in captured.err
        # Only the two probe calls (`list` and `list --enabled`); no `enable`
        # attempt after copy failure.
        assert mock_run.call_count == 2

    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_install_and_enable_success(
        self, mock_which, tmp_path, monkeypatch, capsys
    ):
        """Happy path: copies files and enables, prints success message."""
        monkeypatch.setenv("HOME", str(tmp_path))

        listed = Mock(returncode=0, stdout="other@one.com\n")
        listed_enabled = Mock(returncode=0, stdout="other-on@two.org\n")
        enabled = Mock(returncode=0, stdout="")
        with patch.object(
            gnome_extension.subprocess,
            "run",
            side_effect=[listed, listed_enabled, enabled],
        ):
            gnome_extension.ensure_extension()

        dest = (
            tmp_path
            / ".local"
            / "share"
            / "gnome-shell"
            / "extensions"
            / "easyspeak-grid@local"
        )
        assert (dest / "extension.js").is_file()
        assert (dest / "metadata.json").is_file()

        captured = capsys.readouterr()
        assert "installed and enabled" in captured.err

    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_install_succeeds_enable_returncode_nonzero(
        self, mock_which, tmp_path, monkeypatch, capsys
    ):
        """Install succeeds, but `enable` returns non-zero: log-out hint."""
        monkeypatch.setenv("HOME", str(tmp_path))

        listed = Mock(returncode=0, stdout="other@one.com\n")
        listed_enabled = Mock(returncode=0, stdout="")
        enabled = Mock(returncode=1, stdout="")
        with patch.object(
            gnome_extension.subprocess,
            "run",
            side_effect=[listed, listed_enabled, enabled],
        ):
            gnome_extension.ensure_extension()

        captured = capsys.readouterr()
        assert "log out and back in" in captured.err
        # No manual `gnome-extensions enable` instruction — next startup
        # picks it up via the installed-but-disabled branch.
        assert "gnome-extensions enable" not in captured.err

    @patch.object(
        gnome_extension.shutil, "which", return_value="/usr/bin/gnome-extensions"
    )
    def test_install_succeeds_enable_oserror(
        self, mock_which, tmp_path, monkeypatch, capsys
    ):
        """Install succeeds, but `enable` raises OSError: log-out hint."""
        monkeypatch.setenv("HOME", str(tmp_path))

        listed = Mock(returncode=0, stdout="other@one.com\n")
        listed_enabled = Mock(returncode=0, stdout="")
        with patch.object(
            gnome_extension.subprocess,
            "run",
            side_effect=[listed, listed_enabled, OSError("boom")],
        ):
            gnome_extension.ensure_extension()

        captured = capsys.readouterr()
        assert "log out and back in" in captured.err
