"""Key injection with per-desktop backends.

Mutter RemoteDesktop where the session provides it (GNOME, unchanged behavior —
a RemoteDesktop session lives only as long as its creating D-Bus connection, so
each chord runs CreateSession → Start → keycodes → Stop on ONE connection,
closed when the chord's connection scope exits); ydotool/uinput everywhere
else. The contract is two-tier, raise-only both ways: every backend failure
becomes `InjectionUnavailableError`, while a chord/key the installed client
cannot spell raises the argv builder's plain `ValueError` instead — injection
is available, the key is just not nameable on that dialect (the media keys on
0.1.x; see ydotool.KEY_LEGACY_NAMES). The replay story (media keys for native
desktop feedback) is one consumer, not the module's reason to exist.
"""

import logging
import os

from easyspeak.core import ydotool as yd
from easyspeak.core.session import GDBUS_TIMEOUT, on_gnome
from jeepney import DBusAddress, MessageType, new_method_call
from jeepney.io.blocking import open_dbus_connection

logger = logging.getLogger(__name__)

_BUS = "org.gnome.Mutter.RemoteDesktop"

_REMOTE_DESKTOP = DBusAddress(
    "/org/gnome/Mutter/RemoteDesktop",
    bus_name=_BUS,
    interface=_BUS,
)


class InjectionUnavailableError(RuntimeError):
    """No injection backend answered: refused, missing, or timed out."""


class RemoteDesktopBackend:
    """Mutter RemoteDesktop injection — the native GNOME path, unchanged."""

    KIND = "remote-desktop"

    def __init__(self, conn_factory=None):
        """Take an optional connection factory; tests inject fakes here."""
        # ONE connection per chord — the session lives only as long as the
        # D-Bus connection that created it (the module invariant), so
        # CreateSession, every NotifyKeyboardKeycode and Stop ride the SAME
        # connection. This is today's tap_chord body with exactly two deltas:
        # the rename and the bounded send timeout.
        self._conn_factory = conn_factory or (
            lambda: open_dbus_connection(bus="SESSION")
        )

    def _call(self, conn, message):
        """Send `message`, return its reply; raise if D-Bus answers with an error."""
        reply = conn.send_and_get_reply(message, timeout=GDBUS_TIMEOUT)
        if reply.header.message_type is MessageType.error:
            raise InjectionUnavailableError(" ".join(map(str, reply.body)))
        return reply

    def tap_chord(self, keycodes):
        """Hold a chord of evdev keycodes together, then release it.

        The chord-order contract (down in the order given, up in reverse) and the
        failure modes are documented on the module-level `tap_chord`, which is
        the entry point every consumer goes through.
        """
        # The with-scope is today's `finally: conn.close()`: it closes the
        # connection on every path, success or error (jeepney's __exit__
        # closes), and test fakes bind the same context-manager contract.
        try:
            conn = self._conn_factory()
        except (KeyError, RuntimeError, ValueError, TimeoutError, OSError) as exc:
            # A bus that will not open — no session-bus address (KeyError), an
            # unsupported transport (RuntimeError), auth refusal
            # (AuthenticationError, a ValueError) — is "no usable backend",
            # not a crash: the totality promise covers the open, not just the
            # calls on it. TimeoutError/OSError are here for runner-shaped
            # factories; the dispatch would translate them anyway.
            message = f"no usable injection backend: {exc}"
            raise InjectionUnavailableError(message) from exc
        with conn:
            reply = self._call(conn, new_method_call(_REMOTE_DESKTOP, "CreateSession"))
            session = DBusAddress(
                reply.body[0],
                bus_name=_BUS,
                interface=f"{_BUS}.Session",
            )
            self._call(conn, new_method_call(session, "Start"))
            # Synchronous replies guarantee Mutter has processed each event before
            # we move on, so no settling delay is needed before Stop.
            for keycode in keycodes:
                self._call(
                    conn,
                    new_method_call(
                        session, "NotifyKeyboardKeycode", "ub", (keycode, True)
                    ),
                )
            for keycode in reversed(keycodes):
                self._call(
                    conn,
                    new_method_call(
                        session, "NotifyKeyboardKeycode", "ub", (keycode, False)
                    ),
                )
            self._call(conn, new_method_call(session, "Stop"))

    def tap_key(self, keycode, repeats=1):
        """Tap `keycode` `repeats` times, one RemoteDesktop session per tap."""
        if repeats < 1:
            return  # spoken "backspace 0" — same no-op range(0) gives today
        for _ in range(repeats):  # per-repeat loop: GNOME stays byte-for-byte
            self.tap_chord([keycode])


