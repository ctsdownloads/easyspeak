"""The mousegrid ydotool backend's end-to-end loop, in a headless sway session.

Checks: a failed injector probe keeps `mousegrid` in charge (no privileges
needed), the injector gate passes on a real ydotool where an answered daemon
socket lets it inject (ydotool 1.0.x has no per-invocation fallback, so there a
socket is the only injector there is; 0.1.8 also works daemonless), the gate
fails closed on 1.0.x when no socket answers, the overlay renders and the argv
is exact under a forced backend (the dry-run arm, which is the arm CI can run),
and, only when EASYSPEAK_GRID_LIVE=click is set, that a click lands where the
grid aimed it.

Prerequisites, in one place: `sway`, `ydotool` and `grim` on `PATH`; an
interpreter with PyGObject and the gtk4-layer-shell typelib for the helper and
the probe window — the packaged library (`libgtk4-layer-shell0` with
`gir1.2-gtk4layershell-1.0`) is all a distro that carries it needs to offer,
and where it does not, `EASYSPEAK_GRID_TYPELIB` names an uninstalled build
tree's `src` directory (the harness exports it as both `GI_TYPELIB_PATH` and
`LD_LIBRARY_PATH`) or `EASYSPEAK_GRID_PYTHON` an interpreter that already has
the stack; and a running `ydotoold` for the gate's passing shape on 1.0.x
(where the daemon ships inside the `ydotool` package), while 0.1.8 works
daemonless. Setup and daemon installation: docs/troubleshooting.md. The other
variable the harness reads is `EASYSPEAK_GRID_BACKEND=uinput`, which the
harness sets itself to force the backend active without probing a daemon.

The literal in the live arm is hand-computed. Deriving it with the same algorithm
the plugin uses would make the assertion agree with any shared off-by-one, so the
premise (a pinned 1920x1080 output) is asserted first and the algorithmic
prediction is kept only as a cross-check.

The live arm injects through `ydotool`, which is kernel-global: even inside
this session, arm B moves the real cursor and clicks wherever it aims on the
live desktop. That is why it is opt-in.

A failing live arm attributes itself. It proves the probe window rendered before
anything is injected, and a press that never arrives is reported together with
what the compositor had as input, so "no seat to route the click", "nothing to
click on" and "a swallowed click" cannot be mistaken for one another.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from easyspeak.core import ydotool as core_ydotool
from easyspeak.plugins import mousegrid
from easyspeak.plugins.mousegrid import _ydotool as backend

SWAY_CONFIG = """\
output HEADLESS-1 mode 1920x1080
input * {
    accel_profile flat
}
"""

# For 1920x1080 and the sequence 3 7 5: zone 3 -> (1280, 0, 640, 360),
# zone 7 -> (1280, 240, 213, 120), zone 5 -> (1351, 280, 71, 40).
EXPECTED_CELL = (1351, 280, 71, 40)
EXPECTED_TOLERANCE = 10  # a quarter of the cell's smaller dimension, 40


@pytest.fixture(autouse=True)
def _fresh_backend_state(monkeypatch):
    """The gate tests exercise the backend's real module state machine, so
    reset it around every test: a failed injector probe records a discovery
    failure whose 1s cooldown would otherwise short-circuit the next test's
    resolver into a false skip, and setup() rebinds the dispatcher's globals.
    The same discipline the unit suite's `_fresh_client_state` enforces."""
    # The dialect cache and the socket-discovery state moved to the core run
    # seam; the moved functions resolve that state in core's globals, so the
    # reset has to land THERE (the grid's re-exports are read-only aliases).
    monkeypatch.setattr(core_ydotool, "_dialect", None)
    monkeypatch.setattr(backend, "_active", False)
    monkeypatch.setattr(core_ydotool, "_socket_last_good", None)
    monkeypatch.setattr(core_ydotool, "_socket_last_good_env", None)
    monkeypatch.setattr(core_ydotool, "_socket_search_failed", None)
    monkeypatch.setattr(backend, "_grid_python", None)
    monkeypatch.setattr(backend, "_grid_python_override", None)
    monkeypatch.setattr(backend, "_grid_python_found", False)
    monkeypatch.setattr(mousegrid, "_backend", mousegrid._extension)
    monkeypatch.setattr(mousegrid, "COMMANDS", mousegrid._COMMANDS_FULL)


