"""Tests for the mousegrid plugin's ydotool backend: the zone math, its parity
with the extension backend, and the parser that turns an utterance into zone
numbers."""

import ctypes
import ctypes.util
import importlib.util
import io
import json
import os
import socket
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import Mock

import pytest
from easyspeak.core import ydotool as core_ydotool
from easyspeak.plugins import mousegrid
from easyspeak.plugins.mousegrid import _common, _extension
from easyspeak.plugins.mousegrid import _ydotool as g

# The fixture pins this daemonless; tests that exercise the real resolver
# re-pin it to the function captured here at import time.
_real_injector_socket = g.injector_socket


def _pin_real_resolver(monkeypatch):
    """Re-pin the real daemon resolver in BOTH namespaces.

    `injector_socket` moved to core, so its name now lives in two module
    dicts: the grid-owned callers (`legacy_delay_args`, `_probe_injector`)
    resolve the grid global, the moved `_client_env` resolves core's. A
    one-sided re-pin would leave the other side on the fixture's daemonless
    stub.
    """
    monkeypatch.setattr(core_ydotool, "injector_socket", _real_injector_socket)
    monkeypatch.setattr(g, "injector_socket", _real_injector_socket)


def _pin_argv_recorder(monkeypatch, seen):
    """Record every injected argv, on both namespaces.

    The verb runners reach the seam through core's `run_ydotool` (which
    resolves `_run_bounded` in core's globals), `_probe_injector` through the
    grid's re-export — one recorder, two module dicts.
    """

    def record(args, **k):
        return seen.append(list(args)) or "ran"

    monkeypatch.setattr(core_ydotool, "_run_bounded", record)
    monkeypatch.setattr(g, "_run_bounded", record)


# Snapshotted before any fixture runs: `test_inert_at_import` asserts the
# module's import-time shape, which the autouse reset would otherwise
# make unfalsifiable (the RH-5 class: a test that asserts its own setup).
_IMPORT_TIME_ACTIVE = g._active

# What Ubuntu 25.10's ydotool 0.1.8 prints for `ydotool help`, read off the VM:
# the five verbs are the whole surface there, and `mousemove_relative` is not
# one of them — that absence is what the portable probe exists for.
UBUNTU_HELP = (
    "Usage: ydotool <cmd> <args>\n"
    "Available commands:\n"
    "  type\n"
    "  recorder\n"
    "  mousemove\n"
    "  key\n"
    "  click\n"
)
UBUNTU_VERBS = {"type", "recorder", "mousemove", "key", "click"}

# What Ubuntu 26.04's ydotool 1.0.4 prints for `ydotool help`, read off that VM:
# the same five verbs plus `debug` and `bakers`, and a trailing sentence *after*
# the list that is not a verb. Only the indented lines are commands.
RESOLUTE_HELP = (
    "Usage: ydotool <cmd> <args>\n"
    "Available commands:\n"
    "  click\n"
    "  mousemove\n"
    "  type\n"
    "  key\n"
    "  debug\n"
    "  bakers\n"
    "Use environment variable YDOTOOL_SOCKET to specify daemon socket.\n"
)
RESOLUTE_VERBS = {"click", "mousemove", "type", "key", "debug", "bakers"}

# The two dialects answer *this* question about themselves differently, which is
# how the seam picks one: 1.0.4's move verb names `--absolute` in its own usage
# line, 0.1.8's (whose move takes the position as positionals) does not.
MODERN_MOVE_HELP = (
    "Usage: mousemove [OPTION]... [-x <xpos> -y <ypos>] [-- <xpos> <ypos>]\n"
    "Move mouse pointer or wheel.\n"
    "\n"
    "Options:\n"
    "  -w, --wheel                Move mouse wheel relatively\n"
    "  -a, --absolute             Use absolute position, not applicable to wheel\n"
    "  -x, --xpos                 X position\n"
    "  -y, --ypos                 Y position\n"
    "  -h, --help                 Display this help and exit\n"
)
LEGACY_MOVE_HELP = (
    "Usage: mousemove [OPTION]... <x> <y>\n"
    "Options:\n"
    "  -h, --help                 Display this help and exit\n"
)


def _help_result(text=UBUNTU_HELP):
    """What `ydotool help` returns on Ubuntu: the list on stderr, exit 1."""
    return Mock(returncode=1, stdout="", stderr=text)


def _modern_help_result():
    """What 1.0.4's `ydotool help` returns: the list on stdout, exit 0."""
    return Mock(returncode=0, stdout=RESOLUTE_HELP, stderr="")


def _modern_client(cmd, timeout):
    """One 1.0.4 binary answering both questions the seam asks of it.

    The tool list and the move verb's own help come from the same client, so a
    stub that answers only one of them would let a test pass on a dialect the
    real binary never reports.
    """
    if cmd[1] == "help":
        return _modern_help_result()
    return Mock(returncode=0, stdout=MODERN_MOVE_HELP, stderr="")


@pytest.fixture(autouse=True)
def _reap_leaked_helper():
    """No test — passing or failing — leaves a spawned helper behind."""
    yield
    if g._helper is not None:
        g.stop_helper("test cleanup")


@pytest.fixture(autouse=True)
def _fresh_client_state(monkeypatch):
    """The dialect and the session state are cached module state; every test
    starts from the plugin's own import-time shape, so no test inherits
    another's gate decision or session leftovers (an earlier version reset
    only `_dialect`, which made the inert-plugin test depend on file order).
    The daemon resolver is pinned daemonless so argv expectations are
    deterministic — a host with a running ydotoold would otherwise flip the
    legacy delay arguments mid-suite; daemon-mode tests override it."""
    monkeypatch.setattr(core_ydotool, "_dialect", None)
    monkeypatch.setattr(g, "_monitor_origin", (0, 0))
    monkeypatch.setattr(g, "_active", False)
    monkeypatch.setattr(g, "_bounds", None)
    monkeypatch.setattr(g, "_last_bounds", None)
    monkeypatch.setattr(g, "_grid_python", None)
    monkeypatch.setattr(g, "_grid_python_override", None)
    monkeypatch.setattr(g, "_grid_python_found", False)

    def _daemonless(*a, **k):
        return None

    # Both namespaces, for the same two-dicts reason `_pin_real_resolver`
    # documents below.
    monkeypatch.setattr(core_ydotool, "injector_socket", _daemonless)
    monkeypatch.setattr(g, "injector_socket", _daemonless)
    monkeypatch.setattr(core_ydotool, "_socket_last_good", None)
    monkeypatch.setattr(core_ydotool, "_socket_last_good_env", None)
    monkeypatch.setattr(core_ydotool, "_socket_search_failed", None)
    # TestGate's setup() calls rebind the dispatcher's module globals (the
    # selected backend and the help surface); reset them too, so no test
    # inherits another's gate decision — the same file-order discipline the
    # _ydotool resets above already enforce.
    monkeypatch.setattr(mousegrid, "_backend", mousegrid._extension)
    monkeypatch.setattr(mousegrid, "COMMANDS", mousegrid._COMMANDS_FULL)


class TestZoneMath:
    def test_subdivide_each_zone(self):
        bounds = (0, 0, 900, 600)
        expected = {
            1: (0, 0, 300, 200),
            2: (300, 0, 300, 200),
            3: (600, 0, 300, 200),
            4: (0, 200, 300, 200),
            5: (300, 200, 300, 200),
            6: (600, 200, 300, 200),
            7: (0, 400, 300, 200),
            8: (300, 400, 300, 200),
            9: (600, 400, 300, 200),
        }
        for zone, want in expected.items():
            assert g.subdivide(bounds, zone) == want

    def test_subdivide_truncates_like_the_extension_backend(self):
        # 1000 // 3 == 333, and the same recursion must produce the same cell on
        # both backends or the parity invariant is gone.
        assert g.subdivide((0, 0, 1000, 1000), 9) == (666, 666, 333, 333)

    def test_center(self):
        assert g.center((1351, 280, 71, 40)) == (1386, 300)


class TestContainmentInvariant:
    def test_bounds_never_leave_the_monitor(self):
        """x + w and y + h stay inside the monitor for every sequence."""
        monitor = (1920, 1080)
        for a in range(1, 10):
            for b in range(1, 10):
                for c in range(1, 10):
                    bounds = (0, 0, monitor[0], monitor[1])
                    for zone in (a, b, c):
                        bounds = g.subdivide(bounds, zone)
                    x, y, w, h = bounds
                    assert x + w <= monitor[0], (a, b, c)
                    assert y + h <= monitor[1], (a, b, c)


class TestParityWithExtension:
    """One phrase surface, two backends: both must land on the same pixel.

    Parity is structural since the consolidation: both backends serve one
    `_common`, so a divergence is an ImportError away from being impossible.
    What a test can still pin is the identity — that neither backend grew a
    private copy back — and the row-level behaviour of the shared pieces
    lives in TestZoneMath above and in test_mousegrid.py's update_grid,
    parse and exit rows.
    """

    def test_zone_math_is_the_shared_implementation(self):
        """All 729 three-zone sequences used to be driven through
        `_extension.update_grid` and compared against `subdivide` — the same
        function object on both sides, once the consolidation made
        `update_grid` delegate to `_common`. Every disagreement was
        structurally impossible, so the loop shrank to the identity it was
        actually asserting; a wrong inline copy in `update_grid` is what
        test_mousegrid.py's exact-bounds rows catch instead."""
        assert g.subdivide is _extension.subdivide
        assert g.center is _extension.center

    def test_trigger_words_are_one_shared_table(self):
        """A divergence used to be caught by comparing two maintained copies;
        the consolidation replaced the copies with one `_common` table, so the
        assertion becomes identity — a backend that stops importing it is the
        failure."""
        assert g.GRID_TRIGGERS is _extension.GRID_TRIGGERS

    def test_number_words_are_one_shared_table(self):
        """The ydotool backend reaches the table only through the shared
        parser (it never reads `WORD_TO_NUM` directly), so the identity is
        asserted between `_common` and the extension backend's import of it."""
        assert _extension.WORD_TO_NUM is _common.WORD_TO_NUM

    def test_parser_is_the_shared_implementation(self):
        assert g.parse_number_sequence is _extension.parse_number_sequence

    def test_non_decimal_digit_characters_do_not_crash_the_parser(self):
        """`str.isdigit()` answers True for superscripts, but `int("²")`
        raises: one transcribed "zone ²" would kill the mode loop. Decimal
        characters parse, everything non-decimal is simply not a zone."""
        assert g.parse_number_sequence("zone ²") == []
        assert g.parse_number_sequence("3 ² 5") == [3, 5]
        assert g.parse_number_sequence("٣") == [3]  # Arabic-Indic three: a real decimal

    @pytest.mark.parametrize(
        ["text", "want"],
        [
            ("close", True),
            ("stopwatch", True),  # substring semantics, both backends alike
            ("stay open", False),
            ("", False),
        ],
    )
    def test_dismissal_grammar_is_shared(self, text, want):
        """In-session dismissal must end the grid on the same utterance on
        every desktop: the ydotool backend used to match whole words only,
        so "stopwatch" closed the grid under GNOME and stranded it under
        sway. Both now read one shared matcher."""
        assert g.dismiss_match(text) == want
        assert g.dismiss_match is _extension.dismiss_match


@pytest.fixture
def core():
    """A core stub with the plugin-facing surface this module touches."""
    stub = Mock()
    stub.speak = Mock()
    stub.listen_modal = Mock(return_value=iter([]))
    return stub


class TestOutcomeClassification:
    """The exit code alone says nothing: Exec returns argc but the 0.1.8 client
    discards it — success is 0, measured on the VM — and the daemonless notice
    is a caveat. The seam returns one of three outcomes and the tests pin all
    three."""

    def _result(self, returncode=3, stderr="", stdout=""):
        return Mock(returncode=returncode, stderr=stderr, stdout=stdout)

    def test_ran_is_the_measured_clients_exit_code(self, monkeypatch):
        monkeypatch.setattr(core_ydotool, "_spawn", lambda *a, **k: self._result(0))
        assert g._run_bounded(["ydotool", "mousemove", "0", "0"]) == "ran"

    def test_ran_accepts_the_argv_shaped_success_code(self, monkeypatch):
        """A legacy build that forwards Exec's argc return still classifies: the
        code the tool computes is `len(args) - 1`, which this argv makes 3. The
        dialect is pinned because the tolerance is legacy-only."""
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_LEGACY)
        monkeypatch.setattr(core_ydotool, "_spawn", lambda *a, **k: self._result(3))
        assert g._run_bounded(["ydotool", "mousemove", "0", "0"]) == "ran"

    def test_the_argv_shaped_code_is_never_a_modern_success(self, monkeypatch):
        """On the modern dialect exit 2 is `failed to connect socket` — a real
        failure — and a click argv's `len(args) - 1` is also 2. Clean output or
        not, the shape alone must never read as `ran` there, or one wording
        drift in a 1.0.x variant turns every daemon-less click into silent
        success."""
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_MODERN)
        monkeypatch.setattr(core_ydotool, "_spawn", lambda *a, **k: self._result(2))
        assert g._run_bounded(["ydotool", "click", "0xC0"]) == "errored"

    def test_legacy_accepts_both_argc_shapes(self, monkeypatch):
        """The draft's own forwarding table disagrees with itself by one: the
        noop row reports the full argc, the click row one less. A legacy build
        that forwards either shape still classifies as `ran`."""
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_LEGACY)
        noop = ["ydotool", "type", "", "--delay", "0"]
        monkeypatch.setattr(
            core_ydotool, "_spawn", lambda *a, **k: self._result(len(noop))
        )
        assert g._run_bounded(noop) == "ran"
        click = ["ydotool", "click", "1"]
        monkeypatch.setattr(
            core_ydotool, "_spawn", lambda *a, **k: self._result(len(click) - 1)
        )
        assert g._run_bounded(click) == "ran"

    def test_a_refusal_on_stdout_refuses_too(self, monkeypatch):
        """Both streams are scanned, like the probe seams: a build that moves
        its refusal from stderr to stdout must not turn a rejection into a
        `ran`."""
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_MODERN)
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda *a, **k: self._result(0, stdout="failed to connect socket"),
        )
        assert g._run_bounded(["ydotool", "click", "0xC0"]) == "errored"

    def test_errored_on_an_error_signature(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda *a, **k: self._result(1, stderr="Unknown tool: x"),
        )
        assert g._run_bounded(["ydotool", "bogus"]) == "errored"

    def test_unknown_on_a_signal_kill(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool, "_spawn", lambda *a, **k: self._result(-9, stderr="")
        )
        assert g._run_bounded(["ydotool", "click", "1"]) == "unknown"

    def test_unknown_on_a_timeout(self, monkeypatch):
        import subprocess

        def boom(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="ydotool", timeout=2.0)

        monkeypatch.setattr(core_ydotool, "_spawn", boom)
        assert g._run_bounded(["ydotool", "click", "1"]) == "unknown"

    def test_unknown_when_the_binary_is_missing(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool, "_spawn", Mock(side_effect=FileNotFoundError("ydotool"))
        )
        assert g._run_bounded(["ydotool", "click", "1"]) == "unknown"

    def test_zero_exit_is_ran_even_with_the_daemonless_notice(
        self, monkeypatch, caplog
    ):
        """The VM measured a dispatched tool exiting 0 with the fallback notice
        on stderr: no daemon is a latency caveat, not a failure, and the log
        names the per-invocation mode."""
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda *a, **k: self._result(
                0, stderr="ydotool: notice: ydotoold backend unavailable ...\n"
            ),
        )
        with caplog.at_level("INFO"):
            assert g._run_bounded(["ydotool", "type", "", "--delay", "0"]) == "ran"
        assert any("per-invocation" in r.message for r in caplog.records)

    def test_a_nonzero_exit_matching_no_success_code_is_errored(self, monkeypatch):
        monkeypatch.setattr(core_ydotool, "_spawn", lambda *a, **k: self._result(7))
        assert g._run_bounded(["ydotool", "click", "1", "--delay", "0"]) == "errored"

    def test_a_rejected_argv_that_exits_zero_is_errored(self, monkeypatch, caplog):
        """1.0.4's measured answer to 0.1.8's argv: `click 1 --delay 0` prints
        `click: unrecognized option '--delay'` on stderr, emits **nothing**, and
        still exits 0. Reading the exit code alone would call that an emission,
        and the seam's `ran` is the only positive signal the plugin has — so a
        rejected argv is classified as the refusal it is."""
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda *a, **k: self._result(
                0, stderr="click: unrecognized option '--delay'\n"
            ),
        )
        with caplog.at_level("WARNING"):
            assert (
                g._run_bounded(["ydotool", "click", "1", "--delay", "0"]) == "errored"
            )
        assert any("refused" in r.message for r in caplog.records)

    def test_the_measured_modern_move_abort_is_errored(self, monkeypatch):
        """The same argv on `mousemove` does not even exit cleanly: 1.0.4 aborts
        with the option error plus `*** stack smashing detected ***` (134)."""
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda *a, **k: self._result(
                134,
                stderr=(
                    "mousemove: unrecognized option '--delay'\n"
                    "*** stack smashing detected ***: terminated\n"
                ),
            ),
        )
        assert g._run_bounded(["ydotool", "mousemove", "0", "0", "--delay", "0"]) == (
            "errored"
        )

    def test_the_modern_no_daemon_refusal_is_errored(self, monkeypatch):
        """1.0.4 without a daemon: nothing is emitted and the client says so —
        the "failed to" signature this module already treats as a refusal."""
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda *a, **k: self._result(
                2,
                stderr=(
                    "failed to connect socket `/run/user/1000/.ydotool_socket': "
                    "No such file or directory\nPlease check if ydotoold is running.\n"
                ),
            ),
        )
        assert g._run_bounded(["ydotool", "click", "0xC0"]) == "errored"

    def test_dry_run_records_without_spawning(self, monkeypatch):
        """Dry-run is a parameter of the seam now, not an env read in it: the
        short-circuit needs no spawn, and core stays ignorant of the grid's
        flag — the grid passes it down (proven end-to-end at the runner in
        TestAdapterArgv)."""
        spawn = Mock()
        monkeypatch.setattr(core_ydotool, "_spawn", spawn)
        assert g._run_bounded(["ydotool", "click", "1"], dry_run=True) == "ran"
        spawn.assert_not_called()


