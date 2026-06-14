"""Hold-to-dictate keyboard activation via evdev (the silent-activation path).

On Wayland an ordinary process can't grab global keys, and only raw evdev
events from ``/dev/input`` expose key *release* — which "hold the keys to
dictate, release to stop" needs. This listener reads every keyboard device in a
background thread and tracks whether a configured modifier combo (default
Ctrl+Shift) is fully held, so the audio loop can start dictation on press and
end it the moment the keys come up.

It is best-effort: if python-evdev isn't installed or ``/dev/input`` isn't
readable (the user isn't in the ``input`` group), the listener logs how to
enable it and stays inert, so the daemon runs normally without the hotkey.
"""

import contextlib
import logging
import threading

logger = logging.getLogger(__name__)

# How long select() blocks per cycle, so stop() is honoured promptly.
POLL_TIMEOUT = 0.5

# Friendly modifier name -> the evdev key names that satisfy it (left OR right),
# so "ctrl+shift" matches whichever Ctrl and Shift the user happens to hold.
_MODIFIER_ALIASES = {
    "ctrl": ("KEY_LEFTCTRL", "KEY_RIGHTCTRL"),
    "control": ("KEY_LEFTCTRL", "KEY_RIGHTCTRL"),
    "shift": ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"),
    "alt": ("KEY_LEFTALT", "KEY_RIGHTALT"),
    "super": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
    "meta": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
    "win": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
}


def parse_combo(spec: str) -> tuple[frozenset[str], ...]:
    """Parse a ``'+'``-separated combo string into groups of accepted key names.

    Each element becomes a group of evdev key names of which any one satisfies
    that part of the combo, so ``"ctrl+shift"`` matches either Ctrl together
    with either Shift. Names that aren't known aliases fall through as a single
    literal evdev key name (``"rightctrl"`` -> ``"KEY_RIGHTCTRL"``) so less
    common combos still work.

    Args:
        spec: A combo such as ``"ctrl+shift"`` or ``"super+space"``.

    Returns:
        A tuple of frozensets, one per combo element; the combo is held when
        every group has at least one of its keys down.
    """
    groups = []
    for part in spec.split("+"):
        name = part.strip().lower()
        if not name:
            continue
        if name in _MODIFIER_ALIASES:
            groups.append(frozenset(_MODIFIER_ALIASES[name]))
        else:
            key = name.upper()
            if not key.startswith("KEY_"):
                key = "KEY_" + key
            groups.append(frozenset((key,)))
    return tuple(groups)


class HotkeyListener:
    """Track whether a key combo is held, off a background evdev reader.

    The audio loop calls :meth:`take_activation` once per iteration to learn
    when the combo was just pressed, then drives a dictation session gated on
    :meth:`is_held` so releasing the keys ends it. All evdev/threading state is
    kept behind a lock; the event-processing logic in :meth:`_process` is pure
    and the I/O lives in :meth:`_grab_devices`/:meth:`_drain`, so the behaviour
    is unit-testable without a real keyboard.
    """

    def __init__(self, combo="ctrl+shift", enabled=True):
        """Set up the listener for ``combo`` (e.g. ``"ctrl+shift"``).

        An unparseable or empty combo, or ``enabled=False``, leaves the
        listener disabled so :meth:`start` is a no-op.
        """
        self._spec = combo
        self._groups = parse_combo(combo)
        self._enabled = enabled and bool(self._groups)
        self._pressed = set()  # combo keys currently held
        self._held = False  # whole combo satisfied
        self._activation = False  # rising edge, consumed by take_activation()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._devices = []

    # --- audio-loop facing API ---

    def is_held(self):
        """Return whether the full combo is currently held."""
        with self._lock:
            return self._held

    def take_activation(self):
        """Return True once per press of the combo, clearing the edge.

        The audio loop polls this each iteration; a True means "the user just
        pressed the combo — start dictation now".
        """
        with self._lock:
            fired = self._activation
            self._activation = False
            return fired

    # --- lifecycle ---

    def start(self):
        """Begin watching the keyboard, unless disabled or no device is readable.

        Logs and stays inert (no thread) when the feature is turned off, evdev
        is missing, or ``/dev/input`` can't be read, so the daemon runs normally
        either way.
        """
        if not self._enabled:
            logger.debug("Keyboard activation disabled.")
            return
        self._devices = self._grab_devices()
        if not self._devices:
            return
        logger.info("Hold %s to dictate (silent activation).", self._spec)
        self._thread = threading.Thread(
            target=self._run, name="easyspeak-hotkey", daemon=True
        )
        self._thread.start()

    def stop(self):
        """Stop the reader thread and release the keyboard devices."""
        self._stop.set()
        for device in self._devices:
            with contextlib.suppress(Exception):
                device.close()
        self._devices = []

    # --- evdev I/O (kept thin so the logic above stays testable) ---

    def _grab_devices(self):
        """Open every readable keyboard device, or return [] if unavailable.

        Missing python-evdev or an unreadable ``/dev/input`` (no ``input`` group
        membership) is reported with how to fix it, then treated as "no hotkey".
        """
        try:
            import evdev
        except ImportError:
            logger.info(
                "python-evdev not installed; keyboard activation disabled. "
                "Install the 'evdev' package to enable hold-to-dictate."
            )
            return []

        devices = []
        for path in evdev.list_devices():
            try:
                device = evdev.InputDevice(path)
            except OSError:
                continue
            if evdev.ecodes.EV_KEY in device.capabilities():
                devices.append(device)

        if not devices:
            logger.warning(
                "No readable keyboard for hotkey activation. Add yourself to the "
                "'input' group (sudo usermod -aG input $USER) and re-login to "
                "enable hold-to-dictate."
            )
        return devices

    def _run(self):
        """Select across the keyboard devices and feed key events to _process."""
        import select

        fd_map = {device.fd: device for device in self._devices}
        while not self._stop.is_set():
            readable, _, _ = select.select(list(fd_map), [], [], POLL_TIMEOUT)
            for fd in readable:
                self._drain(fd_map[fd])

    def _drain(self, device):
        """Process all currently-available key events from one device."""
        try:
            events = list(device.read())
        except OSError:
            return  # device unplugged mid-read; the others keep working
        for event in events:
            name = self._event_keyname(event)
            if name is not None:
                self._process(name, event.value)

    def _event_keyname(self, event):
        """Return the evdev key name for a key event, or None if not a key.

        ``ecodes.KEY[code]`` is a list when a code has aliases; the first name
        is the canonical one and the only form our combos use.
        """
        import evdev

        if event.type != evdev.ecodes.EV_KEY:
            return None
        name = evdev.ecodes.KEY.get(event.code)
        if isinstance(name, (list, tuple)):
            name = name[0]
        return name

    def _process(self, keyname, value):
        """Update held state from one key event (value: 0=up, 1=down, 2=repeat).

        Only keys that belong to the combo move the state. The rising edge to
        "fully held" arms :meth:`take_activation`; releasing any key clears the
        held state so the dictation session ends.
        """
        if not any(keyname in group for group in self._groups):
            return
        pressed = value != 0
        with self._lock:
            if pressed:
                self._pressed.add(keyname)
            else:
                self._pressed.discard(keyname)
            held = all(self._pressed & group for group in self._groups)
            if held and not self._held:
                self._activation = True
            self._held = held
