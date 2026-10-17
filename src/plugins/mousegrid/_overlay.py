"""Standalone GTK4 layer-shell overlay for the mousegrid plugin's ydotool backend.

Runs as a script in an interpreter that has PyGObject with its cairo bindings
(the click-through input region is a `cairo.Region`, which PyGObject only
converts with `python3-gi-cairo` installed — without it the probe still passes
and the first `show` refuses) and the gtk4-layer-shell typelib, both of which
the daemon's venv lacks. It is a real module rather than an embedded `-c`
string so Ruff lints it and the unit suite can exercise the pure parts (the
`_atspi_insert.py` precedent), which is also why `gi` is imported inside
functions: importing it at module scope would make the whole file unimportable
from the venv.

Protocol: newline-delimited JSON on stdin and stdout, diagnostics on stderr.

    {"cmd": "show", "bounds": [x, y, w, h]}   draw a 3x3 grid over this rect
    {"cmd": "hide"}                            tear the surface down
    {"cmd": "stop"}                            exit (alias: "quit"; EOF does too)

    {"event": "ready", "monitor": [x, y, w, h], "scale": 1.0}
    {"event": "presented"}
    {"event": "error", "message": "..."}

`--probe` answers whether this compositor supports layer-shell and exits 0 or 1
without mapping anything.
"""

import json
import math
import os
import sys
import time
from pathlib import Path

DEFAULT_NAMESPACE = "mousegrid"

# The grid's face is the GNOME extension's face: a user must not be able to
# tell which backend is answering by eye. Every constant below translates one
# CSS declaration from `src/gnome@easyspeak.dev/grid.js` (cited inline), and
# `grid_metrics` mirrors that file's `gridGeometry()` from
# `extension-helpers.js`. The extension is JavaScript and this helper is
# Python, so identity is impossible across the boundary — the duplication is
# confined to this block plus that one pure function, and the unit suite pins
# `grid_metrics`' computed values against the JS's own outputs (and against
# `_common.center`, which shares the centre formula), so a divergence is a
# test failure away instead of a screenshot surprise.
BACKGROUND = (0.0, 0.0, 0.0, 0.15)  # 'background-color: rgba(0,0,0,0.15)'
LINE = (1.0, 1.0, 1.0, 0.8)  # 'background-color: rgba(255,255,255,0.8)'
LINE_THICKNESS = 3  # the divider bars' width/height
LINE_INSET = 1  # the bars' -1 offset: their centre sits on the third
DIGIT = (1.0, 0.902, 0.0, 1.0)  # 'color: #ffe600'
BADGE = (0.0, 0.0, 0.0, 0.8)  # 'background-color: rgba(0,0,0,0.8)'
BADGE_RADIUS = 8  # 'border-radius: 8px'
BADGE_PADDING = (8, 16)  # 'padding: 8px 16px' (vertical, horizontal)
CROSS = (1.0, 0.0, 0.0, 1.0)  # 'background-color: #ff0000'
CROSS_OUTLINE = (1.0, 1.0, 1.0, 1.0)  # 'background-color: #ffffff'
CROSS_THICKNESS = 4  # crossThick
CROSS_OUTLINE_MARGIN = 2  # the white bars' 2px underlay on every side


