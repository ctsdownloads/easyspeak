"""Fullscreen GTK4 probe that reports what the pointer does.

Prints one JSON object per line: motion and press, with surface-local
coordinates. In the harness's single-output session that is also the absolute
position, which is what turns "the pointer landed in the cell" into an assertion
instead of an eyeball.
"""

import json
import sys


def main():
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    def emit(**payload):
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    def on_activate(app):
        window = Gtk.Window(application=app)
        area = Gtk.DrawingArea()
        window.set_child(area)
        window.fullscreen()

        motion = Gtk.EventControllerMotion()
        motion.connect(
            "motion",
            lambda _c, x, y: emit(event="motion", x=int(x), y=int(y)),
        )
        window.add_controller(motion)

        click = Gtk.GestureClick()
        click.connect(
            "pressed",
            lambda _g, _n, x, y: emit(event="press", button=1, x=int(x), y=int(y)),
        )
        window.add_controller(click)
        window.present()

    app = Gtk.Application(application_id="dev.easyspeak.mousegrid.probe")
    app.connect("activate", on_activate)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
