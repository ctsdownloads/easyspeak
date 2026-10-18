"""The GNOME backend: the grid conversation driven over D-Bus.

This is the original mousegrid implementation. It renders and clicks through
the bundled GNOME Shell extension (`src/gnome@easyspeak.dev`, served over
`org.gnome.Shell` D-Bus by `easyspeak.core.gnome_extension`), which is why it
is the only backend with the full verb surface: nudge, scroll and mark/drag
need either the shell's own input stack or a press-and-hold the one-invocation
ydotool client cannot express (its `click` is press+release in a single call,
and 0.1.8 has no wheel verb at all).

The plugin selects this backend wherever the ydotool gate does not open —
GNOME 47+ hosts, and anything else without both a layer-shell compositor and
a working injector — so on those desktops behaviour is exactly what it always
was.
"""

import logging
import re
import subprocess

from easyspeak.core.i18n import translator
from easyspeak.core.tray import on_gnome

from ._common import (
    AGAIN_WORDS,
    CLICK_REPLIES,
    GRID_TRIGGERS,
    SHOW_BLOCK_WORDS,
    WORD_TO_NUM,
    ZONE_MAP,
    center,
    click_kind,
    dismiss_match,
    parse_direction,
    parse_number_sequence,
    subdivide,
)

logger = logging.getLogger(__name__)

_ = translator(__file__)

core = None
grid_active = False
grid_bounds = None
screen_size = None
last_bounds = None
drag_start = None

NUDGE_AMOUNT = 20

KIND = "gnome"


# This backend drives the GNOME Shell extension over D-Bus (see dbus_call);
# core owns installing, refreshing, and enabling it
# (easyspeak.core.gnome_extension).


def setup(c):
    """Store the core reference for use by the backend's handlers."""
    global core
    core = c


