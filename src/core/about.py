"""Standalone libadwaita "About EasySpeak" window.

The daemon is headless and the panel indicator lives in a GNOME Shell extension
(Clutter/St), which can't host GTK widgets; so the About dialog runs as its own
short-lived process that the tray launches via `python -m easyspeak.core.about` on the
menu's "About" command. It uses libadwaita's `AboutDialog` (the modern,
GNOME-recommended widget), falling back to the older `AboutWindow` on pre-1.5
libadwaita.

Everything GUI is imported lazily inside [`main`][core.about.main] so this module stays
importable (for its metadata constants and version lookup) without PyGObject or a
display present — which is how the unit suite exercises it.
"""

import importlib.metadata

APP_ID = "io.github.ctsdownloads.EasySpeak"
APPLICATION_NAME = "EasySpeak"
APPLICATION_ICON = "audio-input-microphone"  # from GNOME's adwaita-icon-theme
COMMENTS = "Voice control for Linux desktops. Fully local, no cloud, Wayland-native."
COPYRIGHT = "© Matt Hartley and the EasySpeak contributors"

REPO_URL = "https://github.com/ctsdownloads/easyspeak"
DOCS_URL = "https://easyspeak.dev/"
ISSUES_URL = "https://github.com/ctsdownloads/easyspeak/issues"
DISCUSSIONS_URL = "https://github.com/ctsdownloads/easyspeak/discussions"

DEVELOPER_NAME = "Matt Hartley"
DEVELOPERS = ["Matt Hartley <matt@matthartley.com>"]

CONTRIBUTORS = [
    "Peter Bittner <peter@painless.software>",
    "Tulip Blossom <tulilirockz@outlook.com>",
    "Wolfgang Karl <kontakt@wkarl.net>",
    "gband85 <gband85@mailfence.com>",
]

# The models EasySpeak ships or fetches, under their own licenses; shown in the
# About window's legal section. The voices carry their training data's terms.
LEGAL = [
    ("Parakeet TDT 0.6b v3 speech model", "© NVIDIA Corporation", "CC-BY-4.0"),
    ("Whisper speech models", "© OpenAI, converted to CTranslate2 by SYSTRAN", "MIT"),
    ("Hey Jarvis wake-word model (openWakeWord)", "© David Scripka", "Apache-2.0"),
    ("Piper voice en_US-amy", "© Mycroft AI (Mimic 3 voices)", "CC-BY-SA-4.0"),
    ("Piper voice de_DE-thorsten", "© Thorsten Müller", "CC0-1.0"),
    ("Piper voice it_IT-paola", "© Paola Persico", "CC0-1.0"),
    ("Piper voice fr_FR-siwis", "© SIWIS, University of Edinburgh", "CC-BY-4.0"),
    ("Piper voice es_ES-davefx", "© davefx (OHF voice datasets)", "CC0-1.0"),
]
# Creative Commons terms have no Gtk.License member, so they are shown as a link.
LICENSE_URLS = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
}


def app_version():
    """Return the installed package version, or "" if it can't be determined.

    Read at runtime (rather than hard-coded) so the dialog always shows the version
    actually installed; an editable/source checkout without dist metadata simply shows
    no version rather than failing.
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
    """Build and present the About UI, quitting the app once it's dismissed.

    We need to distinguish between the modern widget (libadwaita >= 1.5) and the older
    self-contained About window (libadwaita < 1.5). For the former, we must attach the
    dialog to a parent window, a minimal host purely to own it, and quit on close.
    """
    from gi.repository import Adw, Gtk

    if hasattr(Adw, "AboutDialog"):
        dialog = Adw.AboutDialog(
            application_name=APPLICATION_NAME,
            application_icon=APPLICATION_ICON,
            version=app_version(),
            comments=COMMENTS,
            website=DOCS_URL,
            issue_url=ISSUES_URL,
            developer_name=DEVELOPER_NAME,
            developers=DEVELOPERS,
            copyright=COPYRIGHT,
            license_type=Gtk.License.GPL_3_0,
        )
        dialog.add_link("Source Code", REPO_URL)
        dialog.add_link("Discussions", DISCUSSIONS_URL)
        dialog.add_credit_section("Contributors", CONTRIBUTORS)
        _add_legal_sections(dialog, Gtk)
        host = Gtk.ApplicationWindow(application=app)
        dialog.connect("closed", lambda *_: app.quit())
        dialog.present(host)
    else:
        window = Adw.AboutWindow(
            application=app,
            application_name=APPLICATION_NAME,
            application_icon=APPLICATION_ICON,
            version=app_version(),
            comments=COMMENTS,
            website=DOCS_URL,
            issue_url=ISSUES_URL,
            developer_name=DEVELOPER_NAME,
            developers=DEVELOPERS,
            copyright=COPYRIGHT,
            license_type=Gtk.License.GPL_3_0,
        )
        window.add_link("Source Code", REPO_URL)
        window.add_link("Discussions", DISCUSSIONS_URL)
        window.add_credit_section("Contributors", CONTRIBUTORS)
        _add_legal_sections(window, Gtk)
        window.present()


def _add_legal_sections(about, gtk):  # pragma: no cover - needs libadwaita; run live
    """List the models and their licenses; both About widgets take the same call."""
    known = {"MIT": gtk.License.MIT_X11, "Apache-2.0": gtk.License.APACHE_2_0}
    for title, owner, license_id in LEGAL:
        if license_id in known:
            about.add_legal_section(title, owner, known[license_id], None)
        else:
            about.add_legal_section(
                title,
                owner,
                gtk.License.CUSTOM,
                f'<a href="{LICENSE_URLS[license_id]}">{license_id}</a>',
            )


if __name__ == "__main__":
    main()
