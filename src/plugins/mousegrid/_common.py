"""Data and geometry shared by the mousegrid backends.

One grid feature serves several desktops, and the phrase surface must not
depend on which backend answers: an utterance that opens and zooms the grid on
GNOME has to open and zoom it identically under ydotool. The trigger words,
the number table and the zone math therefore live here, and both backends
import them.

The ydotool backend formerly carried its own copies of these tables, kept
equal only by test assertion — the price of a cross-plugin boundary, where
one plugin may not reach into another's namespace. Inside one package a
shared module does the same job without the ceremony: a divergence is now an
ImportError away from being impossible instead of a test failure away from
being shipped.
"""

import re

from easyspeak.core.i18n import translator

_ = translator(__file__)

# Whisper mishears "grid" as any of these often enough that the extension
# backend tunes a whole set, and a backend that hears fewer words than the
# other is a regression in the user's eyes, not a simplification.
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

# Number parsing - word to digit (carries Whisper's usual mishearings).
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

# One compiled scan for the whole word table. Longest-first matters: Python's
# `re` tries alternatives in order at each position, so "three" must precede
# "tree"-shaped shorter rivals ("to" before "too"/"two" would turn "two" into
# "2wo"). Sorting by length is the order that matches the per-word loop this
# replaced, where every full word got its own whole-string pass.
_NUM_RE = re.compile(
    r"\b("
    + "|".join(sorted(map(re.escape, WORD_TO_NUM), key=len, reverse=True))
    + r")\b"
)

ZONE_MAP = {
    1: (0, 0),
    2: (1, 0),
    3: (2, 0),
    4: (0, 1),
    5: (1, 1),
    6: (2, 1),
    7: (0, 2),
    8: (1, 2),
    9: (2, 2),
}

# Words that end a grid session inside an open mode.
DISMISS_WORDS = {"close", "cancel", "stop", "hide", "escape", "exit", "done", "quit"}
# Words that reopen the grid at the cell of the last click.
AGAIN_WORDS = {"again", "repeat", "reopen"}
# The show/dismiss guard at the claim boundary, no wider than the original
# plugin's pair: a phrase that names the grid and asks to close it must not
# OPEN the grid.
SHOW_BLOCK_WORDS = {"close", "hide"}

# Click grammar: which words name which click flavour. The right-click
# mishears are the extension backend's tuned vocabulary and the plain-click
# ones are the ydotool backend's; under one feature they are one set.
CLICK_WORDS = ("click", "lick", "clique")
RIGHT_WORDS = ("right", "write", "rite", "wright")

# Verbs only the extension backend can honour (ydotool has no wheel verb and
# no press-and-hold): the ydotool mode names them instead of swallowing
# them. These are checked BEFORE the click words because that is where the
# extension loop honours them — a compound utterance ("scroll click",
# "scroll down 3") must classify as the verb on both backends instead of
# clicking or zooming on one and scrolling on the other. (Nudge and bare
# directions are the extension's post-click grammar; the ydotool loop reads
# `parse_direction` below its click branch for the same reason.) Precedence
# is part of the phrase surface, which is why the words sit here with the
# rest of the grammar and not inline at the branch that checks them.
EXTENSION_ONLY_WORDS_BEFORE_CLICKS = ("mark", "drag", "scroll")

# Nudge directions, with Whisper's usual mishearings. Both backends read
# this table: the extension backend nudges with it, and the ydotool backend
# reads the same words at its boundary branch — the extension's nudge
# grammar makes the verb word optional ("up 5" is advertised syntax), so a
# direction word must classify the same way on both sides or the count
# suffix zooms the grid on one desktop and nudges on the other.
DIRECTIONS = {
    "up": ["up", "north", "top", "upper", "above"],
    "down": ["down", "south", "bottom", "lower", "below"],
    "left": ["left", "west", "lift", "let", "lef", "laughed", "loft"],
    "right": ["right", "east", "write", "rite", "wright"],
}