def host_run(cmd):
    """Run a command and capture its output (the backend's own subprocess seam).

    A missing executable returns a failed result (returncode 1) rather than
    raising, so callers treat an absent `gdbus`—e.g. on a headless host such as
    WSL with no GNOME session—as a plain D-Bus failure. Without this the
    cleanup on interpreter exit would raise FileNotFoundError on exit.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        logger.debug("Command not found: %s", exc)
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="", stderr=str(exc)
        )


def dbus_call(method, *args):
    """Call a method on the grid extension over D-Bus; True on success."""
    cmd = [
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.gnome.Shell",
        "--object-path",
        "/org/easyspeak/Desktop",
        "--method",
        f"org.easyspeak.Desktop.{method}",
    ]
    cmd.extend(str(a) for a in args)
    result = host_run(cmd)
    return result.returncode == 0


def get_screen_size():
    """Get screen size from GNOME Shell extension (accurate for Wayland)."""
    result = host_run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.gnome.Shell",
            "--object-path",
            "/org/easyspeak/Desktop",
            "--method",
            "org.easyspeak.Desktop.GetScreenSize",
        ]
    )

    if result.returncode == 0:
        # Parse output like "((1920, 1200),)"

        match = re.search(r"\((\d+),\s*(\d+)\)", result.stdout)
        if match:
            return int(match.group(1)), int(match.group(2))

    # Fallback to /sys/class/drm
    for card in [
        "card0-eDP-1",
        "card1-eDP-1",
        "card0-DP-1",
        "card1-DP-1",
        "card0-HDMI-A-1",
        "card1-HDMI-A-1",
    ]:
        result = host_run(["cat", f"/sys/class/drm/{card}/modes"])
        if result.returncode == 0 and result.stdout.strip():
            match = re.match(r"(\d+)x(\d+)", result.stdout.strip().split("\n")[0])
            if match:
                return int(match.group(1)), int(match.group(2))
    return 1920, 1080


def _release_pending_drag():
    """Release a drag left in progress, so no exit path leaves the button down.

    `mark` presses the primary button and holds it while the user navigates to
    the drop target. Every way out of grid mode other than `drag` — closing,
    clicking, the new idle timeout, a tray sleep — returned without a matching
    release, which left the primary button pressed compositor-wide and turned
    every subsequent pointer move into a drag.
    """
    global drag_start
    if drag_start is None:
        return
    logger.debug("  → Releasing drag left in progress")
    # After close_grid() there are no bounds to take a centre from; releasing
    # at the press point is the least surprising fallback.
    x, y = get_center() or drag_start
    dbus_call("EndDrag", x, y)
    drag_start = None


def cleanup():
    """Hide the grid on interpreter exit so no overlay is left on screen."""
    _release_pending_drag()
    dbus_call("Hide")


def parse_count(text):
    """Extract a repeat count (for nudge/scroll).

    Returns single number or 1.
    """
    text_lower = text.lower()
    for word, num in WORD_TO_NUM.items():
        text_lower = re.sub(rf"\b{word}\b", str(num), text_lower)

    match = re.search(r"\b(\d+)\b", text_lower)
    if match:
        return min(int(match.group(1)), 20)
    return 1


def get_center():
    """Return the (x, y) center of the current grid cell, or None if no grid."""
    if not grid_bounds:
        return None
    return center(grid_bounds)


# === Grid Operations ===


def show_grid():
    """Show the full-screen grid overlay (no-op if it is already active)."""
    global grid_active, grid_bounds, screen_size

    if grid_active:
        return

    screen_size = get_screen_size()
    grid_bounds = (0, 0, screen_size[0], screen_size[1])

    if dbus_call("Show", screen_size[0], screen_size[1]):
        grid_active = True
        core.speak(_("Grid"))
        logger.info("Grid shown (%sx%s)", screen_size[0], screen_size[1])
    else:
        report_grid_unavailable(core)


def report_grid_unavailable(core):
    """Tell the user the grid couldn't be shown, and the likely reason.

    This backend is selected only where the ydotool gate did not open, so
    reaching this path means neither backend can serve the grid here.
    """
    if on_gnome():
        logger.warning("Failed to show the grid. Is the EasySpeak extension enabled?")
        core.speak(_("I couldn't show the grid. Is the EasySpeak extension enabled?"))
    else:
        logger.warning(
            "The mouse grid needs the GNOME extension or a working ydotool setup."
        )
        core.speak(_("The mouse grid needs either the GNOME extension or ydotool."))


def close_grid():
    """Hide the grid overlay and clear its bounds."""
    global grid_active, grid_bounds
    dbus_call("Hide")
    grid_active = False
    grid_bounds = None


def update_grid(zone):
    """Zoom to a single zone.

    Returns True if successful.
    """
    global grid_bounds

    if not grid_active or not grid_bounds:
        return False

    if zone not in ZONE_MAP:
        return False

    new_x, new_y, zone_w, zone_h = subdivide(grid_bounds, zone)

    # Only clamp if actually going off-screen. Subdividing an on-screen
    # rectangle cannot leave it, but the bounds are state, not arithmetic:
    # a cell restored by "again" after a resolution change, or a screen size
    # reported before that change, can start off-screen, and the clamp is
    # what keeps the redrawn grid (and its click target) on the monitor.
    new_x = max(new_x, 0)
    new_y = max(new_y, 0)
    if new_x + zone_w > screen_size[0]:
        new_x = screen_size[0] - zone_w
    if new_y + zone_h > screen_size[1]:
        new_y = screen_size[1] - zone_h

    grid_bounds = (new_x, new_y, zone_w, zone_h)

    cx, cy = get_center()
    logger.debug("  → Zone %s: %sx%s center=(%s, %s)", zone, zone_w, zone_h, cx, cy)
    return dbus_call("Update", new_x, new_y, zone_w, zone_h)


def process_zones(zones):
    """Process a sequence of zones.

    'three seven five' zooms 3 times.
    """
    for zone in zones:
        update_grid(zone)


# === Click Operations ===


def do_click(click_type="click"):
    """Click at the current cell center and close the grid; False if no grid."""
    global grid_bounds, grid_active, last_bounds

    center_point = get_center()
    if not center_point:
        return False

    cx, cy = center_point
    last_bounds = grid_bounds
    grid_active = False
    grid_bounds = None

    method_map = {
        "click": "Click",
        "double": "DoubleClick",
        "right": "RightClick",
        "middle": "MiddleClick",
    }

    return dbus_call(method_map.get(click_type, "Click"), cx, cy)


def do_scroll(direction, count=1):
    """Scroll `count` steps at the current cell center; False if no grid."""
    global grid_bounds, grid_active, last_bounds

    center_point = get_center()
    if not center_point:
        return False

    cx, cy = center_point
    last_bounds = grid_bounds
    grid_active = False
    grid_bounds = None

    logger.debug("  → Scroll %s x%s", direction, count)
    return dbus_call("Scroll", cx, cy, direction, count)


def nudge_grid(direction, count=1):
    """Shift the current cell `count` steps in a direction; False if no grid."""
    global grid_bounds

    if not grid_bounds:
        return False

    x, y, w, h = grid_bounds
    amount = NUDGE_AMOUNT * count

    if direction == "up":
        y = max(0, y - amount)
    elif direction == "down":
        y = min(screen_size[1] - h, y + amount)
    elif direction == "left":
        x = max(0, x - amount)
    elif direction == "right":
        x = min(screen_size[0] - w, x + amount)

    grid_bounds = (x, y, w, h)
    cx, cy = get_center()
    logger.debug("  → Nudge %s x%s: center=(%s, %s)", direction, count, cx, cy)
    return dbus_call("Update", x, y, w, h)


def start_drag():
    """Press at the current cell center and reset the grid to full screen.

    Leaves a drag in progress so a later [`end_drag`][_extension.end_drag]
    releases at the new target. False if no grid is active.
    """
    global drag_start, grid_bounds
    center_point = get_center()
    if not center_point:
        return False
    drag_start = center_point
    logger.debug("  → Drag start: %s", center_point)
    dbus_call("StartDrag", center_point[0], center_point[1])

    # Reset grid to full screen so user can navigate to destination
    grid_bounds = (0, 0, screen_size[0], screen_size[1])
    dbus_call("Update", 0, 0, screen_size[0], screen_size[1])
    logger.debug("  → Grid reset - navigate to drop location")
    return True


def end_drag():
    """Release a drag and close the grid.

    Releases a drag started by [`start_drag`][_extension.start_drag].
    False if no drag is in progress or no grid is active.
    """
    global drag_start, grid_bounds, grid_active, last_bounds
    if not drag_start:
        logger.debug("  → No drag in progress")
        return False
    center_point = get_center()
    if not center_point:
        return False
    logger.debug("  → Drag end: %s", center_point)
    dbus_call("EndDrag", center_point[0], center_point[1])
    last_bounds = grid_bounds
    grid_active = False
    grid_bounds = None
    drag_start = None
    return True


# === Main Handler ===


def handle(cmd, core):
    """Show or reopen the grid on a trigger word, then enter grid mode.

    Returns None for commands that don't open the grid.
    """
    global grid_active, grid_bounds, last_bounds, screen_size

    cmd_lower = cmd.lower().strip()
    words = cmd_lower.split()

    # "Again" - reopen at last position
    if any(w in words for w in AGAIN_WORDS) and last_bounds:
        screen_size = get_screen_size()
        # The remembered cell came from a previous session's geometry: a
        # resolution change or a dock swap between sessions would draw it
        # clipped and aim its clicks at the edge of the output. The fresh
        # full rectangle is the only shape the containment invariant
        # guarantees, so a cell that no longer fits reopens as one — the
        # same rule the ydotool backend applies in `_open_session`, so the
        # parity battery can hold both backends to one rectangle per
        # utterance.
        left, top, width, height = last_bounds
        fits = (
            left >= 0
            and top >= 0
            and left + width <= screen_size[0]
            and top + height <= screen_size[1]
        )
        if not fits:
            logger.info("grid: the remembered cell does not fit; reopening full")
            last_bounds = (0, 0, screen_size[0], screen_size[1])
        if not dbus_call("Show", screen_size[0], screen_size[1]):
            report_grid_unavailable(core)
            return True
        grid_bounds = last_bounds
        grid_active = True
        dbus_call("Update", *last_bounds)
        core.speak(_("Grid"))
        logger.info("Grid reopened at last position")
        listen_for_grid_commands(core)
        return True

    # Show grid
    if any(w in words for w in GRID_TRIGGERS) and not (SHOW_BLOCK_WORDS & set(words)):
        show_grid()
        listen_for_grid_commands(core)
        return True

    return None


def listen_for_grid_commands(core):
    """Handle grid commands until the grid closes or the mode ends.

    Core owns the listening loop (see
    [`listen_modal`][core.main.EasySpeak.listen_modal]) so the tray stays
    responsive while the grid holds the microphone, and an unattended grid
    times out instead of trapping the session. Any drag still in progress is
    released on the way out, so a timeout can't leave the mouse button held
    down.
    """
    global grid_active, drag_start

    if not grid_active:
        return  # the grid never opened (no extension); nothing to listen for

    logger.info("Grid mode: say numbers (e.g. '3 7 5'), nudge, scroll, click, close")

    try:
        _run_grid_mode(core)
    finally:
        _release_pending_drag()
        if grid_active:
            logger.debug("  → Hiding grid left open by an ended mode")
            close_grid()


def _run_grid_mode(core):
    """Dispatch one grid command per utterance until the mode ends."""
    global grid_active, drag_start

    for spoken in core.listen_modal(
        "grid",
        prompt=(
            "one two three four five six seven eight nine click double "
            "right scroll nudge up down left right close cancel mark drag"
        ),
        timeout=10,
        idle_timeout=30,
    ):
        cmd_lower = spoken.lower()
        logger.debug("  ← %s", cmd_lower)

        # === Exit ===
        if dismiss_match(cmd_lower):
            close_grid()
            core.speak(_("Grid closed"))
            logger.info("Grid closed")
            return

        # === Drag ===
        if "mark" in cmd_lower:
            start_drag()
            # "Holding", not "Marked": grid mode is still listening and "mark"
            # inside the reply would start a second drag.
            core.speak(_("Holding"))
            continue
        if "drag" in cmd_lower and drag_start:
            end_drag()
            core.speak(_("Dropped"))
            return

        # === Scroll ===
        if "scroll" in cmd_lower:
            direction = parse_direction(cmd_lower)
            if direction:
                do_scroll(direction, parse_count(cmd_lower))
                core.speak(_("Scrolled"))
                return
            continue

        # === Clicks ===
        # `_common.click_kind` resolves the flavour for both backends; an
        # utterance that names no click word falls through to the nudge
        # below, where bare direction words belong.
        kind = click_kind(cmd_lower)
        if kind:
            do_click(kind)
            core.speak(CLICK_REPLIES[kind])
            return

        # === Nudge ===
        direction = parse_direction(cmd_lower)
        if direction:
            nudge_grid(direction, parse_count(cmd_lower))
            continue

        # === Zone numbers (chained) ===
        zones = parse_number_sequence(cmd_lower)
        if zones:
            logger.debug("  → Zones: %s", zones)
            process_zones(zones)
            continue
