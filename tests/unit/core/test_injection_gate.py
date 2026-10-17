"""The gate: sticky three-arm selection and the total raise-only mapping.

Every test here is hermetic by construction: the selection matrix runs through
``_resolve_backend`` with injected owned/probe_error answers (no I/O), the
RemoteDesktop choreography runs against scripted fake connections, and the one
test that touches the real ``run_ydotool`` uses an argv no client could
mistake for an injection.
"""

import shutil
from unittest.mock import Mock

import pytest
from easyspeak.core import mediakeys as mk
from easyspeak.core import ydotool
from jeepney import MessageType, new_error, new_method_call


@pytest.fixture(autouse=True)
def _fresh_gate():
    """Reset the sticky cache so no test inherits another's backend choice.

    One real-gate test (anything calling ``select_backend``) would otherwise
    populate the module-level cache and silently fix the backend for every
    later sticky-selection test in the process.
    """
    mk._gate.backend = None
    yield
    mk._gate.backend = None


def test_exception_keeps_runtime_error_base():
    """press_key's ``except (RuntimeError, OSError)`` ladder must keep working."""
    assert issubclass(mk.InjectionUnavailableError, RuntimeError)


class FakeConn:
    """A RemoteDesktop connection honoring exactly one scripted outcome."""

    def __init__(self, outcome):
        self.outcome = outcome

    def send_and_get_reply(self, message, timeout=None):
        if self.outcome == "timeout":
            raise TimeoutError
        unexpected = f"unexpected message: {message}"
        raise AssertionError(unexpected)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- the selection matrix (spec 4.2): override x session x ownership --------


def test_matrix_gnome_owned(monkeypatch):
    monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
    monkeypatch.setattr(mk, "on_gnome", lambda: True)
    backend = mk._resolve_backend(
        owned=lambda: True, probe_error=lambda: False, cache=mk._GateCache()
    )
    assert backend.KIND == "remote-desktop"


def test_matrix_gnome_not_owned_selects_uinput(monkeypatch):
    monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
    monkeypatch.setattr(mk, "on_gnome", lambda: True)
    backend = mk._resolve_backend(
        owned=lambda: False, probe_error=lambda: False, cache=mk._GateCache()
    )
    assert backend.KIND == "uinput"  # the only honest "no" reroutes to uinput


def test_matrix_probe_error_stays_gnome(monkeypatch):
    monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
    monkeypatch.setattr(mk, "on_gnome", lambda: True)
    backend = mk._resolve_backend(
        owned=lambda: False, probe_error=lambda: True, cache=mk._GateCache()
    )
    assert backend.KIND == "remote-desktop"  # a wedged bus is not an honest "no"


def test_matrix_non_gnome_selects_uinput(monkeypatch):
    monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
    monkeypatch.setattr(mk, "on_gnome", lambda: False)
    backend = mk._resolve_backend(
        owned=lambda: False, probe_error=lambda: False, cache=mk._GateCache()
    )
    assert backend.KIND == "uinput"


def test_matrix_non_gnome_ignores_mutter_ownership(monkeypatch):
    monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
    monkeypatch.setattr(mk, "on_gnome", lambda: False)
    backend = mk._resolve_backend(
        owned=lambda: True, probe_error=lambda: False, cache=mk._GateCache()
    )
    assert backend.KIND == "uinput"  # Mutter's answer is irrelevant off GNOME


def test_override_remote_desktop_forces_the_native_backend(monkeypatch):
    monkeypatch.setenv("EASYSPEAK_KEY_BACKEND", "Remote-Desktop")
    backend = mk._resolve_backend(
        owned=lambda: False, probe_error=lambda: False, cache=mk._GateCache()
    )
    assert backend.KIND == "remote-desktop"  # forced, and case/space normalized


def test_override_uinput_beats_an_owned_gnome_session(monkeypatch):
    monkeypatch.setenv("EASYSPEAK_KEY_BACKEND", "uinput")
    backend = mk._resolve_backend(
        owned=lambda: True, probe_error=lambda: False, cache=mk._GateCache()
    )
    assert backend.KIND == "uinput"


def test_sticky_second_call_does_not_re_resolve(monkeypatch):
    calls = []
    monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
    monkeypatch.setattr(mk, "on_gnome", lambda: False)

    def counting_owned():
        calls.append(1)
        return False

    cache = mk._GateCache()
    mk._resolve_backend(owned=counting_owned, probe_error=lambda: False, cache=cache)
    mk._resolve_backend(owned=counting_owned, probe_error=lambda: False, cache=cache)
    assert len(calls) == 1


