"""Mouse Grid Plugin - the voice-controlled pointer grid, for every desktop.

One plugin, two backends, chosen once at daemon startup by a capability gate:

- The GNOME backend (`_extension`) drives the bundled GNOME Shell extension
  over D-Bus. It is the original implementation and the full verb surface:
  nudge, scroll, mark/drag.
- The ydotool backend (`_ydotool`) draws the same grid as a layer-shell
  overlay (gtk4-layer-shell) and clicks through ydotool at kernel level, so
  the grid works where no GNOME Shell can run (COSMIC, sway, KDE Wayland,
  Hyprland).

The gate (see `_ydotool.resolve_active`) claims the ydotool backend only where
a layer-shell-capable compositor AND a working injector are both present, and
fails closed: everywhere else the GNOME backend keeps serving, so on GNOME
47+ backend selection is unchanged — the one disclosed delta is the shared
click vocabulary (`lick`/`clique` now click on GNOME too, where they used to
fall through and be dropped). `EASYSPEAK_GRID_BACKEND=uinput|gnome` forces
either side — a deliberate override that short-circuits the probes, which is
what the integration harness uses to observe the overlay without a daemon.

Zone math, trigger words and the number tables are shared (`_common`), so one
utterance lands on the same pixel whichever backend answers. The verbs the
ydotool backend cannot honour (scroll, drag) remain extension-only; ydotool
0.1.8 has no wheel verb, and a hold-drag needs a timing design its
one-invocation press+release cannot express.
"""

import atexit
import logging
import os

from easyspeak.core.i18n import translator

from . import _extension, _ydotool

logger = logging.getLogger(__name__)

_ = translator(__file__)

NAME = "mousegrid"
DESCRIPTION = "Voice-controlled mouse grid"
PRIORITY = 1

COMMANDS = [
    _("grid/mouse/pointer - show mouse grid"),
    _("1-9 or chains like '3 7 5' - zoom to zone(s)"),
    _("up/down/left/right [N] - nudge position"),
    _("click - left click"),
    _("right click / double click / middle click"),
    _("scroll up/down/left/right [N]"),
    _("mark - start drag, drag - end drag"),
    _("again - reopen grid at last position"),
    _("close/cancel - hide grid"),
]

# The verbs the ydotool backend cannot honour (nudge, scroll, mark/drag)
# stay out of the help surface it serves. Core reads `COMMANDS` at help
# time, so `setup()` rebinds it to the list matching the gate's selection;
# the import-time default is the full list, under the same contract as
# `_backend` below (importing without running `setup()` behaves exactly
# like the original single-backend plugin).
COMMANDS_YDOTOOL = [
    _("grid/mouse/pointer - show mouse grid"),
    _("1-9 or chains like '3 7 5' - zoom to zone(s)"),
    _("click - left click"),
    _("right click / double click / middle click"),
    _("again - reopen grid at last position"),
    _("close/cancel - hide grid"),
]

_COMMANDS_FULL = COMMANDS

# The backend serving the conversation. Defaults to the extension backend so
# that importing the module without running `setup()` (as older tests and any
# direct consumer do) behaves exactly like the original single-backend plugin.
_backend = _extension


def setup(core):
    """Choose the backend once, at daemon startup.

    Runs in the loader's guarded `setup()` slot, so a raise here would only
    unload the plugin — but the probes are still bounded internally, because a
    hang is worse than a failure and the guard catches raises, not waits.
    The parameter is named for the keyword the integration harness pins
    (`setup(core=None)`); the loader itself calls it positionally.
    """
    _extension.setup(core)
    global _backend, COMMANDS
    forced = os.environ.get("EASYSPEAK_GRID_BACKEND")
    if forced == "uinput":
        _backend = _ydotool
        _ydotool.activate()
    elif forced == "gnome":
        _backend = _extension
        logger.info("grid: forced extension backend by EASYSPEAK_GRID_BACKEND=gnome")
    else:
        if forced is not None:
            # A typo'd value ("uinpt") would otherwise silently degrade to the
            # probes, and the user would never learn their override did
            # nothing.
            logger.warning(
                "grid: ignoring unknown EASYSPEAK_GRID_BACKEND=%r; probing", forced
            )
        _backend = _ydotool if _ydotool.resolve_active() else _extension
    logger.info("grid backend: %s", _backend.KIND)
    # The help surface matches the backend that will answer: a ydotool
    # desktop is not advertised the verbs that answer "That needs the GNOME
    # extension." there.
    COMMANDS = COMMANDS_YDOTOOL if _backend is _ydotool else _COMMANDS_FULL


def handle(cmd, core):
    """Route the grid conversation to the backend the gate selected.

    Returns None when the utterance is not the grid's, True when it was
    claimed and answered. Only the selected backend is consulted: it either
    claims the phrase or the phrase was never the grid's — the two backends
    share one phrase surface (`_common`), so there is no second opinion to
    ask for.
    """
    return _backend.handle(cmd, core)


def cleanup():
    """Hide the grid on interpreter exit so no overlay is left on screen."""
    _backend.cleanup()


atexit.register(cleanup)
