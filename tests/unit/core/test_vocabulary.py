"""Tests for the vocabulary tables: what a package listens for, per language."""

from pathlib import Path

import pytest
from easyspeak.core import vocabulary

EN = """\
[commands]
open = ["open", "launch"]
close = ["close"]

[apps]
calculator = ["calculator"]
settings = ["settings"]
"""

DE = """\
[commands]
open = ["öffne", "starte"]

[apps]
calculator = ["rechner", "taschenrechner"]
"""


@pytest.fixture
def package(tmp_path):
    """A fake plugin package with an English and a German table."""
    for code, text in (("en", EN), ("de", DE)):
        table = tmp_path / "locale" / code
        table.mkdir(parents=True)
        (table / "vocabulary.toml").write_text(text, encoding="utf-8")
    return tmp_path / "__init__.py"


def test_load_table_returns_none_without_a_table(tmp_path):
    """A language without a table is simply absent, not an error."""
    assert vocabulary.load_table(tmp_path, "fr") is None


def test_load_table_reads_under_the_given_locale_dir(package):
    """The directory given is the locale root itself, no `locale/` appended."""
    table = vocabulary.load_table(package.parent / "locale", "de")

    assert table["commands"]["open"] == ["öffne", "starte"]


def test_german_phrases_come_first_and_english_stay(package):
    """The active language's ways of saying a key precede the English ones."""
    vocab = vocabulary.Vocabulary(package, language="de")

    assert vocab.phrases("open") == ["öffne", "starte", "open", "launch"]
    assert vocab.phrases("close") == ["close"]


def test_says_matches_whole_words_in_either_language(package):
    """ "öffne" and "open" both say open; "reopened" says nothing."""
    vocab = vocabulary.Vocabulary(package, language="de")

    assert vocab.says("öffne den rechner", "open")
    assert vocab.says("open the calculator", "open")
    assert not vocab.says("reopened", "open")


def test_ends_takes_the_phrase_at_the_end_only(package):
    """ "jarvis close" ends with the exit-style phrase; "close tab" does not."""
    vocab = vocabulary.Vocabulary(package, language="de")

    assert vocab.ends("close", "close")
    assert vocab.ends("jarvis close", "close")
    assert not vocab.ends("close tab", "close")


def test_which_names_the_key_said_in_either_language(package):
    """The German word for the calculator resolves to the English key."""
    vocab = vocabulary.Vocabulary(package, language="de")

    assert vocab.which("öffne den taschenrechner", "apps") == "calculator"
    assert vocab.which("open settings", "apps") == "settings"
    assert vocab.which("open nothing", "apps") is None


def test_keys_list_every_key_once(package):
    """Keys of both tables, the active language's first, without repeats."""
    vocab = vocabulary.Vocabulary(package, language="de")

    assert vocab.keys("apps") == ["calculator", "settings"]


def test_english_uses_the_english_table_once(package):
    """With English active there is one table, not the same one twice."""
    vocab = vocabulary.Vocabulary(package, language="en")

    assert len(vocab.tables) == 1
    assert vocab.phrases("open") == ["open", "launch"]


def test_language_defaults_to_the_configured_one(package, monkeypatch):
    """Without an explicit language the configured `LANGUAGE` is used."""
    from easyspeak.core import config

    monkeypatch.setattr(config, "LANGUAGE", "de")

    assert vocabulary.Vocabulary(package).phrases("open")[0] == "öffne"


SHIPPED = ("de", "it", "fr", "es")
PACKAGES = sorted(
    p.parent.parent.parent
    for p in Path(vocabulary.__file__).parent.parent.glob(
        "**/locale/en/vocabulary.toml"
    )
)


@pytest.mark.parametrize("language", SHIPPED)
@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.name)
def test_every_shipped_table_matches_the_english_one(package, language):
    """A language's table has the English sections and keys, with phrases in each.

    The tables are recognition data the plugins execute, so a typo in a key or
    a section would silently drop a command in that language.
    """
    english = vocabulary.load_table(package / "locale", "en")
    table = vocabulary.load_table(package / "locale", language)
    assert table is not None, f"{package.name} has no {language} table"

    assert set(table) <= set(english), (
        package.name,
        language,
        set(table) - set(english),
    )
    for section, entries in table.items():
        if isinstance(entries, list):  # an array of tables, like dictation's replace
            for entry in entries:
                assert entry.get("say") and all(
                    isinstance(v, str) and v for v in entry["say"]
                ), (package.name, language, section, entry)
                assert "insert" in entry, (package.name, language, section, entry)
            continue
        # The numeric sections are keyed by the language's own words; every
        # other key is an identifier the plugin indexes with, English only.
        keyed_by_word = section in ("numbers", "counts")
        assert keyed_by_word or set(entries) <= set(english[section]), (
            package.name,
            language,
            section,
            set(entries) - set(english[section]),
        )
        for key, value in entries.items():
            where = (package.name, language, section, key)
            if section in ("numbers", "counts"):
                assert isinstance(value, int), where
            elif isinstance(value, dict):  # keystrokes.names: key -> spoken names
                for names in value.values():
                    assert names and all(isinstance(n, str) and n for n in names), where
            elif isinstance(value, str):
                assert value, where
            else:
                assert value and all(isinstance(v, str) and v for v in value), where


def test_every_shipped_language_has_the_core_table():
    """The core table exists for each language that has a language pack."""
    locale = Path(vocabulary.__file__).with_name("locale")
    for code in ("en", "de", "it", "fr", "es"):
        table = vocabulary.load_table(locale, code)
        assert set(table["numbers"].values()) == set(range(11)), code
        assert table["commands"]["prompt"], code


def test_say_lists_the_active_languages_ways_for_the_help(package):
    """The help shows the German words, up to the limit, or the English ones."""
    vocab = vocabulary.Vocabulary(package, language="de")

    assert vocab.say("open") == "öffne/starte"
    assert vocab.say("open", limit=1) == "öffne"
    assert vocab.say("close") == "close"
    assert vocab.say("calculator", "apps", limit=1) == "rechner"
    assert vocab.say("nothing") == "nothing"