class UinputBackend:
    """ydotool/uinput injection — the compositor-agnostic path."""

    KIND = "uinput"

    def __init__(self, runner=None):
        """Take an optional runner; tests inject outcome stubs here."""
        # bind with a lambda, never the bare function: the real run_ydotool
        # takes (args, …) and the call site is 2-arg — a direct bind would
        # TypeError on the first real injection, invisible to 2-arg stubs
        self._runner = runner or (
            lambda args, timeout: yd.run_ydotool(args, timeout=timeout)
        )

    def tap_chord(self, keycodes):
        """Inject one chord as a single batched `key` invocation."""
        self._inject(yd.key_argv(tuple(keycodes)), yd.key_timeout(1))

    def tap_key(self, keycode, repeats=1):
        """Tap `keycode` `repeats` times in one batched invocation."""
        if repeats < 1:
            # Spoken "backspace 0": today's press_key loop no-ops it, so the
            # batch is never built and key_argv's ValueError guard — the loud
            # check for beyond-the-boundary bugs — stays out of the way.
            return
        self._inject(
            yd.key_argv((keycode,), repeats=repeats),
            yd.key_timeout(repeats),
        )

    def _inject(self, args, timeout):
        """Run one invocation; anything but `ran` raises, so callers fail closed.

        `run_ydotool` reports outcomes instead of raising, which suits the mouse
        grid's retry ladder but would strand a raise-only caller with a silent
        success: the mapping to `InjectionUnavailableError` happens here, at the
        only place the outcome string is still in scope.
        """
        outcome = self._runner(args, timeout)
        if outcome != "ran":
            # the outcome stays distinct in the log; the spoken fallback is shared;
            # the message names the remedy — the "log names the fix" promise
            logger.warning("uinput injection %s: %s", outcome, " ".join(args))
            message = (
                f"injection {outcome}: {' '.join(args)} — check ydotool is "
                "installed, /dev/uinput access (udev rule or input group), "
                "and ydotoold on 1.0.x"
            )
            raise InjectionUnavailableError(message)


class _GateCache:
    """One attribute of process-level state; tests swap in fresh instances.

    Until resolve writes the instance attr, reads see the class-attr default
    (None), which is what makes the sticky check a plain attribute read.
    """

    backend = None


_gate = _GateCache()  # module-level; tests reset it (see test_injection_gate)

_DBUS = DBusAddress(
    "/org/freedesktop/DBus",
    bus_name="org.freedesktop.DBus",
    interface="org.freedesktop.DBus",
)


def _mutter_state():
    """Return owned / unowned / error for `org.gnome.Mutter.RemoteDesktop`.

    One bounded NameHasOwner call, retried once on a bus-level failure (spec
    4.2's bounded retry — a wedged bus is not an honest "no"). jeepney blocks
    by default, hence the explicit timeout. An error REPLY is an answer, not a
    wedge, so it settles at once; a call that never got through (no bus to
    open, timeout, socket error) is retried once, then settles on "error" —
    a busless host is "no Mutter", not a crash.
    """
    for _attempt in (1, 2):
        try:
            with open_dbus_connection(bus="SESSION") as conn:
                reply = conn.send_and_get_reply(
                    new_method_call(
                        _DBUS,
                        "NameHasOwner",
                        "s",
                        ("org.gnome.Mutter.RemoteDesktop",),
                    ),
                    timeout=GDBUS_TIMEOUT,
                )
        except (KeyError, RuntimeError, ValueError, TimeoutError, OSError):
            # KeyError: no session-bus address; RuntimeError: unsupported
            # transport; ValueError: auth refusal (AuthenticationError).
            continue
        if reply.header.message_type is MessageType.error:
            return "error"
        return "owned" if reply.body[0] else "unowned"
    return "error"