def test_select_backend_probes_once_then_sticks(monkeypatch):
    """The NameHasOwner round trip is a first-injection cost, not per utterance.

    Stickiness exists so a wedged session bus costs its bounded retry ONCE;
    probing again on every injection would reintroduce exactly the
    per-utterance round trips spec 4.2 cites as the failure mode.
    """
    monkeypatch.delenv("EASYSPEAK_KEY_BACKEND", raising=False)
    probes = []

    def state():
        probes.append(1)
        return "unowned"

    monkeypatch.setattr(mk, "_mutter_state", state)
    monkeypatch.setattr(mk, "on_gnome", lambda: False)
    first = mk.select_backend()
    second = mk.select_backend()
    assert first is second
    assert len(probes) == 1


def test_unknown_override_warns_and_autos(monkeypatch, caplog):
    monkeypatch.setenv("EASYSPEAK_KEY_BACKEND", "ydotool")  # the old, wrong name
    backend = mk._resolve_backend(
        owned=lambda: True, probe_error=lambda: False, cache=mk._GateCache()
    )
    assert backend.KIND == "remote-desktop"  # unknown values fall through to auto
    assert any("EASYSPEAK_KEY_BACKEND" in r.message for r in caplog.records)


def test_auto_value_is_documented_and_silent(monkeypatch, caplog):
    monkeypatch.setenv("EASYSPEAK_KEY_BACKEND", "auto")
    mk._resolve_backend(
        owned=lambda: True, probe_error=lambda: False, cache=mk._GateCache()
    )
    assert not any("EASYSPEAK_KEY_BACKEND" in r.message for r in caplog.records)


# --- the mutter ownership probe ---------------------------------------------


class ScriptedBus:
    """One probe connection answering ``NameHasOwner`` with a scripted reply."""

    def __init__(self, outcome):
        self.outcome = outcome  # True | False | "error" | "timeout"

    def send_and_get_reply(self, message, timeout=None):
        assert timeout == mk.GDBUS_TIMEOUT  # the probe is bounded, like the rest
        if self.outcome == "timeout":
            raise TimeoutError
        if self.outcome == "error":
            return new_error(
                new_method_call(mk._DBUS, "NameHasOwner", "s", ("x",)),
                "org.freedesktop.DBus.Error.AccessDenied",
                "s",
                ("denied",),
            )
        reply = Mock()
        reply.header.message_type = MessageType.method_return
        reply.body = (self.outcome,)
        return reply

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _scripted_probe(monkeypatch, outcomes):
    """Hand out one scripted connection per ``open_dbus_connection`` call."""
    conns = [ScriptedBus(outcome) for outcome in outcomes]
    opens = []

    def factory(bus="SESSION"):
        opens.append(bus)
        return conns.pop(0)

    monkeypatch.setattr(mk, "open_dbus_connection", factory)
    return opens


def test_mutter_state_owned(monkeypatch):
    opens = _scripted_probe(monkeypatch, [True])
    assert mk._mutter_state() == "owned"
    assert len(opens) == 1  # a clean answer costs exactly one bounded call


def test_mutter_state_unowned(monkeypatch):
    opens = _scripted_probe(monkeypatch, [False])
    assert mk._mutter_state() == "unowned"
    assert len(opens) == 1


def test_mutter_state_error_reply_is_an_answer(monkeypatch):
    opens = _scripted_probe(monkeypatch, ["error"])
    assert mk._mutter_state() == "error"
    assert len(opens) == 1  # a D-Bus error reply is an answer, not a wedge


def test_mutter_state_retries_a_wedged_bus_once(monkeypatch):
    opens = _scripted_probe(monkeypatch, ["timeout", True])
    assert mk._mutter_state() == "owned"
    assert len(opens) == 2  # spec 4.2's ONE bounded retry, and it rescued it


def test_mutter_state_settles_on_error_after_the_retry(monkeypatch):
    opens = _scripted_probe(monkeypatch, ["timeout", "timeout"])
    assert mk._mutter_state() == "error"  # a wedged bus is not an honest "no"
    assert len(opens) == 2  # bounded: two attempts, never a third


# --- raise-only dispatch -----------------------------------------------------


def test_tap_functions_return_none_and_pass_arguments(monkeypatch):
    """tap_key/tap_chord report by raising, never by returning status."""

    class RecordingBackend:
        KIND = "uinput"

        def __init__(self):
            self.calls = []

        def tap_chord(self, keycodes):
            self.calls.append(("chord", keycodes))

        def tap_key(self, keycode, repeats=1):
            self.calls.append(("key", keycode, repeats))

    backend = RecordingBackend()
    monkeypatch.setattr(mk, "select_backend", lambda: backend)
    assert mk.tap_chord((29, 47)) is None
    assert mk.tap_key(14, repeats=3) is None
    assert backend.calls == [("chord", (29, 47)), ("key", 14, 3)]