class TestDialect:
    """The argv dialect is read from the binary, never assumed from a version.

    0.1.8 and 1.0.x disagree about every part of the injection argv — delay flag,
    position handling, button spelling — and the wrong one is not a style
    problem: 1.0.4 rejects `--delay` (aborting on `move`), reads positional
    coordinates as *relative*, and emits nothing for a bare button selector.
    """

    def test_the_modern_move_help_selects_the_modern_dialect(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda cmd, timeout: Mock(returncode=0, stdout=MODERN_MOVE_HELP, stderr=""),
        )
        assert g._probe_dialect() == g.YDTOOL_DIALECT_MODERN

    def test_a_help_without_the_absolute_option_is_the_legacy_dialect(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda cmd, timeout: Mock(returncode=1, stdout=LEGACY_MOVE_HELP, stderr=""),
        )
        assert g._probe_dialect() == g.YDTOOL_DIALECT_LEGACY

    def test_a_help_that_cannot_answer_keeps_the_legacy_dialect(self, monkeypatch):
        """An unreadable help is not evidence of the modern argv: the legacy one
        is what this plugin shipped first, and the functional probe still has to
        report `ran` before the gate opens."""
        import subprocess

        def boom(cmd, timeout):
            raise subprocess.TimeoutExpired(cmd="ydotool", timeout=5.0)

        monkeypatch.setattr(core_ydotool, "_spawn", boom)
        assert g._probe_dialect() == g.YDTOOL_DIALECT_LEGACY

    def test_a_daemon_down_answer_logs_why_legacy_was_assumed(
        self, monkeypatch, caplog
    ):
        """On 1.0.x `mousemove --help` goes through the daemon connection, so a
        down ydotoold answers with a connect error instead of the usage line —
        the fail-safe legacy default still applies, but the log now says why,
        so the later "no legacy combo name" refusal is not misread as a
        grammar limit (measured live on the kubuntu bed, 2026-10-18)."""
        import logging

        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda cmd, timeout: Mock(
                returncode=2,
                stdout="",
                stderr=(
                    "failed to connect socket `/run/user/1000/.ydotool_socket': "
                    "Connection refused\nPlease check if ydotoold is running."
                ),
            ),
        )
        with caplog.at_level(logging.INFO, logger="easyspeak.core.ydotool"):
            assert g._probe_dialect() == g.YDTOOL_DIALECT_LEGACY
        assert "daemon is likely down" in caplog.text

    def test_a_quiet_non_modern_answer_stays_silent(self, monkeypatch, caplog):
        """A 0.1.8 help (no daemon complaint) must not borrow the daemon-down
        explanation — the two look identical to the flag check and only the
        stderr tells them apart."""
        import logging

        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda cmd, timeout: Mock(returncode=1, stdout=LEGACY_MOVE_HELP, stderr=""),
        )
        with caplog.at_level(logging.INFO, logger="easyspeak.core.ydotool"):
            assert g._probe_dialect() == g.YDTOOL_DIALECT_LEGACY
        assert "daemon is likely down" not in caplog.text

    def test_a_missing_binary_keeps_the_legacy_dialect(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool, "_spawn", Mock(side_effect=FileNotFoundError("ydotool"))
        )
        assert g._probe_dialect() == g.YDTOOL_DIALECT_LEGACY

    def test_the_dialect_is_resolved_once(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            core_ydotool,
            "_probe_dialect",
            lambda: calls.append(1) or g.YDTOOL_DIALECT_MODERN,
        )
        assert g.dialect() == g.YDTOOL_DIALECT_MODERN
        assert g.dialect() == g.YDTOOL_DIALECT_MODERN
        assert calls == [1]

    def test_the_noop_is_built_in_the_dialect(self, monkeypatch):
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_LEGACY)
        assert g.noop_argv() == ("ydotool", "type", "", "--delay", "0")
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_MODERN)
        assert g.noop_argv() == ("ydotool", "type", "")


class TestSocketDiscovery:
    """The daemon's socket path is build-dependent and not always the session's.

    1.0.x defaults to `$XDG_RUNTIME_DIR/.ydotool_socket`; 0.1.8 hardcoded
    `/tmp/.ydotool_socket`; the client's own `YDOTOOL_SOCKET` override wins. A
    session that repoints `XDG_RUNTIME_DIR` — a nested compositor, this repo's own
    harness — must still find the daemon that is running for this user, or every
    injection on 1.0.x silently becomes a refusal.
    """

    def test_the_override_wins_and_the_login_session_is_always_considered(
        self, monkeypatch
    ):
        monkeypatch.setenv("YDOTOOL_SOCKET", "/somewhere/else")
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/repointed")
        assert g.ydotool_socket_candidates() == [
            "/somewhere/else",
            "/repointed/.ydotool_socket",
            f"/run/user/{os.getuid()}/.ydotool_socket",
            "/tmp/.ydotool_socket",
        ]

    def test_a_missing_runtime_dir_still_names_the_login_session(self, monkeypatch):
        monkeypatch.delenv("YDOTOOL_SOCKET", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        assert g.ydotool_socket_candidates() == [
            f"/run/user/{os.getuid()}/.ydotool_socket",
            "/tmp/.ydotool_socket",
        ]

    def test_a_foreign_or_non_socket_candidate_is_never_trusted(self, monkeypatch):
        """protects: a connectable path is not automatically our daemon — the
        `/tmp` fallback lives in a world-writable directory, so a socket
        planted there by another uid would pass a bare `connect()` probe,
        receive every injected coordinate, and inject nothing.
        fails_when: ownership or socket-type is not checked before the
        candidate is offered to `_socket_accepts`, or a foreign (or same-uid
        non-socket) path is returned as the injector.
        no_claim: does not claim a same-uid impostor is impossible (unix
        sockets cannot authenticate beyond ownership); does not touch the
        filesystem — `Path.stat` is stubbed.
        seam: none — the real resolver runs (the autouse fixture stubs it;
        this test re-pins it, or the checks below would never execute).
        """
        monkeypatch.setenv("YDOTOOL_SOCKET", "/tmp/.ydotool_socket")
        _pin_real_resolver(monkeypatch)
        monkeypatch.setattr(
            core_ydotool, "ydotool_socket_candidates", lambda: ["/tmp/.ydotool_socket"]
        )
        # Two calls must both reach the ownership check: without this, the
        # first failed walk's rediscovery cooldown would swallow the second.
        monkeypatch.setattr(core_ydotool, "REDISCOVERY_COOLDOWN", 0)
        socket_mode = 0o140600  # S_IFSOCK | 0600, without importing stat
        plain_mode = 0o100600  # S_IFREG | 0600: same uid, but not a socket
        answers = [
            Mock(st_mode=socket_mode, st_uid=os.getuid() + 1),  # foreign socket
            Mock(st_mode=plain_mode, st_uid=os.getuid()),  # own regular file
        ]
        # Patch the method, not the os module attribute: Path().stat() binds
        # through the os module differently across the supported Pythons, and
        # the method patch behaves the same on every one of them.
        monkeypatch.setattr(Path, "stat", lambda self, **_kwargs: answers.pop(0))
        asked = []
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path, timeout=g.PROBE_TIMEOUT: asked.append(path) or True,
        )
        assert g.injector_socket() is None  # a foreign uid: never offered
        assert g.injector_socket() is None  # own uid, but not a socket: same
        assert asked == []
        assert core_ydotool._socket_last_good is None

    def test_an_owned_listening_socket_is_trusted_and_cached(
        self, monkeypatch, tmp_path
    ):
        """protects: the acceptance branch of `_socket_owned` — own uid AND a
        real socket — is the only path that ever finds a daemon; its two
        rejection twins are pinned above, but this branch had no test
        (mutation-proven: `return True` → `return False` kept the whole suite
        green while disabling daemon discovery entirely). Also the suite's
        first real connect() through `_socket_accepts`, against a real
        listener instead of socket-module mocks.
        fails_when: the acceptance branch stops trusting an owned socket, or
        the answer is not cached as last-good.
        no_claim: does not claim a same-uid impostor is impossible (unix
        sockets cannot authenticate beyond ownership); the listener is real
        and bound by this test's own uid.
        seam: none — the real resolver runs against a real AF_UNIX listener.
        """
        path = tmp_path / ".ydotool_socket"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(path))
            sock.listen(1)
            _pin_real_resolver(monkeypatch)
            monkeypatch.setattr(
                core_ydotool, "ydotool_socket_candidates", lambda: [str(path)]
            )
            assert g.injector_socket() == str(path)
            assert core_ydotool._socket_last_good == str(path)
        finally:
            sock.close()

    def test_the_last_good_socket_is_probed_first(self, monkeypatch):
        """protects: the path that answered last time is re-validated before
        the priority order is walked, so the steady state costs one connect
        instead of the full four-path, two-socket-type fan-out per injection.
        fails_when: the cache short-circuits without re-validating (a stopped
        daemon would stay "good"), or there is no cache at all (the second call
        would walk the priority order from the top again — the shape this test
        distinguishes by caching a NON-first candidate).
        no_claim: does not claim which path a real daemon binds; every probe
        answer is stubbed.
        seam: none
        """
        asked = []
        monkeypatch.setattr(core_ydotool, "_socket_owned", lambda _path: True)
        _pin_real_resolver(monkeypatch)
        monkeypatch.delenv("YDOTOOL_SOCKET", raising=False)
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/xdg")
        order = [
            "/xdg/.ydotool_socket",
            f"/run/user/{os.getuid()}/.ydotool_socket",
            "/tmp/.ydotool_socket",
        ]
        monkeypatch.setattr(
            core_ydotool, "ydotool_socket_candidates", lambda: list(order)
        )
        # First call: the highest-priority candidate is dead, the second one
        # answers — and becomes the cache.
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path, timeout=g.PROBE_TIMEOUT: (
                asked.append(path) or path == order[1]
            ),
        )
        assert g.injector_socket() == order[1]
        assert asked == [order[0], order[1]]

        # Second call: the cached candidate is probed FIRST — before the dead
        # higher-priority head of the list. A no-cache implementation would
        # walk the order from the top again and append order[0] here.
        asked.clear()
        assert g.injector_socket() == order[1]
        assert asked == [order[1]]
        assert core_ydotool._socket_last_good == order[1]

        # Third call: the cached path stops answering — the cache is
        # invalidated and the full walk runs again (last-good first, then the
        # priority order), instead of the dead path being trusted.
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path, timeout=g.PROBE_TIMEOUT: asked.append(path) or False,
        )
        asked.clear()
        assert g.injector_socket() is None
        assert asked == [order[1], order[0], order[1], "/tmp/.ydotool_socket"]
        assert core_ydotool._socket_last_good is None

        # Fifth call: the resolution environment changes (a nested compositor
        # repoints YDOTOOL_SOCKET) — the last-good cache is keyed to that
        # environment, so the stale path is not even probed; the fresh
        # override answers instead (mutation-verified: dropping the
        # `_socket_last_good_env == env_key` compare kept the suite green
        # while the old path was probed first and reused).
        monkeypatch.setenv("YDOTOOL_SOCKET", "/override/.ydotool_socket")
        monkeypatch.setattr(
            core_ydotool,
            "ydotool_socket_candidates",
            lambda: ["/override/.ydotool_socket", order[1]],
        )
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path, timeout=g.PROBE_TIMEOUT: (
                asked.append(path) or path == "/override/.ydotool_socket"
            ),
        )
        asked.clear()
        assert g.injector_socket() == "/override/.ydotool_socket"
        assert asked == ["/override/.ydotool_socket"]
        assert core_ydotool._socket_last_good == "/override/.ydotool_socket"

    def test_repeated_paths_are_collapsed(self, monkeypatch):
        uid = os.getuid()
        monkeypatch.setenv("YDOTOOL_SOCKET", f"/run/user/{uid}/.ydotool_socket")
        monkeypatch.setenv("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        assert g.ydotool_socket_candidates() == [
            f"/run/user/{uid}/.ydotool_socket",
            "/tmp/.ydotool_socket",
        ]

    def test_the_first_socket_that_answers_is_the_one_used(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool,
            "ydotool_socket_candidates",
            lambda: ["/dead", "/alive", "/tmp/.x"],
        )
        monkeypatch.setattr(core_ydotool, "_socket_owned", lambda _path: True)
        _pin_real_resolver(monkeypatch)
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path, timeout=g.PROBE_TIMEOUT: path == "/alive",
        )
        assert g.injector_socket() == "/alive"

    def test_no_answer_is_none_not_a_guess(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool, "ydotool_socket_candidates", lambda: ["/dead"]
        )
        monkeypatch.setattr(core_ydotool, "_socket_owned", lambda _path: True)
        _pin_real_resolver(monkeypatch)
        monkeypatch.setattr(
            core_ydotool, "_socket_accepts", lambda path, timeout=g.PROBE_TIMEOUT: False
        )
        assert g.injector_socket() is None

    def test_a_failed_rediscovery_is_shared_within_the_cooldown(self, monkeypatch):
        """protects: the per-injection callers ask up to four times per click
        utterance (the move's delay args and client env, then the click's);
        each must share one failed fan-out instead of repeating the full walk
        — a stale socket that accepts but never serves would otherwise cost
        the per-use bound per candidate per call, ~2 s of silent voice-thread
        stall between a move and its click.
        fails_when: every call re-walks the candidates after a failure, or
        the window never closes (a daemon that starts later would never be
        found).
        no_claim: does not claim how long a real connect takes; the clock and
        every probe answer are stubbed.
        seam: time.monotonic is pinned; `_socket_accepts` counts its asks.
        """
        _pin_real_resolver(monkeypatch)
        monkeypatch.setattr(
            core_ydotool, "ydotool_socket_candidates", lambda: ["/dead"]
        )
        monkeypatch.setattr(core_ydotool, "_socket_owned", lambda _path: True)
        now = 1000.0
        monkeypatch.setattr(g.time, "monotonic", lambda: now)
        asked = []
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path, timeout=g.PROBE_TIMEOUT: asked.append(path) or False,
        )
        assert g.injector_socket() is None
        assert asked == ["/dead"]  # the walk ran once
        now += core_ydotool.REDISCOVERY_COOLDOWN / 2
        assert g.injector_socket() is None
        assert asked == ["/dead"]  # inside the window: the answer is shared
        now += core_ydotool.REDISCOVERY_COOLDOWN
        assert g.injector_socket() is None
        assert asked == ["/dead", "/dead"]  # the window closed: walk again

    def test_a_changed_environment_always_walks_again(self, monkeypatch):
        """protects: the failed-discovery memory is keyed by the resolution
        environment, so a moved `YDOTOOL_SOCKET`/`XDG_RUNTIME_DIR` cannot be
        answered "none" out of a failure recorded under the old one.
        fails_when: the cooldown short-circuits a walk whose candidates have
        changed since the failure.
        no_claim: does not claim where a real daemon binds; every probe
        answer is stubbed.
        seam: time.monotonic is pinned; `_socket_accepts` counts its asks.
        """
        _pin_real_resolver(monkeypatch)
        monkeypatch.setattr(
            core_ydotool, "ydotool_socket_candidates", lambda: ["/dead"]
        )
        monkeypatch.setattr(core_ydotool, "_socket_owned", lambda _path: True)
        now = 1000.0
        monkeypatch.setattr(g.time, "monotonic", lambda: now)
        asked = []
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path, timeout=g.PROBE_TIMEOUT: asked.append(path) or False,
        )
        assert g.injector_socket() is None
        assert asked == ["/dead"]
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/elsewhere")
        assert g.injector_socket() is None
        # The candidate list is stubbed to the same path, but the environment
        # key changed, so the walk reruns instead of trusting the memory.
        assert asked == ["/dead", "/dead"]

    def test_an_answer_clears_the_failed_rediscovery_memory(self, monkeypatch):
        """protects: once a socket answers, the "none" memory must be gone —
        a failure recorded before the daemon appeared must not outlive the
        daemon it was recorded about.
        fails_when: the success path leaves `_socket_search_failed` set, so
        the memory claims "no daemon" about a resolver that just found one.
        no_claim: does not claim the same socket keeps answering; each call's
        probe answer is stubbed separately.
        seam: time.monotonic is pinned; `_socket_accepts` answers from a
        script.
        """
        _pin_real_resolver(monkeypatch)
        monkeypatch.setattr(
            core_ydotool, "ydotool_socket_candidates", lambda: ["/dead"]
        )
        monkeypatch.setattr(core_ydotool, "_socket_owned", lambda _path: True)
        now = 1000.0
        monkeypatch.setattr(g.time, "monotonic", lambda: now)
        asked = []
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path, timeout=g.PROBE_TIMEOUT: asked.append(path) or False,
        )
        assert g.injector_socket() is None  # the walk fails; memory set
        assert core_ydotool._socket_search_failed is not None
        now += core_ydotool.REDISCOVERY_COOLDOWN
        monkeypatch.setattr(
            core_ydotool, "_socket_accepts", lambda path, timeout=g.PROBE_TIMEOUT: True
        )
        assert g.injector_socket() == "/dead"  # window closed: the walk runs
        assert core_ydotool._socket_search_failed is None  # ...and the memory is gone


