"""Mouse Grid Plugin - Voice-controlled mouse via GNOME Shell D-Bus extension.

Features:
- Chained numbers: "3 7 5" zooms three times in one utterance
- Repetition: "nudge up 5", "scroll down 3"
- Drag support: "mark" to start, "drag" to end
"""

import atexit
import contextlib
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

NAME = "mousegrid"
DESCRIPTION = "Voice-controlled mouse grid"
PRIORITY = 1

COMMANDS = [
    "grid/mouse/pointer - show mouse grid",
    "1-9 or chains like '3 7 5' - zoom to zone(s)",
    "up/down/left/right [N] - nudge position",
    "click - left click",
    "right click / double click / middle click",
    "scroll up/down/left/right [N]",
    "mark - start drag, drag - end drag",
    "again - reopen grid at last position",
    "close/cancel - hide grid",
]

core = None
grid_active = False
grid_bounds = None
screen_size = None
last_bounds = None
drag_start = None

NUDGE_AMOUNT = 20

# Trigger words
GRID_TRIGGERS = {
    "grid",
    "grit",
    "grip",
    "great",
    "greed",
    "grade",
    "grad",
    "grill",
    "guild",
    "greet",
    "grin",
    "green",
    "grey",
    "gray",
    "grab",
    "grand",
    "greek",
    "grew",
    "mouse",
    "pointer",
    "cursor",
    "crosshair",
}

# Number parsing - word to digit
WORD_TO_NUM = {
    "one": 1,
    "won": 1,
    "wan": 1,
    "two": 2,
    "to": 2,
    "too": 2,
    "tu": 2,
    "three": 3,
    "tree": 3,
    "free": 3,
    "four": 4,
    "for": 4,
    "fore": 4,
    "five": 5,
    "six": 6,
    "sex": 6,
    "seven": 7,
    "eight": 8,
    "ate": 8,
    "nine": 9,
    "nein": 9,
}

DIRECTIONS = {
    "up": ["up", "north", "top", "upper", "above"],
    "down": ["down", "south", "bottom", "lower", "below"],
    "left": ["left", "west", "lift", "let", "lef", "laughed", "loft"],
    "right": ["right", "east", "write", "rite", "wright"],
}


# This plugin drives the GNOME Shell extension over D-Bus (see dbus_call); core
# owns installing, refreshing, and enabling it (easyspeak.core.gnome_extension).


def setup(c):
    """Store the core reference for use by the plugin's handlers."""
    global core
    core = c


def host_run(cmd):
    """Run a command and capture its output (the plugin's own subprocess seam)."""
    return subprocess.run(cmd, capture_output=True, text=True)


