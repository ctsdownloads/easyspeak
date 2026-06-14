"""Standalone libadwaita "About EasySpeak" window.

The daemon is headless and the panel indicator lives in a GNOME Shell extension
(Clutter/St), which can't host GTK widgets; so the About dialog runs as its own
short-lived process that the tray launches via ``python -m easyspeak.core.about``
on the menu's "About" command. It uses libadwaita's ``AboutDialog`` (the modern,
GNOME-recommended widget), falling back to the older ``AboutWindow`` on
pre-1.5 libadwaita.

Everything GUI is imported lazily inside :func:`main` so this module stays
importable (for its metadata constants and version lookup) without PyGObject or
a display present — which is how the unit suite exercises it.
"""

import importlib.metadata

# --- Project metadata (single source of truth, shared with the tray) ---

APP_ID = "io.github.ctsdownloads.EasySpeak"
APPLICATION_NAME = "EasySpeak"
# A themed icon that ships with every GNOME install; the project has no icon of
# its own to bundle, and a microphone reads true for a voice assistant.
APPLICATION_ICON = "audio-input-microphone"
COMMENTS = "Voice control for Linux desktops. Fully local, no cloud, Wayland-native."
COPYRIGHT = "© Matt Hartley and the EasySpeak contributors"

REPO_URL = "https://github.com/ctsdownloads/easyspeak"
DOCS_URL = "https://ctsdownloads.github.io/easyspeak/"
ISSUES_URL = "https://github.com/ctsdownloads/easyspeak/issues"

# The author/maintainer, shown as the headline developer.
DEVELOPER_NAME = "Matt Hartley"
DEVELOPERS = ["Matt Hartley <matt@matthartley.com>"]

# Everyone else who has landed changes (bots excluded), shown in their own
# credit section alongside the maintainer.
CONTRIBUTORS = [
    "Peter Bittner <peter@painless.software>",
    "Tulip Blossom <tulilirockz@outlook.com>",
    "Wolfgang Karl <kontakt@wkarl.net>",
    "gband85 <gband85@mailfence.com>",
]


def app_version():
    """Return the installed package version, or "" if it can't be determined.

    Read at runtime (rather than hard-coded) so the dialog always shows the
    version actually installed; an editable/source checkout without dist
    metadata simply shows no version rather than failing.
    """
    try:
        return importlib.metadata.version("easyspeak-linux")
    except importlib.metadata.PackageNotFoundError:
        return ""


def main():  # pragma: no cover - needs libadwaita and a display; run live
    """Show the About window and run until the user closes it."""
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio

    app = Adw.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
    app.connect("activate", _present)
    return app.run(None)


def _present(app):  # pragma: no cover - needs libadwaita and a display; run live
    """Build and present the About UI, quitting the app once it's dismissed."""
    from gi.repository import Adw, Gtk

    if hasattr(Adw, "AboutDialog"):
        # libadwaita >= 1.5: the modern widget. A dialog attaches to a parent
        # window; create a minimal host purely to own it, and quit on close.
        dialog = Adw.AboutDialog(
            application_name=APPLICATION_NAME,
            application_icon=APPLICATION_ICON,
            version=app_version(),
            comments=COMMENTS,
            website=REPO_URL,
            issue_url=ISSUES_URL,
            developer_name=DEVELOPER_NAME,
            developers=DEVELOPERS,
            copyright=COPYRIGHT,
            license_type=Gtk.License.GPL_3_0,
        )
        dialog.add_link("Documentation", DOCS_URL)
        dialog.add_credit_section("Contributors", CONTRIBUTORS)
        host = Gtk.ApplicationWindow(application=app)
        dialog.connect("closed", lambda *_: app.quit())
        dialog.present(host)
    else:
        # libadwaita < 1.5: the older self-contained About window.
        window = Adw.AboutWindow(
            application=app,
            application_name=APPLICATION_NAME,
            application_icon=APPLICATION_ICON,
            version=app_version(),
            comments=COMMENTS,
            website=REPO_URL,
            issue_url=ISSUES_URL,
            developer_name=DEVELOPER_NAME,
            developers=DEVELOPERS,
            copyright=COPYRIGHT,
            license_type=Gtk.License.GPL_3_0,
        )
        window.add_link("Documentation", DOCS_URL)
        window.add_credit_section("Contributors", CONTRIBUTORS)
        window.present()


if __name__ == "__main__":
    main()
