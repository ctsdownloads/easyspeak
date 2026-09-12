"""Tests for the reply translations."""

from pathlib import Path

import polib
from easyspeak.core import i18n

CATALOG = """\
msgid ""
msgstr ""
"Content-Type: text/plain; charset=utf-8\\n"

msgid "Opening {app}."
msgstr "{app} wird geöffnet."

msgid "Done"
msgstr ""
"""


def fake_plugin(tmp_path, language="de"):
    """Return a fake plugin package, with a `.po` for `language` unless None."""
    package = tmp_path / "apps"
    package.mkdir()
    if language:
        messages = package / "locale" / language / "LC_MESSAGES"
        messages.mkdir(parents=True)
        (messages / "apps.po").write_text(CATALOG, encoding="utf-8")
    return package / "__init__.py"


def test_translates_from_the_po_beside_the_package(tmp_path):
    """The package directory names the domain; its `locale/` holds the `.po`."""
    _ = i18n.translator(fake_plugin(tmp_path), language="de")

    assert _("Opening {app}.").format(app="Firefox") == "Firefox wird geöffnet."


def test_untranslated_strings_stay_english(tmp_path):
    """An entry without a translation, or absent from the catalog, is the source."""
    _ = i18n.translator(fake_plugin(tmp_path), language="de")

    assert _("Done") == "Done"
    assert _("No such string") == "No such string"


def test_without_a_catalog_everything_stays_english(tmp_path):
    """A plugin that ships no `locale/` speaks English."""
    _ = i18n.translator(fake_plugin(tmp_path, language=None), language="de")

    assert _("Done") == "Done"


def test_defaults_to_the_reply_language(tmp_path, monkeypatch):
    """Without an explicit language, the catalog of `REPLY_LANGUAGE` is used."""
    monkeypatch.setattr(i18n.config, "REPLY_LANGUAGE", "de")

    _ = i18n.translator(fake_plugin(tmp_path))

    assert _("Opening {app}.") == "{app} wird geöffnet."


def test_every_shipped_package_binds_a_translator():
    """The core and each plugin bind `_` to their own directory."""
    src = Path(i18n.__file__).parent.parent
    plugins = (src / "plugins").iterdir()
    packages = [src / "core", *(p for p in plugins if (p / "__init__.py").is_file())]

    for package in packages:
        code = (
            package / ("i18n.py" if package.name == "core" else "__init__.py")
        ).read_text(encoding="utf-8")
        assert "_ = translator(__file__)" in code, package.name


def test_every_shipped_catalog_is_complete():
    """A shipped `.po` has no empty or fuzzy entry: what it ships, it speaks."""
    src = Path(i18n.__file__).parent.parent
    for catalog in src.glob("**/locale/*/LC_MESSAGES/*.po"):
        for entry in polib.pofile(str(catalog)):
            if entry.msgid and not entry.obsolete:
                assert entry.msgstr, (catalog, entry.msgid)
                assert "fuzzy" not in entry.flags, (catalog, entry.msgid)