def _resolve_backend(owned, probe_error, cache):
    """Sticky three-arm selection (spec 4.2); testable, no I/O.

    `owned`/`probe_error` are callables so the caller decides when — and
    whether — the Mutter probe is paid: once the cache holds a backend, neither
    is consulted.
    """
    if cache.backend is not None:
        return cache.backend
    forced = os.environ.get("EASYSPEAK_KEY_BACKEND", "").strip().lower()
    if forced == "remote-desktop":
        backend = RemoteDesktopBackend()
    elif forced == "uinput":
        backend = UinputBackend()
    else:
        if forced and forced != "auto":  # documented value stays silent
            logger.warning(
                "Ignoring EASYSPEAK_KEY_BACKEND=%r: unknown backend. "
                "Known: remote-desktop, uinput, auto.",
                forced,
            )
        gnome = on_gnome()
        # The Mutter verdict is consulted exactly once per resolution — the
        # probe is the memoized callable select_backend handed in. An OWNED
        # org.gnome.Mutter.RemoteDesktop name is definitive by itself: only
        # the session's mutter owns it, so requiring the desktop env here too
        # could only veto a true positive — a daemon launched without
        # XDG_CURRENT_DESKTOP (any env-less launcher) rerouted real GNOME
        # input to uinput, measured live in the ship QA smoke. The probe_error
        # arm keeps the guard: a wedged bus on a non-GNOME desktop still
        # resolves to uinput rather than guessing RemoteDesktop from nothing.
        native = owned() or (gnome and probe_error())
        backend = RemoteDesktopBackend() if native else UinputBackend()
    logger.info("key injection backend: %s", backend.KIND)
    cache.backend = backend
    return backend


def select_backend():
    """Resolve once per process (sticky); every later injection reuses it.

    The cache check here is what keeps the ownership probe a first-injection
    cost, and the probe itself is handed to `_resolve_backend` as a lazy,
    memoized callable — a forced override returns before the auto arm ever
    consults it, so `EASYSPEAK_KEY_BACKEND` works on a wedged or entirely
    absent bus, the very environment the escape hatch exists for.
    """
    if _gate.backend is not None:
        return _gate.backend
    state = None

    def from_bus():
        nonlocal state
        if state is None:
            state = _mutter_state()
        return state

    return _resolve_backend(
        owned=lambda: from_bus() == "owned",
        probe_error=lambda: from_bus() == "error",
        cache=_gate,
    )


def tap_chord(keycodes):
    """Hold a chord of evdev keycodes together, then release it.

    Keys go down in the order given and come up in reverse, so `[CTRL, V]` is the
    Ctrl+V an application expects rather than two unrelated keypresses. Used for
    pasting dictated text, which is how text reaches an application: every toolkit
    implements paste, whereas accessibility-level insertion is widely stubbed out
    (Chromium-based apps accept it and discard it).

    Raises [`InjectionUnavailableError`][core.mediakeys.InjectionUnavailableError]
    when no injection backend answered, so the caller can report why. A chord
    the installed dialect cannot spell raises the argv builder's plain
    `ValueError` instead (the same carve-out `tap_key` documents).
    """
    try:
        select_backend().tap_chord(tuple(keycodes))
    except InjectionUnavailableError:
        # Already translated by a backend: re-raise unchanged, never re-wrapped.
        raise
    except (TimeoutError, OSError) as exc:
        # Both belong to the RemoteDesktop arm here: the bounded D-Bus wait
        # (jeepney TimeoutError) and a socket/transport error (OSError). The
        # uinput runner never raises them — core.ydotool._run_bounded catches
        # its own spawn/timeout errors and returns outcome strings that
        # UinputBackend translates — so this rung is the Mutter path (plus
        # belt-and-braces for custom, test-injected runners). Either way the
        # meaning is "no usable backend": press_key catches by family and
        # dictation's paste path keys on InjectionUnavailableError.
        message = f"injection unavailable: {exc}"
        raise InjectionUnavailableError(message) from exc


