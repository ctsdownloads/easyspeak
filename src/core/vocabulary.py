"""What the app listens for, per language: the `vocabulary.toml` tables.

The core and every plugin may keep a `locale/<language>/vocabulary.toml` beside
their reply catalog. A table holds phrases grouped in sections, `[commands]`
above all: each key names something the package reacts to and lists the ways of
saying it, mishearings included. That is recognition data tuned by testing, so
it lives in a table a package reads rather than in its code, and English is a
table like the others. See the plugin guide's Translations section.

Commands are matched against the active language's table and the English one,
so the English phrases keep working whatever the language.
"""

import re
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def load_table(locale_dir, language):
    """Return the `vocabulary.toml` for `language` under `locale_dir`, or None."""
    table = Path(locale_dir) / language / "vocabulary.toml"
    if not table.is_file():
        return None
    with table.open("rb") as f:
        return tomllib.load(f)


class Vocabulary:
    """The phrases a package listens for, in the active language and in English.

    `Vocabulary(__file__)` at the top of a plugin binds its own tables; `language`
    defaults to the configured one. Lookups take a section, `commands` unless
    said otherwise, and a key in it.
    """

    def __init__(self, file, language=None):
        """Load the package's table for `language` and the English one."""
        if language is None:
            from . import config

            language = config.LANGUAGE
        locale_dir = Path(file).with_name("locale")
        tables = [load_table(locale_dir, language)] if language != "en" else []
        tables.append(load_table(locale_dir, "en"))
        self.tables = [table for table in tables if table]

    def keys(self, section="commands"):
        """Return the keys of `section`, in table order, the active language's first."""
        keys = []
        for table in self.tables:
            keys.extend(k for k in table.get(section, {}) if k not in keys)
        return keys

    def phrases(self, key, section="commands"):
        """Return every way of saying `key`, in the active language and in English."""
        return [
            phrase
            for table in self.tables
            for phrase in table.get(section, {}).get(key, [])
        ]

    def says(self, text, key, section="commands"):
        """Whether `text` contains a phrase for `key`, as whole words."""
        return any(
            re.search(rf"\b{re.escape(phrase)}\b", text)
            for phrase in self.phrases(key, section)
        )

    def ends(self, text, key, section="commands"):
        """Whether `text` is a phrase for `key`, or ends with one."""
        return any(
            text == phrase or text.endswith(" " + phrase)
            for phrase in self.phrases(key, section)
        )

    def say(self, key, section="commands", limit=2):
        """Return up to `limit` ways of saying `key`, joined by "/", for the help.

        The active language's phrases when it has any, else the English ones, so
        the help lists what the user can actually say.
        """
        for table in self.tables:
            phrases = table.get(section, {}).get(key, [])
            if phrases:
                return "/".join(phrases[:limit])
        return key

    def which(self, text, section):
        """Return the first key of `section` that `text` says, or None."""
        return next(
            (key for key in self.keys(section) if self.says(text, key, section)), None
        )