class TestClientEnv:
    """A spawned client is told which socket to use, when one answers."""

    def test_a_found_socket_is_exported_to_the_client(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool,
            "injector_socket",
            lambda timeout=g.PROBE_TIMEOUT: "/alive.sock",
        )
        env = g._client_env()
        assert env["YDOTOOL_SOCKET"] == "/alive.sock"
        assert env["PATH"] == os.environ["PATH"]

    def test_the_client_probe_uses_the_short_per_use_bound(self, monkeypatch):
        """protects: the rediscovery that runs between a move and its click is
        bounded by the per-use fraction, not the startup bound — a daemon that
        is alive but wedged would otherwise hold the voice thread for five
        seconds per connect, ~30-40s across move plus click, with the grid
        frozen on screen.
        fails_when: `_client_env` calls `injector_socket` without the short
        timeout (or with the startup bound).
        no_claim: does not claim the socket answers; the resolver is stubbed.
        seam: none
        """
        seen = {}

        def spy(timeout=g.PROBE_TIMEOUT):
            seen["timeout"] = timeout
            return "/alive.sock"

        monkeypatch.setattr(core_ydotool, "injector_socket", spy)
        assert g._client_env()["YDOTOOL_SOCKET"] == "/alive.sock"
        assert seen["timeout"] == g.PROBE_TIMEOUT_PER_USE

    def test_with_no_socket_the_environment_is_inherited(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool, "injector_socket", lambda timeout=g.PROBE_TIMEOUT: None
        )
        assert g._client_env() is None

    def test_the_spawn_is_the_thing_that_carries_it(self, monkeypatch):
        """`_spawn` is the only place a client starts, so it is the only place
        that needs to know: `_run_bounded` and the probe stay unchanged."""
        monkeypatch.setattr(
            core_ydotool,
            "injector_socket",
            lambda timeout=g.PROBE_TIMEOUT: "/alive.sock",
        )
        seen = {}
        monkeypatch.setattr(
            g.subprocess,
            "run",
            lambda cmd, **kwargs: (
                seen.update(cmd=cmd, **kwargs)
                or Mock(returncode=0, stdout="", stderr="")
            ),
        )
        g._run_bounded(["ydotool", "click", "0xC0"])
        assert seen["env"]["YDOTOOL_SOCKET"] == "/alive.sock"


class TestHelperEnv:
    """`EASYSPEAK_GRID_TYPELIB` reaches the helper and the probes that gate it."""

    def test_the_build_tree_is_exported_as_both_search_paths(self):
        env = g.helper_env({"EASYSPEAK_GRID_TYPELIB": "/build/src"})
        assert env["GI_TYPELIB_PATH"] == "/build/src"
        assert env["LD_LIBRARY_PATH"] == "/build/src"

    def test_existing_search_paths_are_prepended_not_replaced(self):
        env = g.helper_env(
            {
                "EASYSPEAK_GRID_TYPELIB": "/build/src",
                "GI_TYPELIB_PATH": "/flake/gi",
                "LD_LIBRARY_PATH": "/flake/lib",
            }
        )
        assert env["GI_TYPELIB_PATH"] == f"/build/src{os.pathsep}/flake/gi"
        assert env["LD_LIBRARY_PATH"] == f"/build/src{os.pathsep}/flake/lib"

    def test_without_the_override_nothing_is_rewritten(self, monkeypatch):
        monkeypatch.setattr(g._overlay, "layer_shell_lib_path", lambda build=None: None)
        base = {"GI_TYPELIB_PATH": "/flake/gi", "LD_LIBRARY_PATH": "/flake/lib"}
        env = g.helper_env(base)
        assert env == base
        assert env is not base

    def test_the_layer_shell_library_is_preloaded_for_the_helper(self, monkeypatch):
        """gtk4-layer-shell interposes libwayland, and interposition only reaches
        GTK from the front of the lookup order: a plain RTLD_GLOBAL load loses to
        GDK's direct libwayland dependency, and the layer surface silently comes
        up as an ordinary window (measured live on sway)."""
        monkeypatch.setattr(
            g._overlay,
            "layer_shell_lib_path",
            lambda build=None: "libgtk4-layer-shell.so.0",
        )
        env = g.helper_env({})
        assert env["LD_PRELOAD"] == "libgtk4-layer-shell.so.0"

    def test_an_existing_ld_preload_is_prepended_not_replaced(self, monkeypatch):
        monkeypatch.setattr(
            g._overlay,
            "layer_shell_lib_path",
            lambda build=None: "libgtk4-layer-shell.so.0",
        )
        env = g.helper_env({"LD_PRELOAD": "/keep.so"})
        assert env["LD_PRELOAD"] == "libgtk4-layer-shell.so.0:/keep.so"

    def test_without_a_loadable_library_no_preload_is_set(self, monkeypatch):
        monkeypatch.setattr(g._overlay, "layer_shell_lib_path", lambda build=None: None)
        assert "LD_PRELOAD" not in g.helper_env({})

    def test_the_build_tree_yields_an_absolute_preload(self, tmp_path):
        """End to end without mocks: the helper environment must export the
        library FOUND IN THE TREE, not nothing — the in-process loader can
        never see a path constructed for the child."""
        (tmp_path / "libgtk4-layer-shell.so.0").write_bytes(b"")
        (tmp_path / "libgtk4-layer-shell.so").write_bytes(b"")
        env = g.helper_env({"EASYSPEAK_GRID_TYPELIB": str(tmp_path)})
        assert env["LD_PRELOAD"] == str(tmp_path / "libgtk4-layer-shell.so")

    def test_the_default_base_is_this_process_environment(self, monkeypatch):
        monkeypatch.setenv("EASYSPEAK_GRID_TYPELIB", "/build/src")
        monkeypatch.delenv("GI_TYPELIB_PATH", raising=False)
        assert g.helper_env()["GI_TYPELIB_PATH"] == "/build/src"

    def test_the_interpreter_probe_runs_under_the_export(self, monkeypatch):
        """Without the paths here, the resolver reports the build tree's own
        interpreter as unsupported and the gate closes on a box it would serve."""
        monkeypatch.setenv("EASYSPEAK_GRID_TYPELIB", "/build/src")
        monkeypatch.setenv("GI_TYPELIB_PATH", "/flake/gi")
        monkeypatch.setenv("LD_LIBRARY_PATH", "/flake/lib")
        monkeypatch.delenv("EASYSPEAK_GRID_PYTHON", raising=False)
        seen = []
        monkeypatch.setattr(
            g.subprocess,
            "run",
            lambda cmd, **kwargs: seen.append((cmd, kwargs)) or Mock(returncode=0),
        )
        assert g.grid_python() == "python3"
        assert seen[0][1]["env"]["GI_TYPELIB_PATH"] == (
            f"/build/src{os.pathsep}/flake/gi"
        )
        assert seen[0][1]["env"]["LD_LIBRARY_PATH"] == (
            f"/build/src{os.pathsep}/flake/lib"
        )

    def test_the_helper_probe_runs_under_the_export(self, monkeypatch):
        monkeypatch.setenv("EASYSPEAK_GRID_TYPELIB", "/build/src")
        monkeypatch.setenv("GI_TYPELIB_PATH", "/flake/gi")
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        seen = []
        monkeypatch.setattr(
            g.subprocess,
            "run",
            lambda cmd, **kwargs: (
                seen.append((cmd, kwargs)) or Mock(returncode=0, stdout="", stderr="")
            ),
        )
        assert g._probe_overlay() is True
        assert seen[0][1]["env"]["GI_TYPELIB_PATH"] == (
            f"/build/src{os.pathsep}/flake/gi"
        )

    def test_the_helper_spawn_runs_under_the_export(self, monkeypatch, tmp_path):
        helper = tmp_path / "helper.py"
        helper.write_text(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 1920, 1080],"
            " 'scale': 1.0}), flush=True)\n"
            "print(json.dumps({'event': 'presented'}), flush=True)\n"
            "sys.stdin.readline()\n",
            encoding="utf-8",
        )
        # The LD_PRELOAD probe is a different concern (tested below); pinning it
        # here keeps `seen[0]` the helper's own Popen: on a host with the
        # library installed, `find_library` inside the real probe spawns
        # ldconfig (and a gcc link test) *before* the helper spawn.
        monkeypatch.setattr(g._overlay, "layer_shell_lib_path", lambda build=None: None)
        monkeypatch.setattr(g, "HELPER", str(helper))
        monkeypatch.setattr(g, "grid_python", lambda: sys.executable)
        monkeypatch.setenv("EASYSPEAK_GRID_TYPELIB", "/build/src")
        monkeypatch.setenv("LD_LIBRARY_PATH", "/flake/lib")
        real_popen = g.subprocess.Popen
        seen = []

        def spy_popen(*args, **kwargs):
            seen.append(kwargs)
            return real_popen(*args, **kwargs)

        monkeypatch.setattr(g.subprocess, "Popen", spy_popen)
        assert g._start_helper() == (0, 0, 1920, 1080)
        g.stop_helper("test")
        assert seen[0]["env"]["LD_LIBRARY_PATH"] == (
            f"/build/src{os.pathsep}/flake/lib"
        )


class TestInterpreterResolution:
    """`EASYSPEAK_GRID_PYTHON` names the interpreter outright; the built-in
    candidates are the fallback for when it is not set, never a supplement."""

    def test_the_override_is_the_only_candidate_probed_then_cached(self, monkeypatch):
        """protects: with `EASYSPEAK_GRID_PYTHON` set, that interpreter and no
        other is probed with the helper's own import chain; a failed probe
        reports none and is never cached, so a box that grows a working
        interpreter is found on the next call; and a positive is remembered,
        so later opens reuse it without paying the import probe again.
        fails_when: the override is ignored (the defaults are probed first or
        instead), a failed override falls through to the defaults, a failure is
        cached as the answer, or the cache skips a resolver that never ran.
        no_claim: does not claim which interpreters exist on this host; the
        probe result is stubbed.
        seam: none
        """
        monkeypatch.setenv("EASYSPEAK_GRID_PYTHON", "/opt/grid/python3")
        seen = []
        monkeypatch.setattr(
            g.subprocess,
            "run",
            lambda cmd, **kwargs: seen.append(list(cmd)) or Mock(returncode=1),
        )
        # A failing override is reported as none twice: never cached, never
        # silently widened to the built-in candidates.
        assert g.grid_python() is None
        assert g.grid_python() is None
        assert [cmd[0] for cmd in seen] == ["/opt/grid/python3"] * 2

        monkeypatch.setattr(
            g.subprocess,
            "run",
            lambda cmd, **kwargs: seen.append(list(cmd)) or Mock(returncode=0),
        )
        assert g.grid_python() == "/opt/grid/python3"
        assert seen == [["/opt/grid/python3", "-c", g.HELPER_PROBE]] * 3

        monkeypatch.setattr(
            g.subprocess,
            "run",
            Mock(side_effect=AssertionError("a cached resolver must not re-probe")),
        )
        assert g.grid_python() == "/opt/grid/python3"

        # A repoint invalidates the cache: the new override is probed and
        # returned, and clearing the override falls back to the built-ins —
        # neither may silently answer with the old interpreter (mutation-
        # verified: dropping the `_grid_python_override == override` compare
        # kept the suite green while a stale interpreter was returned for
        # ever).
        monkeypatch.setenv("EASYSPEAK_GRID_PYTHON", "/elsewhere/python3")
        monkeypatch.setattr(
            g.subprocess,
            "run",
            lambda cmd, **kwargs: seen.append(list(cmd)) or Mock(returncode=0),
        )
        assert g.grid_python() == "/elsewhere/python3"
        assert seen[-1][0] == "/elsewhere/python3"
        monkeypatch.delenv("EASYSPEAK_GRID_PYTHON")
        assert g.grid_python() == g.GRID_PYTHON_CANDIDATES[0]
        assert seen[-1][0] == g.GRID_PYTHON_CANDIDATES[0]


class TestAdapterArgv:
    def test_move_applies_the_monitor_origin(self, monkeypatch):
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_LEGACY)
        g._monitor_origin = (1920, 0)
        g.move_to(1351, 280)
        # Daemonless: no --delay, so ydotool's default settle runs before the
        # events — 0.1.8 creates its uinput device per invocation and delay 0
        # delivers into a device the compositor has not enumerated yet.
        assert seen == [["ydotool", "mousemove", "3271", "280"]]

    def test_move_with_a_daemon_keeps_the_zero_delay(self, monkeypatch):
        """Through a daemon the device is persistent, so --delay 0 is safe and
        a double-click pair keeps its timing headroom."""
        monkeypatch.setattr(g, "injector_socket", lambda *a, **k: "/tmp/sock")
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_LEGACY)
        g._monitor_origin = (1920, 0)
        g.move_to(1351, 280)
        assert seen == [["ydotool", "mousemove", "3271", "280", "--delay", "0"]]

    def test_delay_probe_uses_the_short_per_use_bound(self, monkeypatch):
        """protects: the delay decision resolves the daemon on the voice
        thread, mid-mode, so it must carry the short per-use bound — the
        startup bound here can stall every move and click for seconds
        against a wedged listener (the exact freeze the per-use constant
        exists to prevent).
        fails_when: legacy_delay_args calls injector_socket without the
        per-use timeout.
        no_claim: does not claim which candidate a real daemon binds.
        seam: none
        """
        seen = []
        monkeypatch.setattr(
            g, "injector_socket", lambda *a, **k: seen.append(k) or None
        )
        assert g.legacy_delay_args() == ()
        assert seen == [{"timeout": g.PROBE_TIMEOUT_PER_USE}]

    def test_click_buttons(self, monkeypatch):
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_LEGACY)
        g.click("click")
        g.click("right")
        g.click("middle")
        assert seen == [
            ["ydotool", "click", "1"],
            ["ydotool", "click", "2"],
            ["ydotool", "click", "3"],
        ]

    def test_the_modern_move_is_absolute_and_positional_is_not_used(self, monkeypatch):
        """1.0.x reads `-x`/`-y` as a *relative* delta unless `--absolute` is
        given, so the flag is the difference between "the cell's centre" and
        "somewhere off the current pointer"."""
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_MODERN)
        g._monitor_origin = (1920, 0)
        g.move_to(1351, 280)
        assert seen == [
            ["ydotool", "mousemove", "--absolute", "-x", "3271", "-y", "280"]
        ]

    def test_the_modern_buttons_are_selector_plus_mask(self, monkeypatch):
        """Measured against a GTK window in the VM: `0xC0` arrives as button 1,
        `0xC1` as 3 (right) and `0xC2` as 2 (middle), where 0.1.8's own
        `click 1` emits nothing at all on 1.0.x — it is a bare selector."""
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_MODERN)
        g.click("click")
        g.click("right")
        g.click("middle")
        assert seen == [
            ["ydotool", "click", "0xC0"],
            ["ydotool", "click", "0xC1"],
            ["ydotool", "click", "0xC2"],
        ]

    def test_double_click_is_two_calls_in_order(self, monkeypatch):
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        monkeypatch.setattr(core_ydotool, "_dialect", g.YDTOOL_DIALECT_LEGACY)
        g.double_click()
        assert [a[2] for a in seen] == ["1", "1"]

    def test_double_click_aggregates_the_two_outcomes(self, monkeypatch):
        """protects: the pair is one gesture, so `double_click` reports `ran`
        only when both clicks ran, and `errored` when either half refused —
        a refused double must speak the definite line ("I couldn't click."),
        as a refused single already does, not the uncertain one. An uncertain
        half without a refusal stays `unknown`.
        fails_when: the first click's outcome is returned alone (a second click
        that never ran reports success), the pair always reports `ran`, or a
        refused half is coarsened to `unknown`.
        no_claim: does not claim the desktop received either click, nor that
        the pointer moved.
        seam: none
        """
        outcomes = {
            ("ran", "ran"): "ran",
            ("ran", "unknown"): "unknown",
            ("unknown", "ran"): "unknown",
            ("unknown", "unknown"): "unknown",
            ("ran", "errored"): "errored",
            ("errored", "ran"): "errored",
            ("unknown", "errored"): "errored",
            ("errored", "unknown"): "errored",
            ("errored", "errored"): "errored",
        }
        for pair, want in outcomes.items():
            answers = iter(pair)
            monkeypatch.setattr(
                g, "click", lambda button="click", answers=answers: next(answers)
            )
            assert g.double_click() == want, pair

    def test_every_argv_the_seam_builds_uses_a_verb_the_binary_lists(self, monkeypatch):
        """The VM's ydotool offers five verbs and no `mousemove_relative`:
        every argv the adapter and the probe build must come from its list."""
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda cmd, timeout: Mock(returncode=1, stdout="", stderr=UBUNTU_HELP),
        )
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path=None, timeout=g.PROBE_TIMEOUT: False,
        )
        g._monitor_origin = (0, 0)
        g.move_to(10, 20)
        g.click("right")
        g.double_click()
        assert g._probe_injector() is True
        assert [argv[1] for argv in seen] == [
            "mousemove",
            "click",
            "click",
            "click",
            "type",
        ]
        assert all(argv[1] in UBUNTU_VERBS for argv in seen)

    def test_the_modern_argv_stays_inside_the_modern_verb_list(self, monkeypatch):
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        monkeypatch.setattr(
            g, "injector_socket", lambda: "/run/user/1000/.ydotool_socket"
        )
        monkeypatch.setattr(core_ydotool, "_spawn", _modern_client)
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")
        g.move_to(10, 20)
        g.click("right")
        g.double_click()
        assert g._probe_injector() is True
        assert [argv[1] for argv in seen] == [
            "mousemove",
            "click",
            "click",
            "click",
            "type",
        ]
        assert all(argv[1] in RESOLUTE_VERBS for argv in seen)
        # No `--delay` anywhere: 1.0.x has no such option, and passing it turns
        # the move into an abort and the click into a silently rejected argv.
        assert all("--delay" not in argv for argv in seen)

    def test_the_grid_dry_run_flag_still_reaches_the_core_seam(self, monkeypatch):
        """The env flag survived the extraction: the runner passes the grid's
        own `_grid_dry_run()` down as the seam's `dry_run` parameter, so a dry
        run still reports `ran` without spawning — asserted at the CORE `_spawn`
        seam, where a wiring gap would show up as a real client start."""
        spawn = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(core_ydotool, "_spawn", spawn)
        monkeypatch.setattr(
            core_ydotool, "_dialect", core_ydotool.YDTOOL_DIALECT_LEGACY
        )
        monkeypatch.setenv("EASYSPEAK_GRID_DRY_RUN", "1")
        assert g.move_to(10, 20) == "ran"
        spawn.assert_not_called()