def _missing_prerequisite():
    """What stops the harness from running here, or None when nothing does.

    Three binaries are not enough on their own: the helper and the probe window
    both need an interpreter that can load PyGObject and the gtk4-layer-shell
    typelib. The typelib is the prerequisite that is easy to forget and
    expensive to misread. gtk4-layer-shell is not packaged on every distro, so
    the reference setup is an uninstalled build tree, and a helper that cannot
    load the typelib fails its handshake as a GI error rather than as "the build
    path is missing". The interpreter is checked through the plugin's own
    resolver, so the harness needs exactly what the helper needs: a probe of one
    interpreter would report the daemon venv (no PyGObject) as "unsupported"
    even on a box where /usr/bin/python3 could run everything.
    """
    missing = [name for name in ("sway", "ydotool", "grim") if not shutil.which(name)]
    if missing:
        return f"sway, ydotool and grim are needed; missing here: {', '.join(missing)}"
    if backend.grid_python() is None:
        return (
            "no interpreter with PyGObject and the gtk4-layer-shell typelib "
            "(set EASYSPEAK_GRID_TYPELIB to the build tree's src directory, "
            "or EASYSPEAK_GRID_PYTHON to such an interpreter)"
        )
    return None


@pytest.fixture
def session(tmp_path, monkeypatch):
    """A headless sway session, exported to every client the harness spawns.

    The layer-shell build tree is exported too when one is named: an uninstalled
    build is the supported way to run this library where it is not packaged, and
    the helper finds its typelib through `GI_TYPELIB_PATH`. Both paths are
    prepended to whatever is already set rather than replacing it, and the
    export happens before the prerequisite check so the check sees the same
    environment the clients will.

    The environment is set through monkeypatch rather than handed only to sway,
    because the plugin spawns its own helper and the probe window is spawned by
    the test itself: sway names its socket inside XDG_RUNTIME_DIR, and only its
    own children inherit WAYLAND_DISPLAY. The socket is discovered rather than
    assumed, so a client that never learns it fails loudly here instead of
    quietly talking to the wrong compositor.
    """
    build = os.environ.get("EASYSPEAK_GRID_TYPELIB")
    if build:
        for name in ("GI_TYPELIB_PATH", "LD_LIBRARY_PATH"):
            existing = os.environ.get(name, "")
            monkeypatch.setenv(
                name, f"{build}{os.pathsep}{existing}" if existing else build
            )
    problem = _missing_prerequisite()
    if problem is not None:
        pytest.skip(problem)
    config = tmp_path / "sway.conf"
    config.write_text(SWAY_CONFIG, encoding="utf-8")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    # `WLR_BACKENDS` is a *backend list*, not a mode: with only `headless` in it
    # wlroots creates no libinput backend at all, and the compositor then has no
    # seat whatever the kernel holds — `swaymsg -t get_inputs` answers `[]` even
    # while /proc/bus/input/devices lists a device, and an injected click can
    # never be routed. That is right for the arms that only look at pixels, whose
    # session nothing real should be able to perturb, and fatal for the one arm
    # whose click must reach a window: that arm asks for `libinput` too. wlroots
    # keeps a libinput backend's devices only inside an *active* session, so the
    # live arm needs a seat manager (seatd) or an enabled VT behind it; without
    # one sway exits before binding a socket and the fixture skips, naming that.
    live = os.environ.get("EASYSPEAK_GRID_LIVE") == "click"
    monkeypatch.setenv("WLR_BACKENDS", "headless,libinput" if live else "headless")
    # `WLR_LIBINPUT_NO_DEVICES=1` asks the libinput backend for no devices at all:
    # the same isolation as above, said once more for the case where a caller's
    # environment already names that backend. A value inherited from the caller is
    # dropped for the live arm rather than trusted, so its seat is the harness's
    # own doing.
    if live:
        monkeypatch.delenv("WLR_LIBINPUT_NO_DEVICES", raising=False)
    else:
        monkeypatch.setenv("WLR_LIBINPUT_NO_DEVICES", "1")
    # sway's own words are kept: the one failure that is not the harness's own —
    # a session that never becomes active, so no socket is bound — is only
    # legible in them. The child holds its own copy of the descriptor, so closing
    # this one is safe.
    log = tmp_path / "sway.log"
    with log.open("w", encoding="utf-8") as handle:
        sway = subprocess.Popen(
            ["sway", "-c", str(config)],
            stdout=subprocess.DEVNULL,
            stderr=handle,
        )
    deadline = time.monotonic() + 10
    display = None
    while time.monotonic() < deadline:
        sockets = sorted(
            path.name
            for path in tmp_path.glob("wayland-*")
            if not path.name.endswith(".lock")
        )
        if sockets:
            display = sockets[0]
            break
        if sway.poll() is not None:
            # The live arm's session asks for a libinput backend, which wlroots
            # only keeps inside an active session; a compositor that refuses to
            # start there is reporting the missing seat rather than a bug in the
            # harness, so the skip names the prerequisite and carries sway's own
            # words for it. `seatd` hands a seat to one client at a time, so a
            # stray compositor left running by an earlier experiment looks the
            # same way and is named by the same log tail.
            pytest.skip(
                "sway exited before it bound a socket (the live arm needs an "
                "active session for its libinput backend: a running seatd with a "
                "free seat, or a VT-enabled login session): " + _sway_log_tail(log)
                if live
                else "sway exited before it bound a socket: " + _sway_log_tail(log)
            )
        time.sleep(0.2)
    if display is None:
        sway.terminate()
        pytest.skip(
            "sway never created a Wayland socket (it stayed up without becoming "
            "active): " + _sway_log_tail(log)
        )
    monkeypatch.setenv("WAYLAND_DISPLAY", display)
    yield os.environ
    sway.terminate()
    sway.wait(timeout=5)


