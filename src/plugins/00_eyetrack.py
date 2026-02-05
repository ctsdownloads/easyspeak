"""
Head Tracking Plugin - Cursor control via SixDRepNet
Uses 6D rotation representation for smooth head pose estimation
"""

import math
import subprocess
import threading
import time

NAME = "headtrack"
DESCRIPTION = "Head tracking for cursor control"
PRIORITY = 0

COMMANDS = [
    "start tracking - begin head tracking",
    "stop tracking - end tracking",
    "freeze - lock cursor position",
    "go - resume tracking",
    "nudge up/down/left/right - fine tune position",
    "click - left click at cursor",
    "double click - double click",
    "right click - right click",
    "recalibrate - reset center position",
]

core = None
tracking_active = False
tracking_thread = None
stop_event = threading.Event()
cursor_x = 960
cursor_y = 540
frozen = False
NUDGE_AMOUNT = 15


class OneEuroFilter:
    """
    One-Euro Filter for smoothing noisy signals.
    Adapts: smooth when still, responsive when moving.
    """

    def __init__(self, freq=30.0, min_cutoff=1.0, beta=0.007, d_cutoff=1.0):
        self.freq = freq
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev = None
        self.dx_prev = 0.0

    def _alpha(self, cutoff):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        te = 1.0 / self.freq
        return 1.0 / (1.0 + tau / te)

    def __call__(self, x):
        if self.x_prev is None:
            self.x_prev = x
            return x

        # Derivative
        dx = (x - self.x_prev) * self.freq

        # Smooth derivative
        a_d = self._alpha(self.d_cutoff)
        dx_smooth = a_d * dx + (1 - a_d) * self.dx_prev
        self.dx_prev = dx_smooth

        # Adaptive cutoff based on speed
        cutoff = self.min_cutoff + self.beta * abs(dx_smooth)

        # Smooth value
        a = self._alpha(cutoff)
        x_smooth = a * x + (1 - a) * self.x_prev
        self.x_prev = x_smooth

        return x_smooth


def setup(c):
    global core
    core = c


def host_run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dbus_call(method, *args):
    """Call GNOME Shell extension for cursor movement"""
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
    """Get screen size from GNOME Shell extension"""
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
        import re

        match = re.search(r"\((\d+),\s*(\d+)\)", result.stdout)
        if match:
            return int(match.group(1)), int(match.group(2))
    return 1920, 1080