class TestToolListParsing:
    """Capability is read from the binary's own list, never assumed: Ubuntu's
    ydotool 0.1.8 offers five verbs and no `mousemove_relative`, so a probe
    built on an assumed verb could never pass there."""

    def test_reads_the_five_verbs_the_vm_showed(self):
        assert g.parse_tool_list(UBUNTU_HELP) == UBUNTU_VERBS

    def test_reads_the_seven_verbs_the_2604_vm_shows(self):
        """1.0.4 adds `debug` and `bakers`, and closes its help with a sentence
        *after* the list that is not a command — only the indented lines are."""
        assert g.parse_tool_list(RESOLUTE_HELP) == RESOLUTE_VERBS

    def test_an_answer_without_the_header_yields_nothing(self):
        assert (
            g.parse_tool_list("Run 'ydotool help' if you want a tools list\n") == set()
        )

    def test_only_the_lines_after_the_header_are_verbs(self):
        text = (
            "Usage: ydotool <cmd> <args>\nAvailable commands:\n  mousemove\n\n  click\n"
        )
        assert g.parse_tool_list(text) == {"mousemove", "click"}

    def test_a_trailing_sentence_is_not_a_verb(self):
        text = "Available commands:\n  click\nUse YDOTOOL_SOCKET to pick a daemon.\n"
        assert g.parse_tool_list(text) == {"click"}

    def test_a_described_verb_is_read_by_its_first_token(self):
        """Some builds append a per-verb description on the verb's own line;
        the verb is the first token, and a whole-line entry would never match
        the verbs the gate requires."""
        text = (
            "Available commands:\n"
            "  mousemove    Move the pointer\n"
            "  click 1      Press and release a button\n"
        )
        assert g.parse_tool_list(text) == {"mousemove", "click"}

    def test_the_probe_reads_the_list_from_stderr(self, monkeypatch):
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda cmd, timeout: Mock(returncode=1, stdout="", stderr=UBUNTU_HELP),
        )
        assert g._probe_tools() == UBUNTU_VERBS


class TestGate:
    def test_inert_at_import(self):
        """The import-time gate state, snapshotted before any fixture
        resets it: an import-time `_active = True` default (or a stray
        import-time assignment) fails HERE, not nowhere."""
        assert _IMPORT_TIME_ACTIVE is False

    def test_a_wedged_probe_shuts_the_gate_at_the_deadline(self, monkeypatch):
        """protects: `resolve_active` joins its probe threads on a deadline
        derived from PROBE_TIMEOUT — the threads exist exactly so a wedged
        probe cannot hold setup() hostage (the module's own stated reason for
        their existence). Mutation-proven: replacing the bounded join with an
        unbounded one keeps the whole suite green, and the failure mode is a
        daemon that hangs at every start.
        fails_when: the join blocks past the deadline, or the gate answers
        True from a late result nobody read.
        no_claim: does not claim the late thread's write is discarded
        atomically (GIL-atomic writes; the bounded overshoot residual is
        recorded in the review record).
        seam: the overlay probe blocks on an Event; PROBE_TIMEOUT is shrunk
        so the deadline is ~0.4s.
        """
        release = threading.Event()
        monkeypatch.setattr(g, "_probe_overlay", lambda: release.wait(10))
        monkeypatch.setattr(g, "_probe_injector", lambda: True)
        monkeypatch.setattr(g, "PROBE_TIMEOUT", 0.1)
        started = time.monotonic()
        try:
            assert g.resolve_active() is False
        finally:
            release.set()
        assert time.monotonic() - started < 5

    def test_cleanup_routes_to_the_selected_backend(self, monkeypatch, core):
        """protects: the atexit teardown must reach whichever backend setup()
        selected — a routing regression (always calling the extension
        backend, or reading the pre-setup default) leaves the ydotool overlay
        on screen at interpreter exit, the exact failure the registration
        exists to prevent.
        fails_when: cleanup() does not reach the selected backend's teardown.
        no_claim: does not claim the backends' own teardowns work (each is
        tested in its own suite); the dispatcher's routing is the subject.
        seam: the selected backend's cleanup is a stub.
        """
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "uinput")
        monkeypatch.setattr(g, "_probe_overlay", Mock(side_effect=AssertionError))
        monkeypatch.setattr(g, "_probe_injector", Mock(side_effect=AssertionError))
        mousegrid.setup(core)
        ydotool_cleanup = Mock()
        monkeypatch.setattr(g, "cleanup", ydotool_cleanup)
        mousegrid.cleanup()
        ydotool_cleanup.assert_called_once_with()

        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "gnome")
        extension_cleanup = Mock()
        monkeypatch.setattr(_extension, "cleanup", extension_cleanup)
        mousegrid.setup(core)
        mousegrid.cleanup()
        extension_cleanup.assert_called_once_with()

    def test_handle_routes_to_the_selected_backend(self, monkeypatch, core):
        """protects: `mousegrid.handle` is the claim entry point core calls —
        a routing regression (always the extension backend, say) sends every
        grid utterance into the wrong backend's conversation, and only
        integration arm A would notice (it skips on CI-standard runs, where
        sway and the typelib are absent). Mutation-verified in review pass 3:
        hardwiring this to `_extension.handle` kept all 2000 unit tests green.
        fails_when: the utterance does not reach the selected backend.
        no_claim: does not claim the backends' own handle decisions work
        (their suites cover them); the dispatcher's routing is the subject.
        seam: the selected backend's handle is a stub.
        """
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "uinput")
        monkeypatch.setattr(g, "_probe_overlay", Mock(side_effect=AssertionError))
        monkeypatch.setattr(g, "_probe_injector", Mock(side_effect=AssertionError))
        mousegrid.setup(core)
        ydotool_handle = Mock()
        monkeypatch.setattr(g, "handle", ydotool_handle)
        extension_handle = Mock()
        monkeypatch.setattr(_extension, "handle", extension_handle)
        assert mousegrid.handle("grid", core) is ydotool_handle.return_value
        ydotool_handle.assert_called_once_with("grid", core)
        extension_handle.assert_not_called()

        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "gnome")
        mousegrid.setup(core)
        assert mousegrid.handle("grid", core) is extension_handle.return_value
        extension_handle.assert_called_once_with("grid", core)
        ydotool_handle.assert_called_once()

    def test_forced_backend_is_active_without_probing(self, monkeypatch, core):
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "uinput")
        monkeypatch.setattr(g, "_probe_overlay", Mock(side_effect=AssertionError))
        monkeypatch.setattr(g, "_probe_injector", Mock(side_effect=AssertionError))
        mousegrid.setup(core)
        assert g._active is True
        assert mousegrid._backend is g

    def test_forced_gnome_selects_the_extension_backend(self, monkeypatch, core):
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "gnome")
        mousegrid.setup(core)
        assert g._active is False
        assert mousegrid._backend is _extension

    def test_the_help_surface_matches_the_selected_backend(self, monkeypatch, core):
        """protects: a ydotool desktop's help must not advertise the verbs
        its backend refuses — core reads plugin.COMMANDS at help time, so
        setup() rebinds it to the gate's selection.
        fails_when: the scroll/nudge/mark rows survive a uinput selection,
        or a gnome selection loses them.
        seam: none
        """
        monkeypatch.setattr(mousegrid, "_backend", mousegrid._extension)
        monkeypatch.setattr(mousegrid, "COMMANDS", mousegrid._COMMANDS_FULL)
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "uinput")
        mousegrid.setup(core)
        advertised = " ".join(mousegrid.COMMANDS)
        assert "scroll" not in advertised
        assert "nudge" not in advertised
        assert "mark" not in advertised
        assert "click" in advertised
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "gnome")
        mousegrid.setup(core)
        assert mousegrid.COMMANDS is mousegrid._COMMANDS_FULL

    def test_needs_both_halves(self, monkeypatch, core):
        monkeypatch.delenv("EASYSPEAK_GRID_BACKEND", raising=False)
        monkeypatch.setattr(g, "_probe_overlay", lambda: True)
        monkeypatch.setattr(g, "_probe_injector", lambda: False)
        mousegrid.setup(core)
        assert g._active is False
        assert mousegrid._backend is _extension
        monkeypatch.setattr(g, "_probe_overlay", lambda: False)
        monkeypatch.setattr(g, "_probe_injector", lambda: True)
        mousegrid.setup(core)
        assert g._active is False
        assert mousegrid._backend is _extension
        monkeypatch.setattr(g, "_probe_overlay", lambda: True)
        mousegrid.setup(core)
        assert g._active is True
        assert mousegrid._backend is g

    def test_an_unknown_forced_value_is_named_and_probes_run(self, monkeypatch, caplog):
        """A typo'd override ("uinpt") must not silently degrade to probing:
        the discarded value is named in the log, and the probes still decide
        the backend (the unforced path)."""
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "uinpt")
        monkeypatch.setattr(g, "_probe_overlay", lambda: False)
        monkeypatch.setattr(g, "_probe_injector", lambda: False)
        with caplog.at_level("WARNING"):
            mousegrid.setup(core)
        assert any("uinpt" in r.message for r in caplog.records)
        assert mousegrid._backend is _extension

    def test_socket_check_is_a_bare_connect_that_cannot_raise(self, monkeypatch):
        stub = Mock()
        stub.connect.side_effect = OSError("connection refused")
        monkeypatch.setattr(socket, "socket", Mock(return_value=stub))
        assert g._socket_accepts() is False
        assert stub.close.call_count == len(g.YDTOOL_SOCKET_TYPES)

    def test_socket_check_reports_the_daemon_mode(self, monkeypatch):
        monkeypatch.setattr(socket, "socket", Mock(return_value=Mock()))
        assert g._socket_accepts() is True

    def test_a_wrong_socket_type_is_not_the_same_as_no_daemon(self, monkeypatch):
        """The 26.04 shape, measured in the VM: 1.0.4's ydotoold listens on a
        datagram socket, so a stream connect fails with EPROTOTYPE ("Protocol
        wrong type for socket") — and a probe that stops there reports "no
        daemon" for a daemon that is running and answering clients."""
        asked = []

        def make(kind, stype):
            asked.append(stype)
            stub = Mock()
            if stype == socket.SOCK_STREAM:
                stub.connect.side_effect = OSError(91, "Protocol wrong type for socket")
            return stub

        monkeypatch.setattr(socket, "socket", make)
        assert g._socket_accepts("/run/user/1000/.ydotool_socket") is True
        assert asked == [socket.SOCK_STREAM, socket.SOCK_DGRAM]

    def test_a_socket_that_refuses_both_types_is_not_a_daemon(self, monkeypatch):
        asked = []

        def make(kind, stype):
            asked.append(stype)
            stub = Mock()
            stub.connect.side_effect = OSError(111, "Connection refused")
            return stub

        monkeypatch.setattr(socket, "socket", make)
        assert g._socket_accepts("/tmp/.ydotool_socket") is False
        assert asked == [socket.SOCK_STREAM, socket.SOCK_DGRAM]

    def test_the_startup_socket_call_precedes_the_helper_probe(self, monkeypatch):
        """protects: the startup bound must be the process's first discovery
        call. _probe_tools's spawn reaches _client_env, whose walk runs at the
        short per-use bound; if it walked first and failed (a just-starting
        ydotoold needs >0.25s to accept), the cooldown memory would hand the
        startup call a false "none" and the gate would fail closed on a daemon
        that was half a second late (the cooldown comment in core.ydotool is
        the contract this ordering keeps true)."""
        calls = []
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")

        def fake_socket(timeout=g.PROBE_TIMEOUT):
            calls.append(("socket", timeout))

        def fake_tools():
            calls.append(("tools",))
            # probe ends here

        # Patch in the grid module's namespace: _probe_injector resolves these
        # names through its re-export bindings, not through core's globals.
        monkeypatch.setattr(g, "injector_socket", fake_socket)
        monkeypatch.setattr(g, "_probe_tools", fake_tools)
        assert g._probe_injector() is False
        # BOTH calls recorded, socket first and under the full startup bound —
        # this sequence is what keeps the cooldown memory from swallowing the
        # startup answer.
        assert calls == [("socket", g.PROBE_TIMEOUT), ("tools",)]

    def test_injector_probe_is_portable_and_daemonless(self, monkeypatch, caplog):
        """The 0.1.8 shape: Ubuntu's five verbs, no ydotoold, a no-op that reports
        `ran` — there the socket is a logged mode, not a gate condition."""
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path=None, timeout=g.PROBE_TIMEOUT: False,
        )
        monkeypatch.setattr(core_ydotool, "_spawn", lambda cmd, timeout: _help_result())
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        with caplog.at_level("INFO"):
            assert g._probe_injector() is True
        assert seen == [["ydotool", "type", "", "--delay", "0"]]
        assert any("per-invocation" in r.message for r in caplog.records)

    def test_injector_probe_logs_the_daemon_mode_when_the_socket_answers(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            core_ydotool,
            "ydotool_socket_candidates",
            lambda: ["/run/user/1000/.ydotool_socket"],
        )
        monkeypatch.setattr(core_ydotool, "_socket_owned", lambda _path: True)
        _pin_real_resolver(monkeypatch)
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path=None, timeout=g.PROBE_TIMEOUT: True,
        )
        monkeypatch.setattr(core_ydotool, "_spawn", lambda cmd, timeout: _help_result())
        monkeypatch.setattr(g, "_run_bounded", lambda args, **k: "ran")
        with caplog.at_level("INFO"):
            assert g._probe_injector() is True
        assert any("use the daemon" in r.message for r in caplog.records)
        assert any(
            "/run/user/1000/.ydotool_socket" in r.message for r in caplog.records
        )

    def test_the_modern_probe_fails_closed_without_a_socket(self, monkeypatch, caplog):
        """1.0.4 has no per-invocation fallback: with no socket it exits 2 and
        emits nothing, so "no daemon" is "no injector" and the words must stay
        with `mousegrid`. The no-op is not even attempted — there is nothing it
        could prove."""
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path=None, timeout=g.PROBE_TIMEOUT: False,
        )
        monkeypatch.setattr(core_ydotool, "_spawn", _modern_client)
        monkeypatch.setattr(g, "_run_bounded", Mock(side_effect=AssertionError))
        with caplog.at_level("INFO"):
            assert g._probe_injector() is False
        assert any("no injector here" in r.message for r in caplog.records)

    def test_the_modern_probe_passes_with_a_socket_and_a_clean_noop(
        self, monkeypatch, caplog
    ):
        """The 26.04 shape: 1.0.4's own verb list, a daemon answering, and the
        modern no-op (`type ""`, no `--delay` to be rejected) reporting `ran`."""
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            core_ydotool,
            "ydotool_socket_candidates",
            lambda: ["/run/user/1000/.ydotool_socket"],
        )
        monkeypatch.setattr(core_ydotool, "_socket_owned", lambda _path: True)
        _pin_real_resolver(monkeypatch)
        monkeypatch.setattr(
            core_ydotool,
            "_socket_accepts",
            lambda path=None, timeout=g.PROBE_TIMEOUT: True,
        )
        monkeypatch.setattr(core_ydotool, "_spawn", _modern_client)
        seen = []
        _pin_argv_recorder(monkeypatch, seen)
        with caplog.at_level("INFO"):
            assert g._probe_injector() is True
        assert seen == [["ydotool", "type", ""]]
        assert any("use the daemon" in r.message for r in caplog.records)

    def test_injector_probe_fails_closed_without_a_verb_it_builds(self, monkeypatch):
        """Ubuntu's list minus `mousemove`: the gate must not claim the words."""
        text = "Usage: ydotool <cmd> <args>\nAvailable commands:\n  type\n  click\n"
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            core_ydotool,
            "_spawn",
            lambda cmd, timeout: Mock(returncode=1, stdout="", stderr=text),
        )
        monkeypatch.setattr(g, "_run_bounded", Mock(side_effect=AssertionError))
        assert g._probe_injector() is False

    def test_injector_probe_fails_closed_when_the_noop_reports_not_ran(
        self, monkeypatch
    ):
        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(core_ydotool, "_spawn", lambda cmd, timeout: _help_result())
        monkeypatch.setattr(g, "_run_bounded", lambda args, **k: "errored")
        assert g._probe_injector() is False

    def test_injector_probe_fails_closed_without_the_binary(self, monkeypatch):
        monkeypatch.setattr(g.shutil, "which", lambda name: None)
        assert g._probe_injector() is False

    def test_a_help_that_does_not_answer_is_no_capability(self, monkeypatch):
        import subprocess

        monkeypatch.setattr(g.shutil, "which", lambda name: f"/usr/bin/{name}")

        def boom(cmd, timeout):
            raise subprocess.TimeoutExpired(cmd="ydotool", timeout=5.0)

        monkeypatch.setattr(core_ydotool, "_spawn", boom)
        assert g._probe_injector() is False