def _grim(env, path):
    subprocess.run(["grim", str(path)], env=env, check=False, timeout=10)


def _sway_log_tail(log, lines=3):
    """The last few things sway said, for a skip that would otherwise be bare.

    sway's stderr is captured to a file by the fixture because the one failure
    that is not the harness's own — a session that never becomes active, so the
    compositor never binds a socket — is only legible in sway's own words
    ("failed to add backend 'libinput'", "Timeout waiting session to become
    active"). Best-effort: an empty or unreadable log answers with a dash rather
    than raising in the middle of a skip.
    """
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "-"
    said = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(said[-lines:]) or "-"


def _kernel_input_names():
    """The device names `/proc/bus/input/devices` lists, or an empty list.

    The kernel's view, used only when the compositor will not answer. A device
    here does not mean the session can see it - with `WLR_LIBINPUT_NO_DEVICES=1`
    wlroots opens none of them - so this is a fallback, never the first word.
    """
    try:
        listing = Path("/proc/bus/input/devices").read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        line.split('"')[1]
        for line in listing.splitlines()
        if line.startswith("N: Name=") and line.count('"') >= 2
    ]


def _sway_inputs(env):
    """What `swaymsg -t get_inputs` lists, or None when it cannot answer.

    The compositor is asked first because its list is the one that decides
    whether an injected click has a route: with `WLR_BACKENDS=headless` — no
    libinput backend — it is empty while `/proc/bus/input/devices` still lists
    the kernel's devices. Sway's IPC socket is named inside `XDG_RUNTIME_DIR` but
    is never exported to us (only sway's own children inherit `SWAYSOCK`), so it
    is discovered here the same way the session fixture discovers the Wayland
    socket. Returns None for every failure — a missing `swaymsg`, no socket, a
    refused ask, unparsable JSON — because this runs to explain a failed
    assertion and must not raise one of its own.
    """
    runtime = env.get("XDG_RUNTIME_DIR")
    sockets = sorted(Path(runtime).glob("sway-ipc.*.sock")) if runtime else []
    if not sockets or not shutil.which("swaymsg", path=env.get("PATH")):
        return None
    try:
        ask = subprocess.run(
            ["swaymsg", "-t", "get_inputs"],
            env={**env, "SWAYSOCK": str(sockets[0])},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if ask.returncode != 0:
        return None
    try:
        return [device.get("identifier", "?") for device in json.loads(ask.stdout)]
    except (ValueError, AttributeError):
        return None


def _input_report(env):
    """What input the session had, one line of diagnosis for a lost click.

    The compositor's own answer is the first word, in the identifiers it uses;
    the kernel list is the named fallback, and both failures are tolerated. The
    answer is a snapshot taken after the click: on 0.1.8 a daemonless ydotool
    destroys its per-invocation device when its client exits, so "no devices" can
    also mean "the device came and went", which is why the line names its source
    rather than judging. On 1.0.x there is no daemonless mode at all, and the
    daemon's device is persistent, so there the reading is unambiguous.
    """
    devices = _sway_inputs(env)
    if devices is not None:
        if devices:
            return (
                f"the compositor sees {len(devices)} input device(s) "
                f"({', '.join(devices)}), so the injected click had a seat"
            )
        return (
            "the compositor sees no input device (swaymsg -t get_inputs "
            "returned []), so the injected click had no seat"
        )
    names = _kernel_input_names()
    if names:
        return (
            "swaymsg could not answer, but /proc/bus/input/devices lists "
            f"{len(names)} device(s) ({', '.join(names)})"
        )
    return "input state unknown: neither swaymsg nor /proc/bus/input/devices answered"


@pytest.fixture(autouse=True)
def _reap_leaked_helper():
    """No test - passing, failing or skipped - leaves a spawned helper behind.

    The live arm cannot close its session itself (the probe window must stay up
    to observe the click), and a failing arm must not strand a GTK process
    either; the unit suite reaps with exactly this fixture.
    """
    yield
    if backend._helper is not None:
        backend.stop_helper("harness cleanup")


class TestGate:
    def test_a_failed_injector_probe_keeps_the_extension_backend_in_charge(
        self, monkeypatch
    ):
        """The fail-closed property, asserted where it needs no privileges and
        no display: a probe that cannot inject leaves the ydotool backend
        inert, and the plugin's gate routes the words to the extension
        backend."""
        monkeypatch.delenv("EASYSPEAK_GRID_BACKEND", raising=False)
        monkeypatch.setattr(backend, "_probe_overlay", lambda: True)
        monkeypatch.setattr(backend, "_probe_injector", lambda: False)
        mousegrid.setup(core=None)
        assert backend._active is False
        assert mousegrid._backend is mousegrid._extension
        assert backend.handle("grid", core=None) is None

    def test_the_injector_gate_passes_with_an_injector_to_reach(
        self, monkeypatch, caplog
    ):
        """The gate's passing case on a real ydotool: the client's own verb list,
        the no-op built in the dialect that client reports, and a daemon socket
        to emit through. This runs the real `ydotool help` and the real no-op, so
        it skips where ydotool is absent, or where nothing answers a socket.

        The daemon is a precondition here, not a mode: Ubuntu 26.04 ships ydotool
        1.0.4, whose client has no per-invocation fallback (0.1.8, on 25.10, had
        one), so with no socket it exits 2 with "failed to connect socket" and
        emits nothing. The socket is found by the plugin's own resolver, whose
        candidates include the login session's path even when `XDG_RUNTIME_DIR`
        has been repointed.
        """
        if shutil.which("ydotool") is None:
            pytest.skip("ydotool is not installed")
        # The dry-run seam would answer the no-op without spawning the real
        # client this test exists to exercise — a stale export must not buy a
        # vacuous pass.
        monkeypatch.delenv("EASYSPEAK_GRID_DRY_RUN", raising=False)
        if backend.injector_socket() is None:
            pytest.skip(
                "no ydotoold socket answers (Ubuntu packages one as a user unit); "
                "without a daemon a 1.0.x client has nothing to inject through"
            )
        monkeypatch.delenv("EASYSPEAK_GRID_BACKEND", raising=False)
        with caplog.at_level("INFO"):
            assert backend._probe_injector() is True
        assert any("injections " in r.message for r in caplog.records)
        monkeypatch.setattr(backend, "_probe_overlay", lambda: True)
        mousegrid.setup(core=None)
        assert backend._active is True
        assert mousegrid._backend is backend

    def test_the_injector_gate_fails_closed_without_a_socket(
        self, monkeypatch, tmp_path, caplog
    ):
        """The other half of the gate against the same binary: pointed at a socket
        that cannot answer, the real client refuses to emit at all, and a gate
        that opened here would take the grid words for an injector that cannot
        inject. 0.1.8 emits without a daemon, so there is nothing to fail closed
        on there and the case skips by name."""
        if shutil.which("ydotool") is None:
            pytest.skip("ydotool is not installed")
        # Same vacuous-pass guard as the passing twin: a stale DRY_RUN export
        # would answer the probe's no-op without the real client refusing.
        monkeypatch.delenv("EASYSPEAK_GRID_DRY_RUN", raising=False)
        if backend.dialect() != backend.YDTOOL_DIALECT_MODERN:
            pytest.skip(
                "0.1.8's client emits without a daemon; nothing to fail closed on"
            )
        dead = tmp_path / ".ydotool_socket"
        monkeypatch.setattr(backend, "ydotool_socket_candidates", lambda: [str(dead)])
        with caplog.at_level("INFO"):
            assert backend._probe_injector() is False
        assert any("no injector here" in r.message for r in caplog.records)


class TestForcedBackendArm:
    def test_reads_the_geometry_and_records_the_argv(
        self, session, tmp_path, monkeypatch, caplog
    ):
        """Arm A: the backend is forced, so no daemon is needed, and the overlay
        is observed through the plugin's own log records (its stdout belongs to
        the plugin, so the harness cannot read that stream itself).

        The argv is spelled out per dialect and the dialect is the one the
        installed client reports for itself, so on 26.04's ydotool 1.0.4 this
        pins `--absolute -x/-y` and the `0xC0` left click, and on 0.1.8 the
        positional move and `click 1`. Both are the *exact* strings the seam
        emits — a token the client would reject (`--delay`, a bare selector)
        fails here rather than at the pointer.
        """
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "uinput")
        monkeypatch.setenv("EASYSPEAK_GRID_DRY_RUN", "1")
        modern = backend.dialect() == backend.YDTOOL_DIALECT_MODERN
        expected_move = (
            "mousemove --absolute -x 1386 -y 300" if modern else "mousemove 1386 300"
        )
        expected_click = "click 0xC0" if modern else "click 1"

        commands = ["grid", "3 7 5", "click"]

        class FakeCore:
            def __init__(self):
                self.said = []

            def speak(self, text):
                self.said.append(text)

            def listen_modal(self, *_a, **_k):
                return iter(commands[1:])

        with caplog.at_level("INFO"):
            core = FakeCore()
            mousegrid.setup(core)
            assert backend._active is True
            mousegrid.handle(commands[0], core)

        ready = [r for r in caplog.records if "ready on" in r.message]
        assert ready, "the helper never reported ready"
        assert "1920" in ready[0].message and "1080" in ready[0].message
        dry = [r for r in caplog.records if "dry run:" in r.message]
        assert any(expected_move in r.message for r in dry), [r.message for r in dry]
        assert any(expected_click in r.message for r in dry), [r.message for r in dry]
        assert backend._helper is None