def run_tracking():
    """Main tracking loop"""
    global tracking_active, stop_event, cursor_x, cursor_y, frozen

    import cv2
    from sixdrepnet import SixDRepNet

    print("Loading SixDRepNet model...")
    model = SixDRepNet(gpu_id=-1)  # CPU mode

    SCREEN_W, SCREEN_H = get_screen_size()
    print(f"Screen: {SCREEN_W}x{SCREEN_H}")

    cap = cv2.VideoCapture(1)  # Integrated webcam
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    if not cap.isOpened():
        print("Cannot open webcam!")
        tracking_active = False
        return

    # One-euro filters for each axis
    # min_cutoff: lower = smoother (try 0.5-2.0)
    # beta: higher = more responsive to fast moves (try 0.001-0.01)
    filter_yaw = OneEuroFilter(freq=30.0, min_cutoff=0.8, beta=0.005)
    filter_pitch = OneEuroFilter(freq=30.0, min_cutoff=0.8, beta=0.005)

    # Rolling average buffers for stable output
    BUFFER_SIZE = 15
    yaw_buffer = []
    pitch_buffer = []

    # Velocity tracking for movement gating
    prev_yaw = None
    prev_pitch = None
    VELOCITY_THRESHOLD = 0.3  # Degrees per frame - ignore movement below this

    # Calibration center
    center_yaw = None
    center_pitch = None

    # Settings
    SENSITIVITY_X = 40.0  # Pixels per degree
    SENSITIVITY_Y = 25.0
    DEAD_ZONE = 3.0  # Degrees - ignore small movements

    # Initialize cursor position
    cursor_x = SCREEN_W // 2
    cursor_y = SCREEN_H // 2

    print("Head tracking started. Look at center of screen...")
    print("Say 'recalibrate' to reset center, 'stop tracking' to end")

    calibration_frames = 0
    calibration_yaw = 0.0
    calibration_pitch = 0.0

    while tracking_active and not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            continue

        frame = cv2.flip(frame, 1)  # Mirror

        pitch, yaw, roll = model.predict(frame)

        if len(pitch) == 0:
            continue

        raw_pitch = -pitch[0]  # Invert: look up = cursor up
        raw_yaw = -yaw[0]  # Invert: look right = cursor right

        # Auto-calibrate on first 10 frames
        if center_yaw is None:
            calibration_yaw += raw_yaw
            calibration_pitch += raw_pitch
            calibration_frames += 1

            if calibration_frames >= 10:
                center_yaw = calibration_yaw / 10
                center_pitch = calibration_pitch / 10
                print(f"Calibrated: center=({center_yaw:.1f}, {center_pitch:.1f})")
            continue

        # Apply one-euro filter to raw values
        smooth_yaw = filter_yaw(raw_yaw)
        smooth_pitch = filter_pitch(raw_pitch)

        # Add to rolling average buffers
        yaw_buffer.append(smooth_yaw)
        pitch_buffer.append(smooth_pitch)
        if len(yaw_buffer) > BUFFER_SIZE:
            yaw_buffer.pop(0)  # pragma: no cover
            pitch_buffer.pop(0)  # pragma: no cover

        # Use averaged values
        avg_yaw = sum(yaw_buffer) / len(yaw_buffer)
        avg_pitch = sum(pitch_buffer) / len(pitch_buffer)

        # Velocity gating - ignore tiny movements (noise)
        if prev_yaw is not None:
            vel_yaw = abs(avg_yaw - prev_yaw)
            vel_pitch = abs(avg_pitch - prev_pitch)

            # If head is basically still, skip this frame
            if vel_yaw < VELOCITY_THRESHOLD and vel_pitch < VELOCITY_THRESHOLD:
                prev_yaw = avg_yaw
                prev_pitch = avg_pitch
                time.sleep(0.033)
                continue

        prev_yaw = avg_yaw
        prev_pitch = avg_pitch

        # Offset from center
        offset_yaw = avg_yaw - center_yaw
        offset_pitch = avg_pitch - center_pitch

        # Dead zone
        if abs(offset_yaw) < DEAD_ZONE:
            offset_yaw = 0
        else:
            offset_yaw = (
                offset_yaw - DEAD_ZONE if offset_yaw > 0 else offset_yaw + DEAD_ZONE
            )

        if abs(offset_pitch) < DEAD_ZONE:
            offset_pitch = 0
        else:
            offset_pitch = (
                offset_pitch - DEAD_ZONE
                if offset_pitch > 0
                else offset_pitch + DEAD_ZONE
            )

        # Exponential curve - small moves stay small, accelerates toward edges
        # Preserves sign, applies power curve to magnitude
        EXPO = 2.0  # Higher = more acceleration toward edges
        if offset_yaw != 0:
            sign = 1 if offset_yaw > 0 else -1
            offset_yaw = sign * (abs(offset_yaw) ** EXPO)
        if offset_pitch != 0:
            sign = 1 if offset_pitch > 0 else -1
            offset_pitch = sign * (abs(offset_pitch) ** EXPO)

        # Map to cursor position (reduced sensitivity since expo amplifies)
        target_x = SCREEN_W // 2 + (offset_yaw * SENSITIVITY_X / 3)
        target_y = SCREEN_H // 2 + (offset_pitch * SENSITIVITY_Y / 3)

        # Clamp target to screen FIRST
        target_x = max(0, min(SCREEN_W - 1, target_x))
        target_y = max(0, min(SCREEN_H - 1, target_y))

        # Edge dampening - slow down as we approach edges/corners
        EDGE_MARGIN = 150  # Pixels from edge where dampening kicks in
        MIN_DAMP = 0.3  # Minimum speed at very edge (0.3 = 30% speed)

        # Calculate distance from edges
        dist_left = target_x
        dist_right = SCREEN_W - 1 - target_x
        dist_top = target_y
        dist_bottom = SCREEN_H - 1 - target_y

        # Find closest edge distance
        closest_x = min(dist_left, dist_right)
        closest_y = min(dist_top, dist_bottom)

        # Dampening: 1.0 when far from edge, MIN_DAMP at edge
        damp_x = (
            1.0
            if closest_x > EDGE_MARGIN
            else MIN_DAMP + (1.0 - MIN_DAMP) * (closest_x / EDGE_MARGIN)
        )
        damp_y = (
            1.0
            if closest_y > EDGE_MARGIN
            else MIN_DAMP + (1.0 - MIN_DAMP) * (closest_y / EDGE_MARGIN)
        )

        # Apply dampening (blend toward target more slowly near edges)
        damp = min(damp_x, damp_y)  # Use tightest dampening for corners

        # Apply cursor position update (only if not frozen)
        if not frozen:
            # Apply edge dampening to movement
            target_x_damped = cursor_x + (target_x - cursor_x) * damp
            target_y_damped = cursor_y + (target_y - cursor_y) * damp

            cursor_x = target_x_damped
            cursor_y = target_y_damped

            # Strictly clamp to screen bounds
            cursor_x = max(5, min(SCREEN_W - 5, cursor_x))
            cursor_y = max(5, min(SCREEN_H - 5, cursor_y))

            # Move cursor via GNOME Shell extension
            dbus_call("MoveTo", int(cursor_x), int(cursor_y))

        # Throttle to reduce jitter
        time.sleep(0.033)  # ~30fps

    cap.release()
    tracking_active = False
    print("Tracking stopped.")