class TestOverlayProbe:
    """The gate's overlay half is a readiness question: only an answer that says
    yes opens it, and every other answer fails closed to `mousegrid`.

    The whole plugin rests on this half: claiming the grid words on a host whose
    compositor cannot show the surface would answer "grid" with an apology while
    the extension backend was still able to serve it.
    """

    def test_the_overlay_probe_fails_closed_when_it_cannot_answer(
        self, monkeypatch, caplog
    ):
        """protects: `_probe_overlay` reports not-ready when there is no
        interpreter, when every candidate interpreter hangs, when the helper's
        `--probe` refuses, and when that probe times out - the fail-closed half
        of the gate - while a clean `--probe` still reports ready.
        fails_when: any of those answers is read as ready, a helper is probed
        without an interpreter, or a hanging candidate is chosen as the
        overlay's interpreter.
        no_claim: does not claim where the probes run (TestHelperEnv pins the
        environment) nor what a live compositor answers.
        seam: none
        """
        import subprocess

        real_grid_python = g.grid_python

        # No interpreter at all: nothing may be spawned, and the gate is shut.
        monkeypatch.setattr(g, "grid_python", lambda: None)
        runner = Mock(side_effect=AssertionError("a helper must not be probed"))
        monkeypatch.setattr(g.subprocess, "run", runner)
        with caplog.at_level("INFO"):
            assert g._probe_overlay() is False
        runner.assert_not_called()
        assert any("no interpreter" in r.message for r in caplog.records)

        # Every candidate hangs: each is skipped, none is reported as the
        # overlay's interpreter, and the helper probe is never reached.
        monkeypatch.delenv("EASYSPEAK_GRID_PYTHON", raising=False)
        monkeypatch.setattr(g, "grid_python", real_grid_python)
        asked = []

        def hang(cmd, **kwargs):
            asked.append(list(cmd))
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=5.0)

        monkeypatch.setattr(g.subprocess, "run", hang)
        with caplog.at_level("INFO"):
            assert g._probe_overlay() is False
        assert asked == [
            [candidate, "-c", g.HELPER_PROBE] for candidate in g.GRID_PYTHON_CANDIDATES
        ]

        # The helper is there and refuses: the refusal is what the log carries.
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        monkeypatch.setattr(
            g.subprocess,
            "run",
            Mock(return_value=Mock(returncode=1, stdout="unsupported\n", stderr="")),
        )
        caplog.clear()
        with caplog.at_level("INFO"):
            assert g._probe_overlay() is False
        assert any("unsupported" in r.message for r in caplog.records)

        # The helper probe itself hangs: another not-ready, never a wait.
        monkeypatch.setattr(g.subprocess, "run", hang)
        caplog.clear()
        with caplog.at_level("INFO"):
            assert g._probe_overlay() is False
        assert any("did not answer in time" in r.message for r in caplog.records)

        # Control: the clean answer still opens the gate, so the test cannot
        # pass by the probe being dead.
        monkeypatch.setattr(
            g.subprocess, "run", Mock(return_value=Mock(returncode=0, stdout=""))
        )
        assert g._probe_overlay() is True


class TestRouting:
    def test_triggers_open_the_grid(self, monkeypatch, core):
        monkeypatch.setattr(g, "_active", True)
        opened = Mock(return_value=(0, 0, 100, 100))
        monkeypatch.setattr(g, "_open_session", opened)
        assert g.handle("grid", core) is True
        assert g.handle("pointer", core) is True
        assert opened.call_count == 2

    def test_a_word_merely_containing_a_trigger_is_not_ours(self, monkeypatch, core):
        monkeypatch.setattr(g, "_active", True)
        assert g.handle("greatest", core) is None

    def test_close_outside_a_session_is_nobodys_phrase(self, monkeypatch, core):
        """protects: dismissal lives inside an open session's loop; outside
        one, a phrase that names the grid and asks to close it claims nothing.
        The old backend answered such phrases with a spoken "Grid closed" —
        parity insurance, so the two plugins never offered the same words
        twice. One plugin has no double claim to insure against, and
        confirming a closure when nothing is open would be a lie, so the
        branch is gone.
        fails_when: handle claims "close the grid" outside a session, or the
        show guard fails and the phrase opens the grid instead.
        no_claim: does not claim anything about in-session dismissals —
        TestModeDispatch's subject.
        seam: none
        """
        monkeypatch.setattr(g, "_active", True)
        opened = Mock(side_effect=AssertionError("a dismissal must not open"))
        monkeypatch.setattr(g, "_open_session", opened)
        assert g.handle("close the grid", core) is None
        opened.assert_not_called()

    def test_again_reopens_at_the_remembered_cell(self, monkeypatch, core, fake_helper):
        """protects: "again" reopens the grid on the cell a click was dispatched
        from: the remembered cell is handed to the session as its bounds, so the
        fresh open draws over that cell instead of the whole output.
        fails_when: the remembered cell is dropped (reopen at the full monitor
        because the global was assigned before `_open_session` overwrote it, or
        the bounds were never passed), or the word is not claimed.
        no_claim: does not claim the overlay's pixels; the redraw it asks for is
        asserted, not what the helper painted, and the memory is process state
        that a daemon restart clears.
        seam: none
        """
        fake_helper(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 1920, 1080]}),"
            " flush=True)\n"
            "print(json.dumps({'event': 'presented'}), flush=True)\n"
            "for _ in sys.stdin:\n"
            "    pass\n"
        )
        monkeypatch.setattr(g, "_active", True)
        monkeypatch.setattr(g, "_last_bounds", (1351, 280, 71, 40))
        drawn = []
        monkeypatch.setattr(g, "_redraw", drawn.append)
        core.listen_modal = Mock(return_value=iter([]))

        assert g.handle("again", core) is True

        assert drawn == [(1351, 280, 71, 40)]
        assert g._last_bounds == (1351, 280, 71, 40)

    def test_a_remembered_cell_that_no_longer_fits_reopens_full(
        self, monkeypatch, core, fake_helper
    ):
        """protects: the remembered cell is only reused when it still fits the
        output the FRESH session reports — a resolution change or a dock swap
        between sessions would otherwise draw it clipped and aim its click at
        the edge of the new output.
        fails_when: stale bounds are used verbatim against the new geometry,
        or a fitting cell is discarded (the memory would be useless).
        no_claim: does not claim the compositor cannot resize between the
        helper's ready and the click; the clamp is against the geometry the
        session actually opened with.
        seam: none
        """
        fake_helper(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 900, 600]}),"
            " flush=True)\n"
            "print(json.dumps({'event': 'presented'}), flush=True)\n"
            "for _ in sys.stdin:\n"
            "    pass\n"
        )
        monkeypatch.setattr(g, "_active", True)
        # A cell from a 1920x1080 session, replayed on a 900x600 output.
        monkeypatch.setattr(g, "_last_bounds", (1351, 280, 71, 40))
        drawn = []
        monkeypatch.setattr(g, "_redraw", drawn.append)
        core.listen_modal = Mock(return_value=iter([]))

        assert g.handle("again", core) is True

        assert drawn == [(0, 0, 900, 600)]
        assert g._bounds == (0, 0, 900, 600)

    def test_a_wider_dismiss_word_no_longer_blocks_the_show(
        self, monkeypatch, core, fake_helper
    ):
        """protects: the claim-boundary guard is mousegrid's own pair
        ("close"/"hide"), no wider — "grid quit" must OPEN the grid here when
        the gate passed, exactly as mousegrid opens it when the gate did not,
        or the parity promise ("one utterance lands the same whichever backend
        answers") breaks at the claim boundary.
        fails_when: the show guard excludes the whole DISMISS_WORDS set, so
        "grid quit" is answered with a spoken "Grid closed" and no grid.
        no_claim: does not claim the in-session dismissal set — the wider
        DISMISS_WORDS stays in charge inside an open session, where mousegrid
        is not listening.
        seam: none
        """
        fake_helper(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 900, 600]}),"
            " flush=True)\n"
            "for line in sys.stdin:\n"
            "    if 'show' in line:\n"
            "        print(json.dumps({'event': 'presented'}), flush=True)\n"
        )
        monkeypatch.setattr(g, "_active", True)
        opened = []
        monkeypatch.setattr(
            g, "_open_session", lambda core: opened.append(True) or None
        )
        dismissed = []
        monkeypatch.setattr(g, "_dismiss", lambda: dismissed.append(True))

        assert g.handle("grid quit", core) is True

        assert opened == [True]
        assert dismissed == []

    def test_a_subdivide_only_session_leaves_again_nothing_to_reopen(
        self, monkeypatch, core, fake_helper
    ):
        """protects: the cell "again" reopens is the one a click was dispatched
        from - walking zones without clicking records nothing, so "again" falls
        through to the other plugins (mousegrid included) rather than reopening.
        fails_when: a subdivision records the walked cell (again would reopen
        where the user last pointed, not where they last clicked), or handle
        claims "again" with nothing remembered.
        no_claim: does not claim a clicked session is the only way the memory is
        set - that path is test_again_reopens_at_the_remembered_cell's subject.
        seam: none
        """
        fake_helper(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 900, 600]}),"
            " flush=True)\n"
            "print(json.dumps({'event': 'presented'}), flush=True)\n"
            "for _ in sys.stdin:\n"
            "    pass\n"
        )
        monkeypatch.setattr(g, "_active", True)
        monkeypatch.setattr(g, "_last_bounds", None)
        core.listen_modal = Mock(return_value=iter(["3 7 5", "close"]))

        assert g.handle("grid", core) is True
        assert g._last_bounds is None

        monkeypatch.setattr(
            g,
            "_open_session",
            Mock(side_effect=AssertionError("again reopened with nothing remembered")),
        )
        assert g.handle("again", core) is None

    def test_extension_only_verbs_are_named_not_swallowed(self, monkeypatch, core):
        """protects: "scroll down" and friends match nothing this backend can
        do; the mode names the boundary out loud instead of leaving the user
        to retry a verb the desktop will never honour.
        fails_when: the utterance is answered with silence, a click, or an
        end of the mode.
        no_claim: does not claim the grid closes — the mode keeps listening.
        seam: none
        """
        monkeypatch.setattr(g, "_active", True)
        monkeypatch.setattr(g, "_dismiss", Mock())
        core.listen_modal = Mock(return_value=iter(["scroll down", "close"]))

        g._run_mode(core)

        # "scroll down" is named; the grid stays up for the "close" that ends
        # the mode — the boundary is announced, the session is not punished.
        spoken = [call.args[0] for call in core.speak.call_args_list]
        assert spoken[0] == "That needs the GNOME extension."
        assert spoken[-1] == "Grid closed"
        g._dismiss.assert_called_once()

    @pytest.mark.parametrize(
        ["utterance"],
        [
            ["scroll down 3"],
            ["mark 3"],
        ],
    )
    def test_a_count_after_an_extension_only_verb_is_not_a_zoom(
        self, monkeypatch, core, utterance
    ):
        """protects: the count suffix the COMMANDS help advertises must not
        turn a refused verb into grid navigation. The extension loop honours
        scroll and mark BEFORE the zone numbers, so this backend names the
        boundary before its zones parse runs, too.
        fails_when: the zones branch consumes the digit and subdivides.
        seam: none
        """
        monkeypatch.setattr(g, "_active", True)
        monkeypatch.setattr(g, "_dismiss", Mock())
        redraw = Mock()
        monkeypatch.setattr(g, "_redraw", redraw)
        monkeypatch.setattr(g, "_bounds", (0, 0, 900, 600))
        core.listen_modal = Mock(return_value=iter([utterance, "close"]))

        g._run_mode(core)

        redraw.assert_not_called()
        assert g._bounds == (0, 0, 900, 600)
        assert core.speak.call_args_list[0].args[0] == (
            "That needs the GNOME extension."
        )

    def test_a_verb_word_before_a_click_word_is_never_a_click(self, monkeypatch, core):
        """protects: "scroll click" must not fire a real click on this
        backend — the extension reads it as a scroll attempt, and a click
        presses whatever sits under the aimed cell.
        fails_when: click_kind claims the utterance before the verb check.
        seam: none
        """
        monkeypatch.setattr(g, "_active", True)
        monkeypatch.setattr(g, "_dismiss", Mock())
        monkeypatch.setattr(g, "move_to", Mock())
        monkeypatch.setattr(g, "click", Mock())
        core.listen_modal = Mock(return_value=iter(["scroll click", "close"]))

        g._run_mode(core)

        g.move_to.assert_not_called()
        g.click.assert_not_called()
        assert core.speak.call_args_list[0].args[0] == (
            "That needs the GNOME extension."
        )

    def test_a_click_word_with_nudge_still_clicks(self, monkeypatch, core):
        """protects: the extension honours nudge AFTER the click words, so
        this backend must not let it swallow a click utterance either —
        "click nudge" clicks on both.
        fails_when: the extension-only check runs before click_kind (the
        blind hoist of all four verb words would introduce exactly that
        divergence).
        seam: none
        """
        monkeypatch.setattr(g, "_active", True)
        monkeypatch.setattr(g, "_dismiss", Mock())
        monkeypatch.setattr(g, "_bounds", (0, 0, 900, 600))
        monkeypatch.setattr(g, "move_to", Mock(return_value="ran"))
        click = Mock(return_value="ran")
        monkeypatch.setattr(g, "click", click)
        core.listen_modal = Mock(return_value=iter(["click nudge"]))

        g._run_mode(core)

        click.assert_called_once_with("click")
        g._dismiss.assert_called_once()

    def test_unknown_input_passes_to_the_next_plugin(self, monkeypatch, core):
        monkeypatch.setattr(g, "_active", True)
        assert g.handle("open firefox", core) is None

    def test_inert_plugin_never_claims_anything(self, core):
        assert g.handle("grid", core) is None