def grid_metrics(bounds):
    """Mirror `gridGeometry()` (extension-helpers.js) for the drawing code.

    Cell size is integer thirds, the digit font is the cell's third clamped
    to [24, 72], each label's top-left sits half a font left/up of the cell
    centre (the position the extension's St.Label receives), and the centre
    crosshair is capped at 50px. The centre formula is deliberately the same
    as `_common.center`'s — this helper must stay import-standalone (the file
    runs as a script under an interpreter without the package), so the
    equality is enforced by a test instead of by an import. D6 note, carried
    from the drawing it replaced: the plugin computes monitor-local bounds
    and adds the compositor-global origin only at injection time, so nothing
    here may shift by the origin — an earlier revision subtracted it and slid
    the whole grid off the surface.
    """
    bx, by, bw, bh = bounds
    cell_w, cell_h = bw // 3, bh // 3
    font_size = max(24, min(72, min(cell_w, cell_h) // 3))
    cells = []
    for num in range(1, 10):
        row, col = divmod(num - 1, 3)
        zone_x = bx + col * cell_w
        zone_y = by + row * cell_h
        cells.append(
            (
                num,
                zone_x + cell_w / 2 - font_size / 2,
                zone_y + cell_h / 2 - font_size / 2,
            )
        )
    center = (bx + bw // 2, by + bh // 2)
    cross_size = min(50, min(bw, bh) // 3)
    return {
        "cell_w": cell_w,
        "cell_h": cell_h,
        "font_size": font_size,
        "cells": cells,
        "center": center,
        "cross_size": cross_size,
    }


def _rounded_rect(cr, x, y, w, h, radius):
    """Add a rounded rectangle to `cr`'s path (cairo has no native one)."""
    cr.new_sub_path()
    cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _transparent_background(gtk, window):
    """Make the window itself transparent, so the desktop shows through.

    The extension's actors float over the live desktop: grid.js paints a
    0.15 wash over the bounds and nothing else. A GTK window, though, paints
    its theme background under everything its content leaves unpainted -
    opaque, and light on this session's theme - which showed up on the glass
    as a full-monitor white sheet carrying the grid (measured live,
    2026-10-16: the offscreen render was correct and the compositor shot was
    white). A transparent window background restores the extension's
    compositing: only what we draw reaches the glass, and the wash, badges
    and crosshair composite over the real desktop exactly as the
    extension's actors do over the shell.
    """
    from gi.repository import Gdk

    provider = gtk.CssProvider()
    provider.load_from_data(b"window, drawingarea { background: transparent; }")
    display = window.get_display() or Gdk.Display.get_default()
    gtk.StyleContext.add_provider_for_display(
        display, provider, gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def parse_command(line):
    """Return the command object on a protocol line, or None if there is none."""
    line = line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except ValueError:
        sys.stderr.write(f"grid-overlay: ignoring unparsable line: {line[:120]}\n")
        return None
    return payload if isinstance(payload, dict) else None


def usable_bounds(command):
    """Return the integer bounds list a show command must carry, or None.

    Mirrors parse_command's absorb-and-log: one malformed message must not
    take the stdin watch — and the mapped grid — down with a KeyError. The
    integer check mirrors the ready event's own geometry sanity test.
    """
    bounds = command.get("bounds")
    if (
        isinstance(bounds, list)
        and len(bounds) == 4
        and all(isinstance(v, int) and not isinstance(v, bool) for v in bounds)
    ):
        return bounds
    return None


def take_lines(pending, chunk):
    """Split every complete line out of `pending + chunk`.

    Returns `(lines, remainder)`: the newline-terminated lines in order, and
    the trailing fragment that has not arrived completely yet. Splitting the
    whole buffer - instead of reading one line per wake-up - is what keeps a
    command that sits behind another one in the same write from being
    stranded where no io watch can see it.
    """
    lines = (pending + chunk).split("\n")
    return lines[:-1], lines[-1]


def emit(payload):
    """Write one event to the parent."""
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def layer_shell_names():
    """The loadable names for gtk4-layer-shell, most specific first.

    `ctypes.util.find_library` asks the loader's own cache, so an installed
    runtime is found by *soname*: Ubuntu 25.10's `libgtk4-layer-shell0` ships
    only `libgtk4-layer-shell.so.0`, and the unversioned `.so` symlink belongs
    to the `-dev` package a normal user does not have. The soname and the plain
    name are literal fallbacks: the plain one covers an uninstalled build tree
    on `LD_LIBRARY_PATH`, which ldconfig cannot see.

    Only a result that names this library is trusted. `find_library` answers
    with the soname *inside* the file that spells the queried name, so a stale
    or misnamed `libgtk4-layer-shell.so` on the loader path answers with that
    file's own soname (measured: a copy of libm under that name answered
    `libm.so.6`). Loading that answer would preload an unrelated library and
    the link order this load exists for would be silently lost.
    """
    from ctypes.util import find_library

    names = []
    found = find_library("gtk4-layer-shell")
    if found and Path(found).name.startswith("libgtk4-layer-shell."):
        names.append(found)
    for candidate in ("libgtk4-layer-shell.so.0", "libgtk4-layer-shell.so"):
        if candidate not in names:
            names.append(candidate)
    return names


def layer_shell_lib_path(build=None):
    """The first loadable layer-shell library for LD_PRELOAD, or None.

    The helper must receive this on LD_PRELOAD: gtk4-layer-shell works by
    interposing libwayland, and interposition only reaches GTK when the library
    sits at the front of the lookup order — RTLD_GLOBAL cannot win, because
    libwayland-client is a direct dependency of GDK and beats the global scope
    (measured live: without the preload the layer surface came up as an
    ordinary window and the probe answered unsupported on a compositor that
    supports layer shell). The driver process loads the name here as a
    loadability probe; the real load happens in the helper under LD_PRELOAD.

    With `build` (an `EASYSPEAK_GRID_TYPELIB` tree) the sonames are resolved
    INSIDE the tree first, as absolute paths: the loader reads
    LD_LIBRARY_PATH once at process start, so this process can never see the
    path that `helper_env` constructs for the child, and an in-process CDLL
    walk would answer None and leave the documented build-tree fallback
    without its preload. Existence is the whole check here — the child's own
    loader environment is what decides loadability, and it names the tree.
    """
    if build:
        for candidate in sorted(Path(build).glob("libgtk4-layer-shell.so*")):
            return str(candidate)
    from ctypes import CDLL

    for name in layer_shell_names():
        try:
            CDLL(name)
        except OSError:
            continue
        else:
            return name
    return None


def load_layer_shell():
    """Load gtk4-layer-shell and Gtk, or return (None, None).

    The library must be loaded before Gtk's Wayland client is, which is what the
    CDLL call buys: linking it later lets libwayland-client win the symbol
    resolution and the layer surface silently comes up as an ordinary window.
    The names are tried in `layer_shell_names()` order, so a runtime that ships
    only the soname still loads; the load happens before `gi` regardless.
    """
    from ctypes import CDLL

    names = layer_shell_names()
    error = None
    for name in names:
        try:
            CDLL(name)
        except OSError as exc:
            error = exc
        else:
            break
    else:
        sys.stderr.write(
            f"grid-overlay: gtk4-layer-shell not found "
            f"(tried {', '.join(names)}): {error}\n"
        )
        return None, None
    try:
        import gi
    except ModuleNotFoundError as exc:
        # The daemon's venv: a loadable library with PyGObject missing. A bare
        # import here used to escape as a traceback, skipping every caller's
        # error path (reproduced with a dummy library on the loader path:
        # `--probe` under the venv died on this line).
        sys.stderr.write(f"grid-overlay: PyGObject is not installed: {exc}\n")
        return None, None

    try:  # pragma: no cover - needs the layer-shell typelib from the live stack
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk, Gtk4LayerShell
    except (ValueError, ImportError) as exc:  # pragma: no cover - live stack only
        sys.stderr.write(f"grid-overlay: cannot load Gtk4LayerShell: {exc}\n")
        return None, None
    return Gtk, Gtk4LayerShell  # pragma: no cover - live stack only


def is_supported():
    """True when this compositor speaks wlr-layer-shell.

    GTK must have opened a display before the question is asked:
    `gtk4_layer_shell_is_supported()` reads the default display and answers
    false with a gdk assertion when none is open. `Gtk.init` opens it — and
    PyGObject returns None for it (a void function), so testing its return
    value as truthiness answered False unconditionally (measured live: the
    probe refused on sway, which supports layer shell).
    """
    Gtk, layer_shell = load_layer_shell()
    if Gtk is None or layer_shell is None:
        return False
    Gtk.init()
    from gi.repository import Gdk, GLib

    # The Wayland registry arrives through the main context: without running
    # it, is_supported reads before the compositor's globals are known and
    # answers false on compositors that do support layer shell. Bound the
    # wait; a compositor that never answers fails closed in two seconds.
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + 2.0
    supported = False
    while time.monotonic() < deadline:
        while ctx.iteration(may_block=False):
            pass
        if Gdk.Display.get_default() is None:
            return False
        if layer_shell.is_supported():
            supported = True
            break
        time.sleep(0.03)
    return supported


def clear_input_region(surface):
    """Empty the surface's input region, so clicks pass through it.

    `set_can_target(False)` is not enough on this stack: with it alone the
    click is swallowed - neither window receives it - while an empty input
    region lets the window below receive it (measured on GTK 4.6.9, two
    stacked windows, an XTest click). The feature is exactly a click injected
    while the pointer is over this surface, so a swallowing surface breaks it
    silently.

    Returns None on success, or a diagnostic when the region cannot be
    applied; the caller must refuse rather than present the surface without it.
    """
    try:
        import cairo

        surface.set_input_region(cairo.Region())
    except (ImportError, AttributeError, TypeError) as exc:
        return f"cannot clear the input region: {exc}"
    return None


class Overlay:  # pragma: no cover - needs GTK; run live
    """The layer surface, its nine cells, and the redraws they ask for."""

    def __init__(self, gtk, layer_shell, app):
        self.gtk = gtk
        self.layer_shell = layer_shell
        # Associate the window with the application: an app-managed window is what
        # the application's lifecycle (activate, quit, and the stdin watch that
        # ends the process) is written for.
        self.window = gtk.Window(application=app)
        _transparent_background(gtk, self.window)
        self.area = gtk.DrawingArea()
        self.bounds = None
        self.presented = False
        self.window.set_child(self.area)
        self.area.set_draw_func(self._draw)
        layer_shell.init_for_window(self.window)
        for edge in (
            layer_shell.Edge.LEFT,
            layer_shell.Edge.RIGHT,
            layer_shell.Edge.TOP,
            layer_shell.Edge.BOTTOM,
        ):
            layer_shell.set_anchor(self.window, edge, True)  # noqa: FBT003
        layer_shell.set_layer(self.window, layer_shell.Layer.OVERLAY)
        # Span the whole monitor, panel and dock strips included. Layer-shell
        # surfaces default to exclusive zone 0, which smithay resolves to
        # "monitor minus every strip that claimed an exclusive zone" — the
        # panel and dock are two cosmic-panel instances claiming exactly such
        # zones, so with the default this surface ended at the strips, and
        # zooming into them drew cells that were cut off the glass entirely
        # (measured: a depth-3 zoom into the dock rendered nothing at all).
        # -1 is the layer-shell "ignore exclusive zones" value, and cosmic-
        # osd's overlays are the in-tree precedent for it: plain Overlay
        # layer, zone -1, which is the whole reason they float above the
        # panels (source-verified: smithay's layer mapping sizes the surface
        # by the zone, layer.rs:311-347; cosmic-comp orders Overlay above
        # Top, focus/order.rs:180-196; cosmic-osd osd_indicator.rs:200-203).
        layer_shell.set_exclusive_zone(self.window, -1)
        # Never take focus, and never eat the injected click. `set_can_target`
        # stops GTK from targeting the window; the empty input region - applied
        # by `make_click_through` as soon as the surface exists - is what
        # actually lets the click reach whatever is underneath.
        layer_shell.set_keyboard_mode(self.window, layer_shell.KeyboardMode.NONE)
        self.window.set_can_target(False)
        self.click_through_surface = None

    def _draw(self, area, cr, width, height):
        """Paint the grid exactly as the GNOME extension paints it (grid.js).

        Same wash over the bounds, same divider bars, same yellow-on-dark
        badges, same centre crosshair — every constant cites the CSS it
        translates (see the block at the top of this file), and the numeric
        layout comes from `grid_metrics`. The drawing is bounds-local by
        construction: the plugin adds the monitor's compositor-global origin
        only at injection time (design D6), so nothing here may shift by it —
        an earlier revision subtracted it and slid the whole grid off the
        surface. PyGObject calls a `set_draw_func` callback with exactly these
        four arguments - it does not pass the C callback's trailing user_data -
        and a five-argument signature raises TypeError on every frame, which
        loses both the grid and the `presented` event.
        """
        del area, width, height
        if not self.bounds:
            return
        import cairo

        bx, by, bw, bh = self.bounds
        metrics = grid_metrics(self.bounds)

        cr.set_source_rgba(*BACKGROUND)
        cr.rectangle(bx, by, bw, bh)
        cr.fill()
        cr.set_source_rgba(*LINE)
        for i in (1, 2):
            cr.rectangle(
                bx + i * metrics["cell_w"] - LINE_INSET, by, LINE_THICKNESS, bh
            )
        for i in (1, 2):
            cr.rectangle(
                bx, by + i * metrics["cell_h"] - LINE_INSET, bw, LINE_THICKNESS
            )
        cr.fill()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(metrics["font_size"])
        for num, x, y in metrics["cells"]:
            extents = cr.text_extents(str(num))
            cr.set_source_rgba(*BADGE)
            _rounded_rect(
                cr,
                x,
                y,
                extents.width + 2 * BADGE_PADDING[1],
                extents.height + 2 * BADGE_PADDING[0],
                BADGE_RADIUS,
            )
            cr.fill()
            cr.set_source_rgba(*DIGIT)
            cr.move_to(
                x + BADGE_PADDING[1] - extents.x_bearing,
                y + BADGE_PADDING[0] - extents.y_bearing,
            )
            cr.show_text(str(num))

        center_x, center_y = metrics["center"]
        size = metrics["cross_size"]
        half, half_thick = size / 2, CROSS_THICKNESS / 2
        cr.set_source_rgba(*CROSS_OUTLINE)
        cr.rectangle(
            center_x - half - CROSS_OUTLINE_MARGIN,
            center_y - half_thick - CROSS_OUTLINE_MARGIN,
            size + 2 * CROSS_OUTLINE_MARGIN,
            CROSS_THICKNESS + 2 * CROSS_OUTLINE_MARGIN,
        )
        cr.rectangle(
            center_x - half_thick - CROSS_OUTLINE_MARGIN,
            center_y - half - CROSS_OUTLINE_MARGIN,
            CROSS_THICKNESS + 2 * CROSS_OUTLINE_MARGIN,
            size + 2 * CROSS_OUTLINE_MARGIN,
        )
        cr.fill()
        cr.set_source_rgba(*CROSS)
        cr.rectangle(center_x - half, center_y - half_thick, size, CROSS_THICKNESS)
        cr.rectangle(center_x - half_thick, center_y - half, CROSS_THICKNESS, size)
        cr.fill()

        if not self.presented:
            # The first frame of an actual grid is on the glass now; the plugin
            # reads this as "it is on screen", once, never per redraw.
            self.presented = True
            emit({"event": "presented"})

    def make_click_through(self):
        """Give the surface an empty input region, or say why it could not.

        Returns None when the surface is click-through already, or has not
        been created yet - the ready poll retries - and a diagnostic string
        otherwise; the caller refuses the session on a diagnostic, because a
        surface that cannot be made click-through must not be presented as if
        the click would pass through it.
        """
        surface = self.window.get_surface()
        if surface is None or surface is self.click_through_surface:
            return None
        problem = clear_input_region(surface)
        if problem is None:
            self.click_through_surface = surface
        return problem

    def show(self, bounds):
        """Draw the grid over `bounds`; a diagnostic means refuse the session.

        The region is re-checked here, on every show: a surface presented later
        must not go up without it.
        """
        self.bounds = tuple(bounds)
        self.window.present()
        self.area.queue_draw()  # the bounds changed: repaint, mapped or not
        return self.make_click_through()

    def hide(self):
        self.window.set_visible(False)


def report_monitor(overlay):  # pragma: no cover - needs a live surface
    """Emit the ready event once the surface is configured.

    The monitor geometry comes from the surface, not from an assumption: the
    compositor chooses the output (the helper makes no set_monitor call), and
    this report is the plugin's only source of screen size. The origin is the
    compositor-global one and rides along for the plugin's injection
    arithmetic; the drawing must stay in the surface's own space and never
    apply it (see `grid_metrics`).
    """
    surface = overlay.window.get_surface()
    display = surface.get_display()
    monitor = display.get_monitor_at_surface(surface)
    geometry = monitor.get_geometry()
    emit(
        {
            "event": "ready",
            "monitor": [geometry.x, geometry.y, geometry.width, geometry.height],
            "scale": monitor.get_scale_factor(),
        }
    )


def run(gtk, layer_shell):  # pragma: no cover - drives the GTK loop
    """Wire the protocol to the surface and pump the GTK loop."""
    import gi

    GLib = gi.repository.GLib

    app = gtk.Application(application_id="dev.easyspeak.mousegrid.overlay")
    overlay = None
    fatal = None

    def refuse(problem):
        """Emit the refusal instead of the surface that could not be made safe."""
        nonlocal fatal
        fatal = problem
        emit({"event": "error", "message": problem})
        app.quit()
        return False

    def on_activate(_app):
        """Build and present the surface inside the application's lifetime.

        The window cannot be made before `app.run`: GTK refuses to add a window
        created before the `startup` signal ("New application windows must be
        added after the GApplication::startup signal has been emitted"), and an
        application holding no windows returns from `run` as soon as activation
        ends - which would end the helper right after `ready` and leave the
        plugin talking to a corpse.
        """
        nonlocal overlay
        overlay = Overlay(gtk, layer_shell, app)
        overlay.window.present()
        GLib.idle_add(emit_ready_when_mapped)

    def emit_ready_when_mapped():
        """Report geometry only once the surface exists, then stop polling.

        `ready` is what the plugin waits for before it can compute a single
        coordinate, so it must be sent after GTK has a surface to ask, not
        from the constructor where there is none yet - and only after the
        surface has been made click-through, or the click this grid aims would
        be swallowed before it arrived.
        """
        if overlay is None or overlay.window.get_surface() is None:
            return True
        problem = overlay.make_click_through()
        if problem is not None:
            return refuse(problem)
        report_monitor(overlay)
        return False

    app.connect("activate", on_activate)

    pending = ""

    def handle_line(line):
        """Act on one protocol line; False means the process should end."""
        command = parse_command(line)
        if command is None:
            return True
        name = command.get("cmd")
        if name == "show" and overlay is not None:
            bounds = usable_bounds(command)
            if bounds is None:
                sys.stderr.write(
                    f"grid-overlay: ignoring show without usable bounds: {command}\n"
                )
                return True
            problem = overlay.show(bounds)
            if problem is not None:
                return refuse(problem)
        elif name == "hide" and overlay is not None:
            overlay.hide()
        elif name in ("stop", "quit"):
            app.quit()
            return False
        return True

    def on_stdin_ready(_source, _condition):
        """Consume every complete line the descriptor holds, not just one.

        One chunk is read per wake-up and `take_lines` splits every complete
        line out of it - a `stop` behind another command in the same write must
        not be stranded where no watch can see it - while a partial line waits
        in `pending` for the next wake-up.
        """
        nonlocal pending
        chunk = os.read(sys.stdin.fileno(), 4096)
        if not chunk:  # the plugin is gone; never outlive it
            app.quit()
            return False
        lines, pending = take_lines(pending, chunk.decode("utf-8", "replace"))
        # `all` short-circuits at the first `stop`/`quit`, same as a loop would.
        return all(handle_line(line) for line in lines)

    GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, on_stdin_ready)
    app.run([])
    return 1 if fatal is not None else 0


def main(argv=None):
    """Entry point: `--probe` one-shots the support question, otherwise serve."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--probe" in argv:
        supported = is_supported()
        sys.stdout.write("supported\n" if supported else "unsupported\n")
        return 0 if supported else 1
    Gtk, layer_shell = load_layer_shell()
    if Gtk is None:
        emit(
            {
                "event": "error",
                "message": "PyGObject or the layer-shell typelib is missing",
            }
        )
        return 1
    # Gate on the full support path, not the library's raw answer: this is a
    # fresh process that must open its own display and wait for the Wayland
    # registry, and the raw query skips both (an immediate call can answer
    # unsupported on a capable, slow-to-advertise compositor). The load above
    # only carries the diagnostic message; is_supported() reuses it from the
    # loader cache.
    if not is_supported():
        # Refuse rather than degrade: an ordinary window would look like a
        # rendering bug while the injections kept working.
        emit({"event": "error", "message": "layer-shell unsupported"})
        return 1
    return run(Gtk, layer_shell)


if __name__ == "__main__":
    raise SystemExit(main())