# The spoken confirmation per click flavour, keyed by `click_kind`'s
# answer. Translated here at import (the same extraction the COMMANDS list
# relies on): a plain string dict would vanish from the gettext catalogs,
# and `just translations` strips entries the extractor can no longer see.
# Both backends announce a click with the same word: the overlay vanishing
# is the only other cue, and it says nothing about what was done.
CLICK_REPLIES = {
    "double": _("Double clicked"),
    "middle": _("Middle clicked"),
    "right": _("Right clicked"),
    "click": _("Clicked"),
}


def dismiss_match(text):
    """True when an utterance names a dismissal, inside an open grid session.

    Both backends must close on the same utterance — "stopwatch" cannot end
    the grid on one desktop and strand it on another — so the match lives
    here. The semantics are substring-based, which is the extension backend's
    shipped behaviour: one grammar had to move to the other, and moving the
    newer backend's toward the shipped one costs no existing user anything.
    """
    return any(word in text for word in DISMISS_WORDS)


def click_kind(text):
    """Return the click flavour an utterance names, or None.

    Precedence follows the extension backend's original loop (double, middle,
    right, click), and the words match as substrings so "doubleclick" and
    "clicks" resolve too.

    The direction word "right" needs the click word itself attached: bare
    "right" is a nudge on the backend that has one, never a right-click.
    "double" and "middle" name no direction and click on their own. When each
    backend owned its grammar, that bare "right" right-clicked under ydotool
    and nudged under the extension — one utterance, two actions — which is
    exactly the divergence this shared resolver exists to make impossible.
    """
    has_click = any(word in text for word in CLICK_WORDS)
    if "double" in text:
        return "double"
    if "middle" in text:
        return "middle"
    if has_click and any(word in text for word in RIGHT_WORDS):
        return "right"
    if has_click:
        return "click"
    return None


def parse_direction(text):
    """Return the direction (up/down/left/right) named in text, or None.

    Shared since the direction words became the ydotool boundary's grammar
    too: the extension nudges on them and the ydotool backend names its
    boundary on them, and both must answer a direction word alike (see
    [`DIRECTIONS`][_common.DIRECTIONS] for why the verb-optional nudge
    grammar makes this load-bearing).
    """
    for direction, words in DIRECTIONS.items():
        for word in words:
            if word in text:
                return direction
    return None


def subdivide(bounds, zone):
    """Return the ninth of `bounds` named by `zone` (1-9, row-major).

    Integer thirds, including the original backend's truncation: `w // 3` of a
    1000-wide cell is 333, not 333.33, and both backends must agree on that —
    one utterance has to land on the same pixel whichever backend answers. The
    off-monitor safety clamp the first implementation carried is absent because
    it cannot fire: x + w stays inside the monitor by construction.
    """
    x, y, w, h = bounds
    zone_w, zone_h = w // 3, h // 3
    col, row = ZONE_MAP[zone]
    return (x + col * zone_w, y + row * zone_h, zone_w, zone_h)


def center(bounds):
    """Return the (x, y) centre of `bounds`."""
    x, y, w, h = bounds
    return (x + w // 2, y + h // 2)


def parse_number_sequence(text):
    """Extract every zone number from an utterance, in order.

    `"3 7 5"` and `"three seven five"` both give `[3, 7, 5]`; the word table
    carries Whisper's usual mishearings, so the same utterance chains the same
    zooms on whichever backend answers.

    The table compiles to one alternation scanned once per utterance, instead
    of one pass per word over the whole string. Alternatives are ordered
    longest first, which is what keeps the result identical to the sequential
    loop it replaced: at a shared start position the longest word wins, as the
    per-word passes did implicitly (a shorter word never survived where a
    longer one also matched, because the longer pass had already consumed the
    token).
    """
    lowered = _NUM_RE.sub(lambda m: str(WORD_TO_NUM[m[0]]), text.lower())
    # `isdecimal`, not `isdigit`: `isdigit()` also answers True for
    # superscripts and other non-decimal digit characters, and `int("²")`
    # raises - one transcribed "zone ²" would crash the mode loop. Decimal
    # characters are exactly the ones `int()` accepts per character.
    return [int(char) for char in lowered if char.isdecimal() and char != "0"]