class TestModeDispatch:
    def test_digits_subdivide_and_redraw(self, monkeypatch, core):
        calls = []
        monkeypatch.setattr(g, "_redraw", calls.append)
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["3 7 5"]))
        g._run_mode(core)
        # 3 -> (600, 0, 300, 200); 7 -> (600, 132, 100, 66); 5 -> (633, 154, 33, 22)
        assert calls[-1] == (633, 154, 33, 22)

    def test_click_moves_then_clicks_then_ends(self, monkeypatch, core):
        seen = []
        # The fakes answer in the seam's own vocabulary — a move and a click
        # that both `ran` — which is the scenario this test exercises.
        monkeypatch.setattr(
            g, "move_to", lambda x, y: seen.append(("move", x, y)) or "ran"
        )
        monkeypatch.setattr(
            g, "click", lambda button="click": seen.append(("click", button)) or "ran"
        )
        monkeypatch.setattr(g, "_dismiss", lambda: seen.append(("dismiss",)))
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["click"]))
        g._run_mode(core)
        # Centre of the whole output: (450, 300), and the cell is remembered.
        assert seen[-3:] == [("move", 450, 300), ("click", "click"), ("dismiss",)]
        assert g._last_bounds == (0, 0, 900, 600)

    def test_close_ends_the_mode_without_clicking(self, monkeypatch, core):
        monkeypatch.setattr(g, "move_to", Mock())
        monkeypatch.setattr(g, "_dismiss", Mock())
        core.listen_modal = Mock(return_value=iter(["close"]))
        g._run_mode(core)
        g.move_to.assert_not_called()
        g._dismiss.assert_called_once()

    def test_unrecognised_utterance_keeps_the_mode(self, monkeypatch, core):
        monkeypatch.setattr(g, "move_to", Mock())
        monkeypatch.setattr(g, "click", Mock())
        # `_dismiss` is stubbed as in the two tests above: the dispatch of the
        # unknown utterance is this test's subject, not the session teardown
        # its real body performs.
        monkeypatch.setattr(g, "_dismiss", Mock())
        core.listen_modal = Mock(return_value=iter(["open firefox", "close"]))
        g._run_mode(core)
        g.move_to.assert_not_called()
        g.click.assert_not_called()
        g._dismiss.assert_called_once()

    def test_unknown_outcome_speaks_the_uncertain_line(self, monkeypatch, core):
        monkeypatch.setattr(g, "move_to", lambda x, y: "unknown")
        monkeypatch.setattr(g, "click", lambda button="click": "unknown")
        monkeypatch.setattr(g, "_dismiss", Mock())
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["click"]))
        g._run_mode(core)
        assert (
            core.speak.call_args_list[-1].args[0]
            == "I tried, but I'm not sure it worked."
        )

    def test_errored_outcome_speaks_the_definite_line(self, monkeypatch, core):
        monkeypatch.setattr(g, "move_to", lambda x, y: "errored")
        monkeypatch.setattr(g, "click", lambda button="click": "errored")
        monkeypatch.setattr(g, "_dismiss", Mock())
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["click"]))
        g._run_mode(core)
        assert core.speak.call_args_list[-1].args[0] == "I couldn't move the pointer."

    def test_errored_click_after_a_ran_move_is_not_blamed_on_the_move(
        self, monkeypatch, core
    ):
        """protects: once the move ran, a click refusal is spoken as a click
        failure - "I couldn't move the pointer" named the action that
        succeeded and hid the one that didn't.
        fails_when: the click's outcome is folded back into the move's
        variable and the move failure line is spoken for a move that ran.
        no_claim: does not claim which of the two invocations the injector
        refused, only what the user is told.
        seam: none
        """
        monkeypatch.setattr(g, "move_to", Mock(return_value="ran"))
        monkeypatch.setattr(g, "click", Mock(return_value="errored"))
        monkeypatch.setattr(g, "_dismiss", Mock())
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["click"]))
        g._run_mode(core)
        g.click.assert_called_once_with("click")
        assert core.speak.call_args_list[-1].args[0] == "I couldn't click."

    def test_errored_move_does_not_click(self, monkeypatch, core):
        """protects: a move that errored is not followed by a click, the same
        `ran`-or-nothing guard the `unknown` case carries: the click is only
        fired once the move reported `ran`, so a refusal cannot land a click
        where the pointer happens to sit.
        fails_when: `_fire_click` treats anything but `unknown` as a green light
        (an errored move would click at the unproven position), or skips the
        dismissal.
        no_claim: does not claim the user hears more than the definite line, and
        does not claim where the pointer actually was.
        seam: none
        """
        monkeypatch.setattr(g, "move_to", Mock(return_value="errored"))
        monkeypatch.setattr(g, "click", Mock(return_value="ran"))
        monkeypatch.setattr(g, "double_click", Mock(return_value="ran"))
        monkeypatch.setattr(g, "_dismiss", Mock())
        monkeypatch.setattr(g, "_bounds", (0, 0, 900, 600))
        monkeypatch.setattr(g, "_last_bounds", None)
        core.listen_modal = Mock(return_value=iter(["click"]))
        g._run_mode(core)
        g.click.assert_not_called()
        g.double_click.assert_not_called()
        g._dismiss.assert_called_once()
        assert core.speak.call_args_list[-1].args[0] == "I couldn't move the pointer."

    def test_unknown_move_never_clicks(self, monkeypatch, core):
        """An unproven move must not click: a click is not idempotent and lands
        at whatever position the pointer happened to be left at."""
        monkeypatch.setattr(g, "move_to", Mock(return_value="unknown"))
        monkeypatch.setattr(g, "click", Mock(return_value="ran"))
        monkeypatch.setattr(g, "_dismiss", Mock())
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["click"]))
        g._run_mode(core)
        g.click.assert_not_called()
        assert (
            core.speak.call_args_list[-1].args[0]
            == "I tried, but I'm not sure it worked."
        )

    def test_click_outcome_replaces_a_successful_move_outcome(self, monkeypatch, core):
        """The move ran, so the click's own outcome is what the user hears."""
        monkeypatch.setattr(g, "move_to", Mock(return_value="ran"))
        monkeypatch.setattr(g, "click", Mock(return_value="unknown"))
        monkeypatch.setattr(g, "_dismiss", Mock())
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["click"]))
        g._run_mode(core)
        g.click.assert_called_once_with("click")
        assert (
            core.speak.call_args_list[-1].args[0]
            == "I tried, but I'm not sure it worked."
        )

    def test_right_click_fires_the_right_button(self, monkeypatch, core):
        seen = []
        monkeypatch.setattr(
            g, "move_to", lambda x, y: seen.append(("move", x, y)) or "ran"
        )
        monkeypatch.setattr(
            g, "click", lambda button="click": seen.append(("click", button)) or "ran"
        )
        monkeypatch.setattr(g, "_dismiss", lambda: seen.append(("dismiss",)))
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["right click"]))
        g._run_mode(core)
        assert seen == [("move", 450, 300), ("click", "right"), ("dismiss",)]

    def test_double_click_utterance_calls_double_click(self, monkeypatch, core):
        seen = []
        monkeypatch.setattr(
            g, "move_to", lambda x, y: seen.append(("move", x, y)) or "ran"
        )
        monkeypatch.setattr(
            g, "double_click", lambda: seen.append(("double_click",)) or "ran"
        )
        monkeypatch.setattr(g, "_dismiss", lambda: seen.append(("dismiss",)))
        g._bounds = (0, 0, 900, 600)
        core.listen_modal = Mock(return_value=iter(["double click"]))
        g._run_mode(core)
        assert seen == [("move", 450, 300), ("double_click",), ("dismiss",)]

    def test_a_double_click_with_a_failed_half_speaks_the_definite_line(
        self, monkeypatch, core
    ):
        """protects: a "double click" whose second click was refused ends the
        mode with the definite failure line, through the real aggregation —
        the pair carries the worst outcome by rank, so a refused gesture is
        never spoken as "not sure" while a refused single click speaks
        "I couldn't click."
        fails_when: `_fire_click` reads a partial `double_click` outcome as
        success (no speech at all), swaps in the move's outcome instead of
        the pair's, or coarsens the refused pair back to the uncertain line.
        no_claim: does not claim where the pointer sat after the first click,
        nor what the desktop received.
        seam: none
        """
        monkeypatch.setattr(g, "move_to", Mock(return_value="ran"))
        answers = iter(["ran", "errored"])
        monkeypatch.setattr(
            g, "click", lambda button="click", answers=answers: next(answers)
        )
        monkeypatch.setattr(g, "_dismiss", Mock())
        g._bounds = (0, 0, 900, 600)
        g._last_bounds = None
        core.listen_modal = Mock(return_value=iter(["double click"]))
        g._run_mode(core)
        g._dismiss.assert_called_once()
        assert core.speak.call_args_list[-1].args[0] == "I couldn't click."

    def test_click_without_bounds_does_nothing(self, monkeypatch, core):
        monkeypatch.setattr(g, "move_to", Mock())
        monkeypatch.setattr(g, "click", Mock())
        monkeypatch.setattr(g, "_dismiss", Mock())
        g._bounds = None
        g._fire_click("click", core)
        g.move_to.assert_not_called()
        g.click.assert_not_called()
        g._dismiss.assert_not_called()


class TestClickKind:
    """One click grammar for both backends (`_common.click_kind`).

    The matrix is the contract an interim suite carried and a later rename
    shrank to one case; every row here is a parity promise: the same
    utterance resolves to the same flavour whichever backend serves it.
    """

    @pytest.mark.parametrize(
        ["text", "want"],
        [
            # Plain click, including its mishears.
            ("click", "click"),
            ("clicks", "click"),
            ("lick", "click"),
            ("clique", "click"),
            # Double and middle: bare flavour words count, substrings too.
            ("double", "double"),
            ("double click", "double"),
            ("doubleclick", "double"),
            ("middle", "middle"),
            ("middle click", "middle"),
            # Right-click needs the click word beside the direction word,
            # mishears included: "write click" right-clicks on BOTH backends
            # (it left-clicked under ydotool when only the extension knew the
            # mishears).
            ("right click", "right"),
            ("write click", "right"),
            ("rite click", "right"),
            ("wright click", "right"),
            # A bare direction word is a nudge where a backend has one and
            # must never become a right-click where it does not: the two
            # grammars disagreed on exactly this before the table went
            # shared.
            ("right", None),
            ("write", None),
            ("rite", None),
            # No click anywhere.
            ("up", None),
            ("open firefox", None),
        ],
    )
    def test_each_utterance_maps_to_its_flavour(self, text, want):
        assert g.click_kind(text) == want, text

    def test_one_shared_grammar(self):
        """Identity, not equality: a backend that stops importing the shared
        resolver is the failure, not a divergence to be caught later."""
        assert g.click_kind is _extension.click_kind


class TestRedraw:
    def test_sends_the_show_command(self, monkeypatch):
        sent = []
        # `_send` is stubbed so the show payload can be asserted without a
        # helper on the other end of the pipe.
        monkeypatch.setattr(g, "_send", sent.append)
        g._redraw((0, 0, 900, 600))
        assert sent == [{"cmd": "show", "bounds": [0, 0, 900, 600]}]


class TestHelperChannel:
    def _fake_helper(self, tmp_path, script):
        path = tmp_path / "helper.py"
        path.write_text(script, encoding="utf-8")
        return str(path)

    def test_ready_then_presented_are_logged_and_geometry_returned(
        self, monkeypatch, tmp_path, caplog
    ):
        helper = self._fake_helper(
            tmp_path,
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 1920, 1080],"
            " 'scale': 1.0}), flush=True)\n"
            "print(json.dumps({'event': 'presented'}), flush=True)\n"
            "sys.stdin.readline()\n",
        )
        monkeypatch.setattr(g, "HELPER", helper)
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        with caplog.at_level("DEBUG"):
            assert g._start_helper() == (0, 0, 1920, 1080)
        g.stop_helper("test")
        assert any("ready" in r.message and "1920" in r.message for r in caplog.records)

    def test_the_handshake_never_waits_for_presented(self, monkeypatch, tmp_path):
        """protects: the first-frame wait lives after the first `show`, never in
        the ready handshake — the helper cannot announce a frame it has no
        bounds for yet, so a handshake wait would expire its whole bound on
        every single grid open.
        fails_when: the `presented` read moves back into `_start_helper` (with
        a never-presenting helper and a raised bound, the handshake then blocks
        the full timeout instead of returning immediately).
        no_claim: does not claim the announcement is consumed anywhere in
        particular; only that this function does not wait for it.
        seam: none
        """
        helper = self._fake_helper(
            tmp_path,
            "import json, sys, time\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 800, 600]}),"
            " flush=True)\n"
            "for line in sys.stdin:\n"  # never announces anything
            "    time.sleep(0.01)\n",
        )
        monkeypatch.setattr(g, "HELPER", helper)
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        monkeypatch.setattr(g, "PRESENT_TIMEOUT", 30)
        started = time.monotonic()
        assert g._start_helper() == (0, 0, 800, 600)
        assert time.monotonic() - started < 5
        g.stop_helper("test")

    def test_a_silent_helper_hits_the_deadline_and_is_reaped(
        self, monkeypatch, tmp_path
    ):
        helper = self._fake_helper(tmp_path, "import time\ntime.sleep(60)\n")
        monkeypatch.setattr(g, "HELPER", helper)
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        monkeypatch.setattr(g, "PROBE_TIMEOUT", 0.5)
        assert g._start_helper() is None
        assert g._helper is None

    def test_an_error_answer_ends_the_handshake_with_its_message(
        self, monkeypatch, tmp_path, caplog
    ):
        helper = self._fake_helper(
            tmp_path,
            "import json, sys, time\n"
            "print(json.dumps({'event': 'error',"
            " 'message': 'layer-shell unsupported'}), flush=True)\n"
            "time.sleep(60)\n",
        )
        monkeypatch.setattr(g, "HELPER", helper)
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        with caplog.at_level("WARNING"):
            assert g._start_helper() is None
        assert any("layer-shell unsupported" in r.message for r in caplog.records)

    def test_a_helper_that_dies_first_is_reaped(self, monkeypatch, tmp_path):
        helper = self._fake_helper(tmp_path, "raise SystemExit(1)\n")
        monkeypatch.setattr(g, "HELPER", helper)
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        assert g._start_helper() is None
        assert g._helper is None

    def test_a_bad_line_is_logged_and_ignored(self, monkeypatch, tmp_path):
        helper = self._fake_helper(
            tmp_path,
            "import json, sys\n"
            "print('not json at all', flush=True)\n"
            "print(json.dumps({'event': 'ready', 'monitor': [1, 2, 3, 4]}), flush=True)\n"
            "sys.stdin.readline()\n",
        )
        monkeypatch.setattr(g, "HELPER", helper)
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        assert g._start_helper() == (1, 2, 3, 4)
        g.stop_helper("test")

    def test_degenerate_geometry_is_refused_not_aimed(
        self, monkeypatch, tmp_path, caplog
    ):
        """protects: a ready event whose width or height is zero (a broken
        compositor report) is refused at the handshake — subdivide would carve
        degenerate cells out of it and every click would aim at (0, 0), spoken
        as success.
        fails_when: only the length is checked and the degenerate rectangle
        becomes the session's bounds.
        no_claim: does not claim fractional or non-int elements are refused
        separately; the same all-int check rejects them.
        seam: none
        """
        helper = self._fake_helper(
            tmp_path,
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 0, 600]}),"
            " flush=True)\n"
            "sys.stdin.readline()\n",
        )
        monkeypatch.setattr(g, "HELPER", helper)
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        with caplog.at_level("WARNING"):
            assert g._start_helper() is None
        assert g._helper is None
        assert any("no usable geometry" in r.message for r in caplog.records)


@pytest.fixture
def fake_helper(monkeypatch, tmp_path):
    """Point the plugin at a fake helper written from `script`."""

    def _point(script):
        path = tmp_path / "helper.py"
        path.write_text(script, encoding="utf-8")
        monkeypatch.setattr(g, "HELPER", str(path))
        monkeypatch.setattr(g, "grid_python", lambda: "python3")

    return _point


@pytest.fixture
def start_helper(fake_helper):
    """Run the handshake against a fake helper written from `script`."""

    def _start(script):
        fake_helper(script)
        return g._start_helper()

    return _start


