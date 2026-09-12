"""Translations of the spoken replies, read straight from gettext `.po` files.

The core and every plugin are each a gettext domain with a `locale/` directory
next to their code, laid out the conventional way:
`locale/<language>/LC_MESSAGES/<domain>.po`, the domain being the directory's
name. The catalog for [`REPLY_LANGUAGE`][core.config] is built in memory from
the `.po` at startup, so no compiled `.mo` files exist, and a missing catalog or
a missing string falls back to the English source text.

A plugin opts in with one line, `_ = translator(__file__)`, and wraps what it
speaks: `core.speak(_("Opening {app}.").format(app=app))`. `just translations`
keeps the `.po` files in step with the code.
"""

import gettext
import io
from pathlib import Path

import polib

from . import config


def translator(file, language=None):
    """Return the `gettext` function for the package that `file` belongs to.

    The package directory's name is the domain and its `locale/` directory
    holds the catalogs; `language` defaults to `config.REPLY_LANGUAGE`.
    """
    package = Path(file).parent
    language = language or config.REPLY_LANGUAGE
    po = package / "locale" / language / "LC_MESSAGES" / f"{package.name}.po"
    if not po.is_file():
        return gettext.NullTranslations().gettext
    catalog = gettext.GNUTranslations(io.BytesIO(polib.pofile(str(po)).to_binary()))
    return catalog.gettext


_ = translator(__file__)
"""The core's own translator, for the replies spoken by `core.main` and `core.tray`."""