@pytest.mark.skipif(
    os.environ.get("EASYSPEAK_GRID_LIVE") != "click",
    reason="live injection is opt-in: set EASYSPEAK_GRID_LIVE=click",
)
class TestLiveArm:
    def test_the_click_lands_in_the_expected_cell(
        self, session, tmp_path, monkeypatch, request
    ):
        monkeypatch.setenv("EASYSPEAK_GRID_BACKEND", "uinput")
        repo_root = Path(backend.__file__).parents[3]
        # The probe window runs under the system interpreter, not the venv the
        # test itself runs in: grid_python() is the plugin's own resolver for
        # "an interpreter with PyGObject and Gtk 4", which is exactly the probe
        # window's requirement, and under `just integration` python3 resolves to
        # the daemon venv (no PyGObject), so a bare `python3` here would die on
        # import while everything else worked.
        python = backend.grid_python()
        assert python, "no interpreter can run the GTK4 probe window"

        # The bare session is captured before the probe window exists, and the
        # same view again once the probe has had the settle time below. Identical
        # pixels mean the probe never realised a surface - a GPU-less guest's
        # GTK4 may fail to get a GL/EGL context - and the click further down
        # would land on an empty scene. This runs before anything injects, so
        # that failure reports "the probe window never rendered" instead of the
        # lost click it would otherwise masquerade as.
        bare = tmp_path / "bare.png"
        _grim(session, bare)
        probe = subprocess.Popen(
            [python, str(repo_root / "tests" / "integration" / "grid_probe_window.py")],
            env=session,
            stdout=subprocess.PIPE,
            text=True,
        )

        # The terminate/communicate pair at the end of this test runs only on
        # the success path; any assertion failure between the spawn and it
        # would strand the probe window (the session fixture kills sway, but
        # the probe is this test's own child). A finalizer covers every exit
        # path and is a no-op after the success-path terminate — same hygiene
        # rule the helper reap fixture enforces for the backend's own child.
        def _reap_probe():
            if probe.poll() is None:
                probe.terminate()
                try:
                    probe.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    probe.kill()

        request.addfinalizer(_reap_probe)
        time.sleep(1.5)
        before = tmp_path / "before.png"
        _grim(session, before)
        probe_rendered = bare.read_bytes() != before.read_bytes()
        assert probe_rendered, (
            "the probe window never rendered: the bare session and the spawned "
            "probe are pixel-identical, so a click could only land on an empty "
            "scene"
        )

        monkeypatch.setattr(backend, "PROBE_TIMEOUT", 8.0)
        mousegrid.setup(core=None)
        assert backend._start_helper() == (0, 0, 1920, 1080)
        backend._bounds = (0, 0, 1920, 1080)
        for zone in (3, 7, 5):
            backend._bounds = backend.subdivide(backend._bounds, zone)
            backend._redraw(backend._bounds)
        time.sleep(0.5)
        assert backend._bounds == EXPECTED_CELL

        after = tmp_path / "after.png"
        _grim(session, after)
        assert before.read_bytes() != after.read_bytes(), "the overlay did not render"

        # The seat is asserted before anything is injected, and separately from
        # the click it has to route: with no input device in the compositor's own
        # list there is no route for an injected event to take, so a lost click
        # would be indistinguishable from a session that could never have
        # delivered one. `libinput` in `WLR_BACKENDS` inside an active session is
        # what puts devices here; the failure names that prerequisite instead of
        # leaving the reader to infer it from an empty press list later.
        seat = _sway_inputs(session)
        assert seat, (
            "the session has no input device, so no injected click can have a "
            "seat: sway needs its libinput backend (`WLR_BACKENDS="
            "headless,libinput`) inside an active session — a running seatd or a "
            "VT-enabled login session"
        )

        # The hide -> show lifecycle: hiding unmaps the surface and showing it
        # again remaps it, the case the helper's per-show region check exists
        # for. The fresh surface must still be click-through, and the injected
        # click further down is the observable: GDK keeps the region on the
        # surface and re-applies it to the re-created wl_surface, but only the
        # probe's press can prove it. The two screenshots keep a failed
        # re-present from passing silently, because a click would sail through
        # an absent overlay anyway.
        backend._send({"cmd": "hide"})
        time.sleep(0.5)
        hidden = tmp_path / "hidden.png"
        _grim(session, hidden)
        assert hidden.read_bytes() != after.read_bytes(), "the overlay did not hide"
        backend._redraw(backend._bounds)
        time.sleep(0.5)
        shown_again = tmp_path / "shown-again.png"
        _grim(session, shown_again)
        assert shown_again.read_bytes() != hidden.read_bytes(), (
            "the overlay did not come back"
        )

        x, y = backend.center(EXPECTED_CELL)
        print(f"about to click at {x},{y}")  # noqa: T201
        backend.move_to(x, y)
        backend.click("click")
        time.sleep(0.5)

        probe.terminate()
        out, _ = probe.communicate(timeout=5)
        events = [json.loads(line) for line in (out or "").splitlines()]
        presses = [e for e in events if e["event"] == "press"]
        # With the probe window proven on screen and the seat proven before the
        # injection, an empty press list has one reading left: a click that had a
        # real route and was swallowed before the probe observed it — the reading
        # that points at the overlay's input region. The report still names where
        # its input answer came from, because a session whose devices came and
        # went (0.1.8's daemonless mode destroys the device with the client) can
        # read as empty after the fact; on 1.0.x the daemon's device persists, so
        # that ambiguity is not in play.
        session_input = _input_report(session)
        assert presses, (
            f"the probe window saw no click: {events}; "
            f"probe window on screen: {probe_rendered}; {session_input}"
        )
        left, top, width, height = EXPECTED_CELL
        px, py = presses[-1]["x"], presses[-1]["y"]
        assert left - EXPECTED_TOLERANCE <= px <= left + width + EXPECTED_TOLERANCE
        assert top - EXPECTED_TOLERANCE <= py <= top + height + EXPECTED_TOLERANCE