class TestHelperLifecycle:
    """Closing is idempotent: every mode exit closes the session twice.

    A dismissal runs `_dismiss()` → `_close_session()`, then `_open_session`'s
    `finally` calls it again, and the same two calls happen when no helper was
    ever started.
    """

    def _ready_script(self):
        """A helper that stays up for the session, like the real one does: it
        announces `presented` only once the first `show` has been drawn — not
        at ready, because the real helper cannot know the frame reached the
        glass before it has bounds — and then serves stdin until EOF, so the
        loop-top liveness check sees it alive and the teardown paths are what
        end it."""
        return (
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 900, 600]}),"
            " flush=True)\n"
            "for line in sys.stdin:\n"
            "    if 'show' in line:\n"
            "        print(json.dumps({'event': 'presented'}), flush=True)\n"
        )

    def test_a_real_session_that_ends_on_idle_still_closes(self, core, fake_helper):
        """Nothing dismissed the grid, so `_open_session`'s `finally` is what
        has to reap the helper and drop the session."""
        fake_helper(self._ready_script())
        core.listen_modal = Mock(return_value=iter([]))
        g._open_session(core)
        assert g._helper is None
        assert [call.args[0] for call in core.speak.call_args_list] == [g._("Grid")]

    def test_a_real_session_dismisses_then_closes_again(self, core, fake_helper):
        """The production shape of the double close: `_run_mode` dismisses the
        grid, then the `finally` closes the session a second time."""
        fake_helper(self._ready_script())
        core.listen_modal = Mock(return_value=iter(["close"]))
        g._open_session(core)
        assert g._helper is None
        assert [call.args[0] for call in core.speak.call_args_list] == [
            g._("Grid"),
            g._("Grid closed"),
        ]

    def test_a_speech_failure_after_the_draw_still_closes(self, core, fake_helper):
        """protects: the show, the `presented` read and the announcement all
        run while a live helper holds the overlay on screen; a raise in that
        stretch — a TTS backend blowing up inside `core.speak` — must tear the
        session down, not leave the grid drawn with nobody to close it
        (route_command swallows the exception per plugin, so the daemon would
        have kept running with the overlay stranded until the next open or
        `atexit`).
        fails_when: the `finally` covers only `_run_mode`, so a raise between
        the first show and the mode leaves `_helper` alive.
        no_claim: does not claim anything about which speech backends can
        raise; the raise is injected.
        seam: `core.speak` raises; the helper is the real fake protocol.
        """
        fake_helper(self._ready_script())
        core.speak = Mock(side_effect=RuntimeError("tts backend died"))
        with pytest.raises(RuntimeError, match="tts backend died"):
            g._open_session(core)
        assert g._helper is None

    def test_a_helper_that_refuses_the_first_show_is_reaped_and_answered(
        self, core, fake_helper
    ):
        """protects: the `presented` read is the first consumer of a
        show-triggered refusal — the helper emits `error` and quits when the
        surface went up but the click-through region could not be applied.
        The plugin must reap the corpse, speak the failure (not "Grid"), and
        open nothing.
        fails_when: the refusal is dropped (the mode starts on a dead
        helper), the helper leaks, or "Grid" is spoken for a grid that never
        appeared.
        no_claim: does not claim which compositor states trigger the
        refusal; the helper's own contract is simulated.
        seam: none — the real fake-helper protocol carries the refusal.
        """
        fake_helper(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 900, 600]}),"
            " flush=True)\n"
            "for line in sys.stdin:\n"
            "    if 'show' in line:\n"
            "        print(json.dumps({'event': 'error', 'message':"
            " 'click-through refused'}), flush=True)\n"
            "        sys.exit(1)\n"
        )
        g._open_session(core)
        assert g._helper is None
        assert [call.args[0] for call in core.speak.call_args_list] == [
            g._("I couldn't show the grid.")
        ]

    def test_a_helper_that_dies_before_presenting_is_answered_not_announced(
        self, monkeypatch, core, fake_helper, caplog
    ):
        """protects: the `_eof` arm of the announcement read — a helper that
        dies right after ready, without ever presenting a frame, is reaped and
        answered with the refusal line, never announced as "Grid". The
        fall-through it replaces spoke success for a grid that provably never
        appeared, and the mode's own death on the next poll is silent, so the
        user heard "Grid" followed by nothing (the red-team read; the
        earlier log-only choice predates the refusal arm's reply string).
        fails_when: the fall-through returns — "Grid" is spoken and the mode
        starts on a dead helper.
        no_claim: does not claim the mid-mode death path here (a helper that
        presented first is the loop-top liveness check's row, tested below);
        the subject is the pre-present death only.
        seam: none — the real fake-helper protocol carries the death.
        """
        fake_helper(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 900, 600]}),"
            " flush=True)\n"
            "sys.stdin.readline()\n"
            "sys.exit(0)\n"
        )
        move_to = Mock()
        click = Mock()
        monkeypatch.setattr(g, "move_to", move_to)
        monkeypatch.setattr(g, "click", click)

        def utterances():
            # The fake helper exits after the first show reaches it, the way a
            # crashed helper would; make sure it has done so before the first
            # utterance would be consumed — which it never is, because the
            # mode must never start.
            assert g._helper.wait(timeout=5) == 0
            yield "click"

        core.listen_modal = Mock(return_value=utterances())
        with caplog.at_level("WARNING"):
            g._open_session(core)
        move_to.assert_not_called()
        click.assert_not_called()
        assert g._helper is None
        assert any("exited right after ready" in r.message for r in caplog.records)
        assert [call.args[0] for call in core.speak.call_args_list] == [
            g._("I couldn't show the grid.")
        ]

    def test_a_refusal_that_arrived_before_the_death_is_read_as_the_last_words(
        self, monkeypatch, core, fake_helper, caplog
    ):
        """protects: a refusal that arrived mid-mode — the click-through region
        failing on a redraw, say — is the diagnostic for the vanish, and the
        death branch reads it instead of ending the mode silently.
        fails_when: the death branch checks only `poll()` and returns, leaving
        the error line unread in the pipe (the diagnostic is lost).
        no_claim: does not claim the helper's stderr, only its structured
        protocol line; the speech stays the spec's none-for-this-path.
        seam: none
        """
        fake_helper(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 900, 600]}),"
            " flush=True)\n"
            "for line in sys.stdin:\n"
            "    if 'show' in line:\n"
            "        print(json.dumps({'event': 'presented'}), flush=True)\n"
            "        print(json.dumps({'event': 'error', 'message':"
            " 'no click-through'}), flush=True)\n"
            "        sys.exit(1)\n"
        )
        monkeypatch.setattr(g, "move_to", Mock())
        monkeypatch.setattr(g, "click", Mock())

        def utterances():
            assert g._helper.wait(timeout=5) is not None
            yield "click"

        core.listen_modal = Mock(return_value=utterances())
        with caplog.at_level("WARNING"):
            g._open_session(core)
        assert any("last words" in r.message for r in caplog.records)
        assert any("no click-through" in r.message for r in caplog.records)

    def test_closing_twice_reaps_once_and_survives_the_second_call(self, start_helper):
        assert start_helper(
            "import json, sys\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 8, 8]}), flush=True)\n"
            "sys.stdin.readline()\n",
        ) == (0, 0, 8, 8)
        helper = g._helper
        g._close_session()
        g._close_session()
        assert g._helper is None
        assert helper.poll() is not None

    def test_closing_twice_writes_one_hide(self, monkeypatch):
        stdin = io.StringIO()
        monkeypatch.setattr(g, "_helper", Mock(stdin=stdin, poll=Mock(return_value=0)))
        g._close_session()
        g._close_session()
        assert stdin.getvalue() == '{"cmd": "hide"}\n'

    def test_closing_with_nothing_running_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(g, "_helper", None)
        assert g._send({"cmd": "hide"}) is False
        g._close_session()
        g._close_session()

    def test_a_helper_that_ignores_sigterm_is_killed(
        self, monkeypatch, start_helper, caplog
    ):
        monkeypatch.setattr(g, "REAP_GRACE", 0.2)
        assert start_helper(
            "import json, signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 8, 8]}), flush=True)\n"
            "time.sleep(60)\n",
        ) == (0, 0, 8, 8)
        helper = g._helper
        with caplog.at_level("WARNING"):
            g.stop_helper("stubborn")
        assert helper.poll() is not None
        assert g._helper is None
        assert any("ignored SIGTERM" in r.message for r in caplog.records)

    def test_a_surviving_sigkill_does_not_raise(self, monkeypatch, caplog):
        """protects: the post-kill wait is bounded and its expiry is logged,
        never raised — teardown's whole purpose is to not freeze or crash,
        and an uncaught TimeoutExpired here would replace whatever was in
        flight through the mode's finally (or print a traceback at atexit).
        fails_when: stop_helper lets the second wait's TimeoutExpired escape.
        no_claim: does not claim the kernel reaps a D-state helper, only that
        the corpse is left for this process to reap at exit.
        seam: none
        """
        import subprocess

        helper = Mock()
        helper.poll.return_value = None
        helper.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="helper", timeout=0.1),
            subprocess.TimeoutExpired(cmd="helper", timeout=0.1),
        ]
        monkeypatch.setattr(g, "_helper", helper)
        with caplog.at_level("WARNING"):
            g.stop_helper("unstoppable")
        helper.kill.assert_called_once()
        assert any("survived SIGKILL" in r.message for r in caplog.records)
        assert g._helper is None

    @pytest.mark.parametrize(
        "exc",
        [
            BrokenPipeError("the helper is gone"),
            # The ValueError arm covers writing or flushing a stream that was
            # already closed (the wrapper's own close, or interpreter GC).
            ValueError("I/O operation on closed file"),
        ],
        ids=["broken-pipe", "closed-stream"],
    )
    def test_a_failed_write_swallows_the_command(self, monkeypatch, caplog, exc):
        """A helper that died between the handshake and a command is not a
        crash: the write fails, the line is dropped, the log says so, and the
        dead stream is closed so the undelivered line is not re-flushed - and
        reported as an ignored exception - when the wrapper is collected."""
        stdin = Mock()
        stdin.write.side_effect = exc
        monkeypatch.setattr(g, "_helper", Mock(stdin=stdin, poll=Mock(return_value=1)))
        with caplog.at_level("WARNING"):
            assert g._send({"cmd": "hide"}) is False
        # The log names the drop, not the exception class.
        assert any("the helper is gone" in r.message for r in caplog.records)
        stdin.close.assert_called_once_with()


class TestHelperStartFailures:
    def test_no_interpreter_means_no_helper(self, monkeypatch):
        spawn = Mock()
        monkeypatch.setattr(g, "grid_python", lambda: None)
        monkeypatch.setattr(g.subprocess, "Popen", spawn)
        assert g._start_helper() is None
        spawn.assert_not_called()

    def test_a_helper_that_cannot_spawn_is_logged(self, monkeypatch, caplog):
        monkeypatch.setattr(g, "grid_python", lambda: "python3")
        monkeypatch.setattr(g.subprocess, "Popen", Mock(side_effect=OSError("gone")))
        with caplog.at_level("WARNING"):
            assert g._start_helper() is None
        assert g._helper is None
        assert any("could not start" in r.message for r in caplog.records)

    def test_a_ready_event_without_geometry_is_refused(self, start_helper, caplog):
        with caplog.at_level("WARNING"):
            assert (
                start_helper(
                    "import json, time\n"
                    "print(json.dumps({'event': 'ready', 'monitor': []}), flush=True)\n"
                    "time.sleep(60)\n",
                )
                is None
            )
        assert g._helper is None
        assert any("no usable geometry" in r.message for r in caplog.records)

    def test_an_event_before_ready_is_logged_and_skipped(self, start_helper, caplog):
        with caplog.at_level("DEBUG"):
            assert start_helper(
                "import json, sys\n"
                "print(json.dumps({'event': 'presented'}), flush=True)\n"
                "print(json.dumps({'event': 'ready', 'monitor': [0, 0, 10, 10]}),"
                " flush=True)\n"
                "sys.stdin.readline()\n",
            ) == (0, 0, 10, 10)
        assert any("presented" in r.message for r in caplog.records)
        g.stop_helper("test")

    def test_open_session_speaks_when_the_helper_cannot_start(self, monkeypatch, core):
        monkeypatch.setattr(g, "_start_helper", lambda: None)
        g._open_session(core)
        core.speak.assert_called_once_with("I couldn't show the grid.")


class TestReadUntil:
    def test_a_deadline_that_has_passed_gives_up(self, tmp_path):
        path = tmp_path / "stream"
        path.write_text("", encoding="utf-8")
        with path.open() as stream:
            assert g.read_until(stream, 0) is None

    def test_a_stream_that_cannot_be_polled_gives_up(self):
        stream = Mock()
        stream.fileno.side_effect = ValueError("closed")
        assert g.read_until(stream, time.monotonic() + 1) is None

    def test_a_non_object_json_line_is_skipped_not_returned(self, tmp_path, caplog):
        """protects: every caller asks `.get("event")` on what this returns;
        a bare JSON number or string parses but is not an event, and returning
        one would raise AttributeError mid-handshake — in `_start_helper` that
        escape lands after `Popen` and before any `stop_helper`, leaking the
        child. A protocol line is an object or it is noise.
        fails_when: `json.loads`' result is returned unchecked.
        no_claim: does not claim the shipped helper can produce such a line
        (it only emits objects); the guard makes the contract total for any
        helper this module is pointed at.
        seam: none — a real file stream carries the lines.
        """
        path = tmp_path / "stream"
        path.write_text('42\n"stray"\n{"event": "ready"}\n', encoding="utf-8")
        with caplog.at_level("WARNING"), path.open() as stream:
            assert g.read_until(stream, time.monotonic() + 5) == {"event": "ready"}
        assert any("non-object protocol line" in r.message for r in caplog.records)


