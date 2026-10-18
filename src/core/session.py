"""Session-kind and session-bus facts shared by core modules.

A neutral home for the two small facts more than one core module needs: which
desktop family the session belongs to, and the budget any bounded session-bus
wait honors. They used to live in `core.tray`, which made the key-injection
core import from the tray/UI module — a layering inversion this module removes.
`core.tray` re-exports both, so plugin imports and the tests that patch
`core.tray.on_gnome` keep working unchanged.
"""

import os

# Cap any session-bus round trip (gdbus or jeepney) so a wedged bus can't hang
# the audio loop or an injection. One budget, one meaning, two former homes.
GDBUS_TIMEOUT = 5.0


def on_gnome():
    """Return whether the session is GNOME, where the Shell extension is the tray."""
    return "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