def dbus_call(method, *args):
    """Call a method on the grid extension over D-Bus; True on success."""
    cmd = [
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.gnome.Shell",
        "--object-path",
        "/org/easyspeak/Grid",
        "--method",
        f"org.easyspeak.Grid.{method}",
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
            "/org/easyspeak/Grid",
            "--method",
            "org.easyspeak.Grid.GetScreenSize",
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


def cleanup():
    """Hide the grid on interpreter exit so no overlay is left on screen."""
    dbus_call("Hide")


atexit.register(cleanup)


def parse_number_sequence(text):
    """Extract ALL numbers from text as a sequence. '3 7 5' -> [3, 7, 5]."""
    # Replace word numbers with digits
    text_lower = text.lower()
    for word, num in WORD_TO_NUM.items():
        text_lower = re.sub(rf"\b{word}\b", str(num), text_lower)

    # Extract all single digits (grid zones are 1-9)
    return [int(char) for char in text_lower if char.isdigit() and char != "0"]


def parse_count(text):
    """Extract a repeat count (for nudge/scroll). Returns single number or 1."""
    text_lower = text.lower()
    for word, num in WORD_TO_NUM.items():
        text_lower = re.sub(rf"\b{word}\b", str(num), text_lower)

    match = re.search(r"\b(\d+)\b", text_lower)
    if match:
        return min(int(match.group(1)), 20)
    return 1


def parse_direction(text):
    """Return the direction (up/down/left/right) named in text, or None."""
    for direction, words in DIRECTIONS.items():
        for word in words:
            if word in text:
                return direction
    return None


def get_center():
    """Return the (x, y) center of the current grid cell, or None if no grid."""
    if not grid_bounds:
        return None
    x, y, w, h = grid_bounds
    return x + w // 2, y + h // 2


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
        core.speak("Grid")
        logger.info("Grid shown (%sx%s)", screen_size[0], screen_size[1])
    else:
        logger.warning("Failed to show grid - is extension enabled?")


def close_grid():
    """Hide the grid overlay and clear its bounds."""
    global grid_active, grid_bounds
    dbus_call("Hide")
    grid_active = False
    grid_bounds = None


def update_grid(zone):
    """Zoom to a single zone. Returns True if successful."""
    global grid_bounds

    if not grid_active or not grid_bounds:
        return False

    x, y, w, h = grid_bounds
    zone_w, zone_h = w // 3, h // 3

    zone_map = {
        1: (0, 0),
        2: (1, 0),
        3: (2, 0),  # top row
        4: (0, 1),
        5: (1, 1),
        6: (2, 1),  # middle row
        7: (0, 2),
        8: (1, 2),
        9: (2, 2),  # bottom row
    }

    if zone not in zone_map:
        return False

    col, row = zone_map[zone]
    new_x = x + col * zone_w
    new_y = y + row * zone_h

    # Only clamp if actually going off-screen (shouldn't happen, but safety)
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
    """Process a sequence of zones. 'three seven five' zooms 3 times."""
    for zone in zones:
        update_grid(zone)


# === Click Operations ===


def do_click(click_type="click"):
    """Click at the current cell center and close the grid; False if no grid."""
    global grid_bounds, grid_active, last_bounds

    center = get_center()
    if not center:
        return False

    cx, cy = center
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
    """Scroll ``count`` steps at the current cell center; False if no grid."""
    global grid_bounds, grid_active, last_bounds

    center = get_center()
    if not center:
        return False

    cx, cy = center
    last_bounds = grid_bounds
    grid_active = False
    grid_bounds = None

    logger.debug("  → Scroll %s x%s", direction, count)
    return dbus_call("Scroll", cx, cy, direction, count)


def nudge_grid(direction, count=1):
    """Shift the current cell ``count`` steps in a direction; False if no grid."""
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

    Leaves a drag in progress so a later :func:`end_drag` releases at the new
    target. False if no grid is active.
    """
    global drag_start, grid_bounds
    center = get_center()
    if not center:
        return False
    drag_start = center
    logger.debug("  → Drag start: %s", center)
    dbus_call("StartDrag", center[0], center[1])

    # Reset grid to full screen so user can navigate to destination
    grid_bounds = (0, 0, screen_size[0], screen_size[1])
    dbus_call("Update", 0, 0, screen_size[0], screen_size[1])
    logger.debug("  → Grid reset - navigate to drop location")
    return True


def end_drag():
    """Release a drag started by :func:`start_drag` and close the grid.

    False if no drag is in progress or no grid is active.
    """
    global drag_start, grid_bounds, grid_active, last_bounds
    if not drag_start:
        logger.debug("  → No drag in progress")
        return False
    center = get_center()
    if not center:
        return False
    logger.debug("  → Drag end: %s", center)
    dbus_call("EndDrag", center[0], center[1])
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

    # "Again" - reopen at last position
    if any(w in cmd_lower for w in ["again", "repeat", "reopen"]) and last_bounds:
        screen_size = get_screen_size()
        grid_bounds = last_bounds
        grid_active = True
        dbus_call("Show", screen_size[0], screen_size[1])
        dbus_call("Update", *last_bounds)
        core.speak("Grid")
        logger.info("Grid reopened at last position")
        listen_for_grid_commands(core)
        return True

    # Show grid
    if (
        any(w in cmd_lower for w in GRID_TRIGGERS)
        and "close" not in cmd_lower
        and "hide" not in cmd_lower
    ):
        show_grid()
        listen_for_grid_commands(core)
        return True

    return None


def listen_for_grid_commands(core):
    """Continuous listening while grid active."""
    global grid_active, drag_start

    logger.info("Grid mode: say numbers (e.g. '3 7 5'), nudge, scroll, click, close")

    while grid_active:
        with contextlib.suppress(Exception):
            core.stream.read(
                core.stream.get_read_available(), exception_on_overflow=False
            )

        first = core.wait_for_speech(timeout=10)
        if not first:
            continue

        audio = first + core.record_until_silence()
        cmd = core.transcribe(
            audio,
            prompt=(
                "one two three four five six seven eight nine click double "
                "right scroll nudge up down left right close cancel mark drag"
            ),
        )
        if not cmd:
            continue

        cmd_lower = cmd.lower().strip()
        logger.debug("  ← %s", cmd_lower)

        # === Exit ===
        if any(
            w in cmd_lower
            for w in [
                "close",
                "cancel",
                "escape",
                "exit",
                "hide",
                "stop",
                "done",
                "quit",
            ]
        ):
            close_grid()
            logger.info("Grid closed")
            return

        # === Drag ===
        if "mark" in cmd_lower:
            start_drag()
            continue
        if "drag" in cmd_lower and drag_start:
            end_drag()
            return

        # === Scroll ===
        if "scroll" in cmd_lower:
            direction = parse_direction(cmd_lower)
            if direction:
                do_scroll(direction, parse_count(cmd_lower))
                return
            continue

        # === Clicks ===
        has_click = "click" in cmd_lower

        if "double" in cmd_lower:
            do_click("double")
            return
        if "middle" in cmd_lower:
            do_click("middle")
            return
        if has_click and any(
            w in cmd_lower for w in ["right", "write", "rite", "wright"]
        ):
            do_click("right")
            return
        if has_click:
            do_click("click")
            return

        # === Nudge ===
        direction = parse_direction(cmd_lower)
        if direction and not has_click:
            nudge_grid(direction, parse_count(cmd_lower))
            continue

        # === Zone numbers (chained) ===
        zones = parse_number_sequence(cmd_lower)
        if zones:
            logger.debug("  → Zones: %s", zones)
            process_zones(zones)
            continue