def test_dispatch_translates_oserror(monkeypatch):
    """A missing binary or spawn failure is "no usable backend", not a crash."""

    class SpawnFailureBackend:
        KIND = "uinput"

        def tap_chord(self, keycodes):
            raise FileNotFoundError("ydotool: command not found")

        def tap_key(self, keycode, repeats=1):
            raise OSError("could not spawn")

    backend = SpawnFailureBackend()
    monkeypatch.setattr(mk, "select_backend", lambda: backend)
    with pytest.raises(mk.InjectionUnavailableError):
        mk.tap_chord((29, 47))
    with pytest.raises(mk.InjectionUnavailableError):
        mk.tap_key(14)


def test_dispatch_reraises_unavailable_errors_unchanged(monkeypatch):
    """An already translated error must not be wrapped a second time."""

    class RefusingBackend:
        KIND = "uinput"

        def tap_chord(self, keycodes):
            raise mk.InjectionUnavailableError("refused by Mutter")

        def tap_key(self, keycode, repeats=1):
            raise mk.InjectionUnavailableError("refused by Mutter")

    backend = RefusingBackend()
    monkeypatch.setattr(mk, "select_backend", lambda: backend)
    with pytest.raises(mk.InjectionUnavailableError, match=r"^refused by Mutter$"):
        mk.tap_chord((29, 47))
    with pytest.raises(mk.InjectionUnavailableError, match=r"^refused by Mutter$"):
        mk.tap_key(14)


def test_remote_desktop_translates_jeepney_timeout(monkeypatch):
    # through the MODULE dispatch — the TimeoutError/OSError translation
    # lives in tap_chord's arm, not inside the backend body; the fake
    # connection preserves the one-connection-per-chord contract
    monkeypatch.setattr(
        mk,
        "select_backend",
        lambda: mk.RemoteDesktopBackend(conn_factory=lambda: FakeConn("timeout")),
    )
    with pytest.raises(mk.InjectionUnavailableError):
        mk.tap_chord([29, 47])


# --- the uinput backend ------------------------------------------------------


def _pin_legacy_dialect(monkeypatch):
    """Pin the dialect so no test consults (and caches) the host binary.

    Same discipline as the ydotool suite: the dialect is module state the
    autouse conftest fixture clears, and these tests assert the outcome
    mapping, not the argv — the synthesis only has to run.
    """
    monkeypatch.setattr(ydotool, "_dialect", ydotool.YDTOOL_DIALECT_LEGACY)


def test_uinput_backend_maps_outcomes_to_raise(monkeypatch):
    _pin_legacy_dialect(monkeypatch)
    backend = mk.UinputBackend(runner=lambda args, timeout: "errored")
    with pytest.raises(mk.InjectionUnavailableError):
        backend.tap_chord((29, 47))


def test_uinput_unknown_raises_with_distinct_log(monkeypatch, caplog):
    _pin_legacy_dialect(monkeypatch)
    backend = mk.UinputBackend(runner=lambda args, timeout: "unknown")
    with pytest.raises(mk.InjectionUnavailableError):
        backend.tap_key(14, repeats=1)
    assert any("unknown" in r.message for r in caplog.records)


def test_uinput_backend_batches_repeats_into_one_invocation(monkeypatch):
    _pin_legacy_dialect(monkeypatch)
    runs = []
    backend = mk.UinputBackend(
        runner=lambda args, timeout: runs.append((args, timeout)) or "ran"
    )
    assert backend.tap_key(14, repeats=10) is None
    ((args, timeout),) = runs  # one invocation for the whole batch
    assert args == ("ydotool", "key", "--repeat", "10", "backspace")
    assert timeout == pytest.approx(
        mk.yd.INJECT_TIMEOUT + 10 * mk.yd.KEY_PER_REPEAT_BUDGET
    )


def test_uinput_repeats_below_one_is_a_noop():
    fired = []
    backend = mk.UinputBackend(runner=lambda args, timeout: fired.append(args) or "ran")
    backend.tap_key(14, repeats=0)
    assert fired == []


def test_uinput_default_runner_signature():
    """The DEFAULT runner path with the real run_ydotool against a
    guaranteed-refusing, NON-injecting argv (unknown verb: the client
    usage-errors without emitting events). A 2-arg stub runner would mask
    a TypeError at the true call site; a real Ctrl+V would type into
    whoever is focused on a provisioned dev host.
    """
    if shutil.which("ydotool") is None:
        pytest.skip(
            "ydotool is not installed here; the unknown-verb refusal this pins "
            "is the client's own, and without the binary the run answers "
            '"unknown" through the OSError arm before any dialect is read'
        )
    backend = mk.UinputBackend()
    with pytest.raises(mk.InjectionUnavailableError):
        backend._inject(
            ("ydotool", "definitely-not-a-verb", "x"), ydotool.key_timeout(1)
        )