def _overlay_module():
    """Import the helper without importing gi: the module defers that import so
    the daemon's venv can test its pure parts."""
    path = Path(g.__file__).with_name("_overlay.py")
    spec = importlib.util.spec_from_file_location("grid_overlay", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestOverlayPureParts:
    def test_grid_metrics_mirrors_the_extension_helper(self):
        overlay = _overlay_module()
        m = overlay.grid_metrics((0, 0, 900, 600))
        assert m["cell_w"] == 300 and m["cell_h"] == 200
        assert m["font_size"] == 66
        assert m["cells"][0] == (1, 117.0, 67.0)
        assert m["cells"][8] == (9, 717.0, 467.0)
        assert len(m["cells"]) == 9

    def test_parse_command_accepts_show_and_hide(self):
        overlay = _overlay_module()
        assert overlay.parse_command('{"cmd": "hide"}') == {"cmd": "hide"}
        assert overlay.parse_command("") is None
        assert overlay.parse_command("{oops") is None
        # A parsable non-object line is noise, not a command: handle_line asks
        # `.get("cmd")` on whatever this returns, so returning the bare payload
        # would raise AttributeError inside the GLib stdin watch and strand the
        # live helper — the helper-side twin of read_until's non-object guard.
        assert overlay.parse_command("42") is None
        assert overlay.parse_command('"stray"') is None

    def test_usable_bounds_absorbs_a_malformed_show(self):
        """protects: one malformed show message must not take the stdin watch
        (and the mapped grid) down with a KeyError — parse_command absorbs
        unparsable lines, and a parsable line without usable bounds gets the
        same treatment. The integers-only rule mirrors the ready event's own
        geometry sanity test.
        fails_when: handle_line indexes command["bounds"] unguarded, or the
        predicate accepts non-integer or wrongly-shaped bounds.
        no_claim: does not claim the parent cannot send garbage, only that
        the helper survives it.
        seam: none
        """
        overlay = _overlay_module()
        assert overlay.usable_bounds({"cmd": "show"}) is None
        assert overlay.usable_bounds({"cmd": "show", "bounds": [1, 2, 3]}) is None
        assert overlay.usable_bounds({"cmd": "show", "bounds": "1024x768"}) is None
        assert overlay.usable_bounds({"cmd": "show", "bounds": [1, 2, 3, True]}) is None
        assert overlay.usable_bounds({"cmd": "show", "bounds": [1, 2, 3, 4]}) == [
            1,
            2,
            3,
            4,
        ]

    def test_take_lines_splits_every_complete_line_of_one_chunk(self):
        """A `stop` behind another command in the same write must arrive too."""
        overlay = _overlay_module()
        lines, remainder = overlay.take_lines("", '{"cmd": "hide"}\n{"cmd": "stop"}\n')
        assert lines == ['{"cmd": "hide"}', '{"cmd": "stop"}']
        assert remainder == ""

    def test_take_lines_carries_a_partial_line_into_the_next_chunk(self):
        overlay = _overlay_module()
        lines, remainder = overlay.take_lines("", '{"cmd": "hi')
        assert lines == []
        assert remainder == '{"cmd": "hi'
        lines, remainder = overlay.take_lines(remainder, 'de"}\n{"cmd":')
        assert lines == ['{"cmd": "hide"}']
        assert remainder == '{"cmd":'

    def test_the_module_imports_without_gi(self):
        assert _overlay_module() is not None


class TestOverlaySurfaceSpace:
    """Drawing happens in the surface's own space, never in compositor-global
    coordinates.

    The plugin sends monitor-local bounds (D6) and adds the monitor origin only
    at injection time. An earlier revision also subtracted that origin when
    painting, which moved the grid and its digits off the visible surface on
    any output whose origin was not (0, 0) - clicks still landed correctly, so
    a single-output render could never show it. The drawing is bounds-local by
    construction and the helper carries no origin state at all; the draw test
    pins what actually reaches cairo.
    """

    def test_the_draw_callback_paints_the_bounds_not_the_monitor(self, monkeypatch):
        """The production callback: the first rectangle is the wash over the
        bounds (never the monitor's size), the divider bars sit on the thirds,
        and the last four rectangles are the centre crosshair - white outline
        pair, then red pair."""
        overlay = _overlay_module()
        cr = Mock()
        cr.text_extents.return_value = types.SimpleNamespace(
            width=10.0, height=24.0, x_bearing=1.0, y_bearing=2.0
        )
        # The host venv has no pycairo (the daemon's doesn't either - the file
        # documents that); _draw only reads the font-weight constants from it.
        monkeypatch.setitem(
            sys.modules,
            "cairo",
            types.SimpleNamespace(FONT_SLANT_NORMAL=0, FONT_WEIGHT_BOLD=1),
        )
        drawer = object.__new__(overlay.Overlay)
        drawer.bounds = (0, 0, 900, 600)
        drawer.presented = True  # no `presented` emit: this is not a live run
        assert not hasattr(drawer, "origin")  # D6: no origin state left to misuse
        drawer._draw(Mock(), cr, 1920, 1080)

        rects = [call.args for call in cr.rectangle.call_args_list]
        assert rects[0] == (0, 0, 900, 600)  # the wash covers the bounds only
        assert rects[1:5] == [
            (299, 0, 3, 600),
            (599, 0, 3, 600),
            (0, 199, 900, 3),
            (0, 399, 900, 3),
        ]
        assert rects[-4:] == [
            (423, 296, 54, 8),  # white outline, horizontal
            (446, 273, 8, 54),  # white outline, vertical
            (425, 298, 50, 4),  # red cross, horizontal
            (448, 275, 4, 50),  # red cross, vertical
        ]

        alphas = [call.args for call in cr.set_source_rgba.call_args_list]
        assert alphas[0] == (0.0, 0.0, 0.0, 0.15)  # the extension's faint wash
        assert (0.05, 0.05, 0.08, 0.55) not in alphas  # the old full dim is gone
        assert alphas.count((0.0, 0.0, 0.0, 0.8)) == 9  # one badge per cell
        assert alphas[-2:] == [(1.0, 1.0, 1.0, 1.0), (1.0, 0.0, 0.0, 1.0)]

        assert cr.set_font_size.call_args.args == (66,)  # floor(200/3), unclamped
        # ("Sans", FONT_SLANT_NORMAL, FONT_WEIGHT_BOLD) in cairo's own constants
        assert cr.select_font_face.call_args.args == ("Sans", 0, 1)
        assert [call.args[0] for call in cr.show_text.call_args_list] == [
            str(num) for num in range(1, 10)
        ]
        # First badge baseline: label (117, 67) offset by padding minus bearing
        assert cr.move_to.call_args_list[0].args == (132.0, 73.0)


class TestOverlayGridFace:
    """The numeric face of the grid, pinned against the extension's JavaScript.

    `grid_metrics` mirrors `gridGeometry()` (extension-helpers.js) and the
    drawing constants mirror grid.js's CSS. The two implementations live on
    opposite sides of a language boundary, so identity is impossible — these
    literals ARE the contract: when the extension's face changes, recompute
    them from the JS and the mirror follows.
    """

    def test_grid_geometry_matches_the_extension_helper(self):
        overlay = _overlay_module()
        m = overlay.grid_metrics((0, 0, 1920, 1080))
        assert (m["cell_w"], m["cell_h"]) == (640, 360)
        assert m["font_size"] == 72  # floor(360/3) = 120, clamped to 72
        assert m["center"] == (960, 540)
        assert m["cross_size"] == 50  # min(50, 360)
        assert m["cells"][0] == (1, 284.0, 144.0)  # 0 + 320 - 36, 0 + 180 - 36
        assert m["cells"][8] == (9, 1564.0, 864.0)

    def test_the_experiment_rect_maps_like_the_extension(self):
        overlay = _overlay_module()
        m = overlay.grid_metrics((318, 239, 387, 290))
        assert (m["cell_w"], m["cell_h"]) == (129, 96)
        assert m["font_size"] == 32
        assert m["center"] == (511, 384)
        assert m["cross_size"] == 50  # min(50, 96)
        assert m["cells"][0] == (1, 366.5, 271.0)

    def test_the_font_size_clamps_at_the_floor_for_deep_cells(self):
        """The lower clamp is production-reachable at exactly the cell the
        live harness aims at (1920x1080 depth 3: 71x40 -> 71//3//3 = 7); a
        `max(0, ...)` mutation would draw unreadable digits while every other
        font assertion stays green."""
        overlay = _overlay_module()
        assert overlay.grid_metrics((0, 0, 71, 40))["font_size"] == 24

    def test_the_centre_formula_never_drifts_from_common(self):
        """`_overlay` must stay import-standalone (it runs as a bare script
        under an interpreter without the package), so the centre is mirrored
        rather than imported — this pins the mirror to the original."""
        overlay = _overlay_module()
        for bounds in [
            (0, 0, 900, 600),
            (318, 239, 387, 290),
            (0, 0, 1919, 1079),
            (5, 7, 101, 53),
            (1, 1, 2, 2),
        ]:
            assert overlay.grid_metrics(bounds)["center"] == _common.center(bounds)

    def test_the_cell_thirds_match_common_subdivide(self):
        """The overlay's cell thirds and the plugin's zoom thirds must stay
        the same thirds: one utterance has to land on the same pixel whose
        badge the user aimed at."""
        overlay = _overlay_module()
        for bounds in [(0, 0, 900, 600), (318, 239, 387, 290)]:
            m = overlay.grid_metrics(bounds)
            _, _, width, height = _common.subdivide(bounds, 9)
            assert (m["cell_w"], m["cell_h"]) == (width, height)


class TestOverlayLibraryLookup:
    """The runtime ships only the soname; the unversioned `.so` is `-dev`-only.

    Ubuntu 25.10's `libgtk4-layer-shell0` installs `libgtk4-layer-shell.so.0`
    (-> `.so.1.0.4`) and nothing unversioned, so `CDLL("libgtk4-layer-shell.so")`
    refuses everywhere the library is merely installed. The chain resolves the
    soname through the loader's own cache and keeps the plain name for an
    uninstalled build tree on `LD_LIBRARY_PATH`. A `find_library` result is
    trusted only when it names this library, because it reports the soname
    *inside* the file that spelled the name.
    """

    def test_the_chain_ends_at_the_soname_and_the_plain_name(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        assert overlay.layer_shell_names() == [
            "libgtk4-layer-shell.so.0",
            "libgtk4-layer-shell.so",
        ]

    def test_the_chain_prefers_what_find_library_resolves(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setattr(
            ctypes.util, "find_library", lambda name: "libgtk4-layer-shell.so.0"
        )
        assert overlay.layer_shell_names() == [
            "libgtk4-layer-shell.so.0",
            "libgtk4-layer-shell.so",
        ]

    def test_a_result_that_names_another_library_is_not_trusted(self, monkeypatch):
        """`find_library` answers with the soname embedded in the file it found,
        never a made-up one: a copy of libm under the name
        `libgtk4-layer-shell.so` answers `libm.so.6`, and trusting it would make
        the loader preload libm while the link order the CDLL exists for is
        silently lost."""
        overlay = _overlay_module()
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: "libm.so.6")
        assert overlay.layer_shell_names() == [
            "libgtk4-layer-shell.so.0",
            "libgtk4-layer-shell.so",
        ]

    def test_load_walks_the_chain_until_a_name_loads(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setattr(
            ctypes.util, "find_library", lambda name: "libgtk4-layer-shell.so.99"
        )
        attempts = []

        def cdll(name):
            attempts.append(name)
            if name != "libgtk4-layer-shell.so.0":
                msg = f"{name}: cannot open shared object file"
                raise OSError(msg)
            return Mock()

        monkeypatch.setattr(ctypes, "CDLL", cdll)
        overlay.load_layer_shell()
        assert attempts == [
            "libgtk4-layer-shell.so.99",
            "libgtk4-layer-shell.so.0",
        ]

    def test_a_host_with_only_the_versioned_soname_loads_it(self, monkeypatch):
        """The VM shape: `libgtk4-layer-shell0` installs only `.so.0`, which
        find_library resolves through the loader's cache. A chain reduced to the
        single hardcoded plain name would try `.so`, fail, and refuse where the
        library is installed."""
        overlay = _overlay_module()
        monkeypatch.setattr(
            ctypes.util, "find_library", lambda name: "libgtk4-layer-shell.so.0"
        )
        attempts = []

        def cdll(name):
            attempts.append(name)
            if name != "libgtk4-layer-shell.so.0":
                msg = f"{name}: cannot open shared object file"
                raise OSError(msg)
            return Mock()

        monkeypatch.setattr(ctypes, "CDLL", cdll)
        overlay.load_layer_shell()
        assert attempts == ["libgtk4-layer-shell.so.0"]

    def test_load_never_opens_a_name_meant_for_another_library(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: "libm.so.6")
        attempts = []

        def cdll(name):
            attempts.append(name)
            msg = f"{name}: cannot open shared object file"
            raise OSError(msg)

        monkeypatch.setattr(ctypes, "CDLL", cdll)
        assert overlay.load_layer_shell() == (None, None)
        assert attempts == [
            "libgtk4-layer-shell.so.0",
            "libgtk4-layer-shell.so",
        ]

    def test_load_reaches_the_plain_name_of_an_uninstalled_build(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        attempts = []

        def cdll(name):
            attempts.append(name)
            if name != "libgtk4-layer-shell.so":
                msg = f"{name}: cannot open shared object file"
                raise OSError(msg)
            return Mock()

        monkeypatch.setattr(ctypes, "CDLL", cdll)
        overlay.load_layer_shell()
        assert attempts == [
            "libgtk4-layer-shell.so.0",
            "libgtk4-layer-shell.so",
        ]

    def test_the_refusal_names_every_candidate(self, monkeypatch, capsys):
        overlay = _overlay_module()
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        monkeypatch.setattr(ctypes, "CDLL", Mock(side_effect=OSError("absent")))
        assert overlay.load_layer_shell() == (None, None)
        err = capsys.readouterr().err
        assert "libgtk4-layer-shell.so.0" in err
        assert "libgtk4-layer-shell.so" in err

    def test_lib_path_returns_the_first_loadable_name(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        monkeypatch.setattr(ctypes, "CDLL", lambda name: name)
        assert overlay.layer_shell_lib_path() == "libgtk4-layer-shell.so.0"

    def test_lib_path_walks_to_a_later_name(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)

        def cdll(name):
            if name != "libgtk4-layer-shell.so":
                msg = f"{name}: cannot open shared object file"
                raise OSError(msg)
            return name

        monkeypatch.setattr(ctypes, "CDLL", cdll)
        assert overlay.layer_shell_lib_path() == "libgtk4-layer-shell.so"

    def test_lib_path_answers_none_when_nothing_loads(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        monkeypatch.setattr(ctypes, "CDLL", Mock(side_effect=OSError("absent")))
        assert overlay.layer_shell_lib_path() is None

    def test_lib_path_resolves_inside_the_build_tree(self, monkeypatch, tmp_path):
        """A build tree named by EASYSPEAK_GRID_TYPELIB is invisible to this
        process's loader (LD_LIBRARY_PATH is read once at start, and the path
        is being constructed for the child), so the sonames must be resolved
        in the tree directly — without any CDLL probe."""
        overlay = _overlay_module()
        (tmp_path / "libgtk4-layer-shell.so.0").write_bytes(b"")
        (tmp_path / "libgtk4-layer-shell.so").write_bytes(b"")
        monkeypatch.setattr(
            ctypes, "CDLL", Mock(side_effect=AssertionError("must not probe"))
        )
        assert overlay.layer_shell_lib_path(str(tmp_path)) == str(
            tmp_path / "libgtk4-layer-shell.so"
        )

    def test_lib_path_falls_back_when_the_build_tree_has_no_library(
        self, monkeypatch, tmp_path
    ):
        overlay = _overlay_module()
        (tmp_path / "README").write_text("not a build tree", encoding="utf-8")
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        monkeypatch.setattr(ctypes, "CDLL", lambda name: name)
        assert overlay.layer_shell_lib_path(str(tmp_path)) == "libgtk4-layer-shell.so.0"


class TestOverlaySupportProbe:
    """`is_supported` must give the compositor's globals a chance to arrive.

    `gtk4_layer_shell_is_supported()` reads the default display; before the main
    context has run, the Wayland registry is not yet known and a compositor that
    supports layer shell still answers false (measured live on sway: the probe
    refused until the context iterations were added). And `Gtk.init` must not be
    tested for truthiness — PyGObject maps the void function to None, so
    `if not Gtk.init()` refused on every compositor.
    """

    @staticmethod
    def _fake_gi(monkeypatch, iteration, display):
        """A stand-in for gi.repository: GLib with the scripted main context and
        Gdk with the scripted display, reached by is_supported's own import."""
        glib = Mock()
        glib.MainContext.default.return_value.iteration.side_effect = iteration
        gdk = Mock()
        gdk.Display.get_default.return_value = display
        gi = types.ModuleType("gi")
        repository = types.ModuleType("gi.repository")
        repository.GLib = glib
        repository.Gdk = gdk
        gi.repository = repository
        monkeypatch.setitem(sys.modules, "gi", gi)
        monkeypatch.setitem(sys.modules, "gi.repository", repository)
        return glib, gdk

    def test_supported_once_the_compositor_answers(self, monkeypatch):
        overlay = _overlay_module()
        stack = (Mock(), Mock(is_supported=Mock(return_value=True)))
        monkeypatch.setattr(overlay, "load_layer_shell", lambda: stack)
        self._fake_gi(monkeypatch, iteration=lambda **kwargs: False, display=Mock())
        assert overlay.is_supported() is True

    def test_refuses_when_no_display_opens(self, monkeypatch):
        overlay = _overlay_module()
        stack = (Mock(), Mock(is_supported=Mock(return_value=True)))
        monkeypatch.setattr(overlay, "load_layer_shell", lambda: stack)
        self._fake_gi(monkeypatch, iteration=lambda **kwargs: False, display=None)
        assert overlay.is_supported() is False

    def test_the_wait_is_bounded(self, monkeypatch):
        """A compositor that never answers fails closed instead of hanging the
        gate, and the compositor is never asked after the deadline."""
        overlay = _overlay_module()
        layer_shell = Mock(is_supported=Mock(return_value=False))
        monkeypatch.setattr(overlay, "load_layer_shell", lambda: (Mock(), layer_shell))
        self._fake_gi(monkeypatch, iteration=lambda **kwargs: False, display=Mock())
        ticks = iter([0.0, 3.0])  # deadline read, then a check past it
        monkeypatch.setattr(overlay.time, "monotonic", lambda: next(ticks))
        assert overlay.is_supported() is False
        layer_shell.is_supported.assert_not_called()


class TestOverlayServePath:
    """`main` without `--probe`: refuse rather than degrade, then hand over.

    The refusal is the counterpart of the plugin's handshake: a silent window
    would look like a rendering bug while the injections kept working.
    """

    def test_refuses_with_an_error_event_without_the_library(self, monkeypatch, capsys):
        overlay = _overlay_module()
        monkeypatch.setattr(overlay, "load_layer_shell", lambda: (None, None))
        assert overlay.main([]) == 1
        assert json.loads(capsys.readouterr().out.strip()) == {
            "event": "error",
            "message": "PyGObject or the layer-shell typelib is missing",
        }

    def test_refuses_when_layer_shell_is_unsupported(self, monkeypatch, capsys):
        overlay = _overlay_module()
        monkeypatch.setattr(overlay, "load_layer_shell", lambda: (Mock(), Mock()))
        monkeypatch.setattr(overlay, "is_supported", lambda: False)
        assert overlay.main([]) == 1
        assert json.loads(capsys.readouterr().out.strip()) == {
            "event": "error",
            "message": "layer-shell unsupported",
        }

    def test_the_serve_path_never_asks_the_raw_library_call(self, monkeypatch):
        """The serve path is a fresh process: the raw `layer_shell.is_supported()`
        skips Gtk.init and the registry wait, so main() must gate on the same
        full support path the probe uses, even when the raw answer is False."""
        overlay = _overlay_module()
        stack = (Mock(), Mock(is_supported=Mock(return_value=False)))
        monkeypatch.setattr(overlay, "load_layer_shell", lambda: stack)
        monkeypatch.setattr(overlay, "is_supported", lambda: True)
        run = Mock(return_value=7)
        monkeypatch.setattr(overlay, "run", run)
        assert overlay.main([]) == 7
        stack[1].is_supported.assert_not_called()

    def test_hands_a_supported_stack_to_run(self, monkeypatch):
        overlay = _overlay_module()
        stack = (Mock(), Mock(is_supported=Mock(return_value=True)))
        run = Mock(return_value=7)
        monkeypatch.setattr(overlay, "load_layer_shell", lambda: stack)
        monkeypatch.setattr(overlay, "is_supported", lambda: True)
        monkeypatch.setattr(overlay, "run", run)
        assert overlay.main([]) == 7
        run.assert_called_once_with(*stack)


class TestOverlayLoadGuard:
    """A loadable library must not turn a missing PyGObject into a traceback.

    That shape is exactly the daemon's venv with the library findable on the
    loader path: the reviewer reproduced it with a dummy `libgtk4-layer-shell.so`
    and `--probe` died inside `load_layer_shell` before it could answer
    `unsupported`, skipping every caller's error path.
    """

    @staticmethod
    def _library_loads(monkeypatch):
        monkeypatch.setattr(ctypes, "CDLL", lambda name: Mock())
        monkeypatch.setitem(sys.modules, "gi", None)

    def test_load_layer_shell_reports_the_missing_pygobject(self, monkeypatch, capsys):
        self._library_loads(monkeypatch)
        overlay = _overlay_module()
        assert overlay.load_layer_shell() == (None, None)
        assert "PyGObject" in capsys.readouterr().err

    def test_probe_answers_unsupported_instead_of_dying(self, monkeypatch, capsys):
        self._library_loads(monkeypatch)
        overlay = _overlay_module()
        assert overlay.main(["--probe"]) == 1
        assert capsys.readouterr().out.strip() == "unsupported"


class TestOverlayClickThrough:
    """The empty input region is the pass-through mechanism: apply it or refuse.

    Measured on this stack (GTK 4.6.9, two stacked windows, an XTest click):
    with `set_can_target(False)` alone the click is swallowed - neither window
    receives it - while an empty input region lets the window below receive it.
    The feature is a click injected while the pointer is over the surface, so a
    surface that cannot be made click-through has to surface as an error, never
    as a grid that silently eats its own click.
    """

    def test_the_surface_gets_an_empty_region(self, monkeypatch):
        overlay = _overlay_module()

        class FakeRegion:
            pass

        monkeypatch.setitem(
            sys.modules, "cairo", types.SimpleNamespace(Region=FakeRegion)
        )
        surface = Mock()
        assert overlay.clear_input_region(surface) is None
        region = surface.set_input_region.call_args.args[0]
        assert isinstance(region, FakeRegion)

    def test_missing_pycairo_is_a_diagnostic_not_a_traceback(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setitem(sys.modules, "cairo", None)
        surface = Mock()
        problem = overlay.clear_input_region(surface)
        assert "input region" in problem
        surface.set_input_region.assert_not_called()

    def test_a_surface_that_rejects_the_region_is_a_diagnostic(self, monkeypatch):
        overlay = _overlay_module()
        monkeypatch.setitem(
            sys.modules, "cairo", types.SimpleNamespace(Region=lambda: None)
        )
        surface = Mock()
        surface.set_input_region.side_effect = TypeError("no foreign struct converter")
        problem = overlay.clear_input_region(surface)
        assert "input region" in problem