def start_tracking():
    global tracking_active, tracking_thread, stop_event, frozen

    if tracking_active:
        return False, "Already tracking"

    frozen = False
    stop_event.clear()
    tracking_active = True
    tracking_thread = threading.Thread(target=run_tracking, daemon=True)
    tracking_thread.start()
    return True, "Tracking"


def stop_tracking():
    global tracking_active, stop_event
    stop_event.set()
    tracking_active = False
    time.sleep(0.2)
    return True, "Stopped"


def recalibrate():
    """Reset calibration - will auto-calibrate on next frames"""
    # center_yaw/pitch are in the tracking thread scope, so restart tracking
    if tracking_active:
        stop_tracking()
        time.sleep(0.3)
        start_tracking()
        return True, "Recalibrating"
    return False, "Not tracking"


def handle(cmd, core):
    global cursor_x, cursor_y
    cmd_lower = cmd.lower()

    # Start tracking
    if any(
        w in cmd_lower for w in ["start tracking", "begin tracking", "enable tracking"]
    ):
        success, msg = start_tracking()
        core.speak(msg)
        if success:
            listen_for_tracking_commands(core)
        return True

    # Stop tracking
    if any(
        w in cmd_lower
        for w in [
            "stop tracking",
            "end tracking",
            "close tracking",
            "quit tracking",
            "disable tracking",
            "tracking off",
            "stop track",
        ]
    ):
        success, msg = stop_tracking()
        core.speak(msg)
        return True

    # Recalibrate
    if "recalibrate" in cmd_lower or "calibrate" in cmd_lower:
        success, msg = recalibrate()
        core.speak(msg)
        return True

    return None


def listen_for_tracking_commands(core):
    """Continuous listening while tracking active"""
    global tracking_active, cursor_x, cursor_y, frozen

    SCREEN_W, SCREEN_H = get_screen_size()

    print("Tracking mode: freeze, nudge, click, or stop tracking")

    while tracking_active:
        try:
            core.stream.read(
                core.stream.get_read_available(), exception_on_overflow=False
            )
        except:
            pass

        first = core.wait_for_speech(timeout=10)
        if not first:
            continue

        audio = first + core.record_until_silence()
        cmd = core.transcribe(
            audio,
            prompt="click double click right click freeze go nudge up down left right recalibrate stop tracking close cancel",
        )
        if not cmd:
            continue

        cmd_lower = cmd.lower().strip()
        print(f"  ← {cmd_lower}")

        # Exit commands
        if any(
            w in cmd_lower
            for w in [
                "stop tracking",
                "end tracking",
                "close tracking",
                "stop",
                "cancel",
                "escape",
                "exit",
                "quit",
                "done",
            ]
        ):
            frozen = False
            stop_tracking()
            core.speak("Stopped")
            return

        # Freeze/Go
        if any(w in cmd_lower for w in ["freeze", "free", "rees", "frees"]):
            frozen = True
            print(f"  → Frozen at ({int(cursor_x)}, {int(cursor_y)})")
            continue

        if cmd_lower in ["go", "go go", "unfreeze", "resume", "track"]:
            frozen = False
            print("  → Resumed")
            continue

        # Nudge (only when frozen)
        if frozen and any(
            w in cmd_lower for w in ["nudge", "move", "up", "down", "left", "right"]
        ):
            if any(w in cmd_lower for w in ["up", "north"]):
                cursor_y = max(0, cursor_y - NUDGE_AMOUNT)
            if any(w in cmd_lower for w in ["down", "south"]):
                cursor_y = min(SCREEN_H - 1, cursor_y + NUDGE_AMOUNT)
            if any(w in cmd_lower for w in ["left", "west"]):
                cursor_x = max(0, cursor_x - NUDGE_AMOUNT)
            if any(w in cmd_lower for w in ["right", "east", "write"]):
                cursor_x = min(SCREEN_W - 1, cursor_x + NUDGE_AMOUNT)
            dbus_call("MoveTo", int(cursor_x), int(cursor_y))
            continue

        # Recalibrate
        if "recalibrate" in cmd_lower or "calibrate" in cmd_lower:
            frozen = False
            recalibrate()
            core.speak("Recalibrating")
            continue

        # Click commands
        if "double" in cmd_lower:
            dbus_call("DoubleClick", int(cursor_x), int(cursor_y))
            continue

        if any(w in cmd_lower for w in ["right click", "right-click", "write click"]):
            dbus_call("RightClick", int(cursor_x), int(cursor_y))
            continue

        if any(
            w in cmd_lower
            for w in ["click", "select", "press", "kick", "quick", "flick"]
        ):
            dbus_call("Click", int(cursor_x), int(cursor_y))
            continue
