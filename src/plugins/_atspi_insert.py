"""Standalone AT-SPI caret-insertion helper.

The dictation plugin runs this as a script (see ``dictation.atspi_python``) in
an interpreter that has PyGObject and the AT-SPI typelib — which the app's own
venv usually lacks. It is a real module rather than an embedded ``python3 -c``
string so Ruff lints it and the unit tests can import and exercise it; an
unlinted string is exactly how the earlier ``contextlib`` NameError slipped in.

It communicates with the parent purely through stdout tokens:
``OK`` (text inserted), ``NO_FOCUS`` (no editable field), ``NO_BACKEND``
(PyGObject/AT-SPI not importable). Kept out of plugin discovery by the leading
underscore in the filename.
"""

import contextlib
import sys

OK = "OK"
NO_FOCUS = "NO_FOCUS"
NO_BACKEND = "NO_BACKEND"

MAX_DEPTH = 25
BACKSPACE = chr(8)


def load_atspi():
    """Return PyGObject's ``Atspi`` namespace, or ``None`` if unavailable.

    The detail of why it failed is written to stderr so the parent can log it.
    """
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except (ImportError, ValueError) as exc:
        sys.stderr.write(str(exc))
        return None
    return Atspi


def find_focused_editable(atspi, obj, depth=0):
    """Depth-first search for the focused, editable accessible under ``obj``."""
    if depth > MAX_DEPTH:
        return None
    # AT-SPI nodes can raise while being queried (apps closing, slow a11y
    # responses); skip a node that misbehaves rather than aborting the walk.
    with contextlib.suppress(Exception):
        state = obj.get_state_set()
        if state.contains(atspi.StateType.FOCUSED) and state.contains(
            atspi.StateType.EDITABLE
        ):
            return obj
        for i in range(obj.get_child_count()):
            found = find_focused_editable(atspi, obj.get_child_at_index(i), depth + 1)
            if found:
                return found
    return None


def _insertion_point(target):
    """Where to start inserting: the caret, else end-of-text, else None.

    Falling back to the end keeps multi-character insertion in order; the old
    code advanced from a bogus ``-1``, scattering later characters to the start.
    None means neither the caret nor the character count was readable.
    """
    with contextlib.suppress(Exception):
        pos = target.get_caret_offset()
        if pos >= 0:
            return pos
    with contextlib.suppress(Exception):
        return target.get_character_count()
    return None


def insert_into(target, text):
    """Type ``text`` into ``target`` at the caret, honouring backspaces.

    Returns True once the text is inserted, or False if no usable insertion
    point could be found — so the caller reports "no focus" rather than
    scattering characters across the field.
    """
    pos = _insertion_point(target)
    if pos is None:
        return False

    for char in text:
        if char == BACKSPACE:
            if pos > 0:
                target.delete_text(pos - 1, pos)
                pos -= 1
        else:
            target.insert_text(pos, char, len(char.encode("utf-8")))
            pos += 1
    return True


def run(atspi, text):
    """Insert ``text`` into the focused editable; return an OK/NO_FOCUS token."""
    desktop = atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        target = find_focused_editable(atspi, desktop.get_child_at_index(i))
        if target:
            return OK if insert_into(target, text) else NO_FOCUS
    return NO_FOCUS


def main(argv):
    """Entry point: load AT-SPI, insert argv[1], print a status token."""
    atspi = load_atspi()
    if atspi is None:
        sys.stdout.write(NO_BACKEND + "\n")
        return 0
    text = argv[1] if len(argv) > 1 else ""
    sys.stdout.write(run(atspi, text) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