def tap_key(keycode, repeats=1):
    """Press and release one evdev keycode via the selected backend.

    Raises [`InjectionUnavailableError`][core.mediakeys.InjectionUnavailableError]
    when no injection backend answered (e.g. a non-GNOME session) so the caller
    can fall back to a silent change. A code the 0.1.8 client cannot spell
    raises the argv builder's plain ValueError instead — injection is
    available, the key is just not nameable on that dialect.
    """
    try:
        select_backend().tap_key(keycode, repeats=repeats)
    except InjectionUnavailableError:
        # Already translated by a backend: re-raise unchanged, never re-wrapped.
        raise
    except (TimeoutError, OSError) as exc:
        message = f"injection unavailable: {exc}"
        raise InjectionUnavailableError(message) from exc


KEYS = {
    "enter": 28,
    "tab": 15,
    "escape": 1,
    "backspace": 14,
    "up": 103,
    "down": 108,
    "left": 105,
    "right": 106,
    "home": 102,
    "end": 107,
    "page up": 104,
    "page down": 109,
}

KEY_ALIASES = {
    "delete": "backspace",
    "return": "enter",
    "escape key": "escape",
}

SPOKEN_COUNTS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# Spoken key name -> key in KEYS, the English vocabulary.
KEY_NAMES = {**{name: name for name in KEYS}, **KEY_ALIASES}
PRESS_PREFIXES = ("press",)

MAX_KEY_REPEATS = 200


def parse_key_request(words, bare_allowed, *, names=None, counts=None, prefixes=None):
    """Return (keycode, repeats) for a spoken keystroke command, else None.

    Accepts an optional "press" prefix, key names of up to three words, and a trailing
    count as digits or a number word. `bare_allowed` names the keys a caller will
    accept without the prefix; every other key needs it, so that words already
    meaning something else in that mode are left alone. The vocabulary is English
    unless `names` (spoken name -> key in `KEYS`), `counts` (number word -> int)
    and `prefixes` say otherwise, as dictation does for the user's language.
    """
    names = KEY_NAMES if names is None else names
    counts = SPOKEN_COUNTS if counts is None else counts
    prefixes = PRESS_PREFIXES if prefixes is None else prefixes
    explicit = bool(words) and words[0] in prefixes
    if explicit:
        words = words[1:]
    if not words:
        return None

    for length in (3, 2, 1):
        name = names.get(" ".join(words[:length]))
        if name is None or (not explicit and name not in bare_allowed):
            continue
        tail = words[length:]
        if not tail:
            return KEYS[name], 1
        if len(tail) > 1:
            return None
        count = int(tail[0]) if tail[0].isdigit() else counts.get(tail[0])
        if count is None:
            return None
        return KEYS[name], min(count, MAX_KEY_REPEATS)
    return None


def press_key(keycode, repeats=1):
    """Tap `keycode` `repeats` times; True when the keystrokes were delivered."""
    try:
        select_backend().tap_key(keycode, repeats=repeats)
    except (RuntimeError, OSError, ValueError) as exc:
        # ValueError: the uinput backend's argv builder raises it for a code
        # the 0.1.8 name tables cannot spell (the media keys — see
        # ydotool.KEY_LEGACY_NAMES). A refusal is not a crash: the caller
        # answers with its own fallback (dictation's spoken refusal, the
        # system plugin's wpctl call) instead of the error escaping to the
        # dispatcher's generic apology.
        logger.warning("Keystrokes could not be injected: %s", exc)
        return False
    return True
