"""Tests for the standalone AT-SPI caret-insertion helper."""

import sys
import types

from easyspeak.plugins import _atspi_insert as helper


class FakeState:
    """A minimal AT-SPI state set."""

    def __init__(self, states):
        self._states = set(states)

    def contains(self, state):
        return state in self._states


class FakeAccessible:
    """A minimal AT-SPI accessible node for tree-walk tests."""

    def __init__(self, states=(), children=(), caret=0, *, raises=False):
        self._state = FakeState(states)
        self._children = list(children)
        self.caret = caret
        self.raises = raises
        self.inserted = []
        self.deleted = []

    def get_state_set(self):
        if self.raises:
            raise RuntimeError("boom")
        return self._state

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, i):
        return self._children[i]

    def get_caret_offset(self):
        if self.caret is None:
            raise RuntimeError("no caret")
        return self.caret

    def insert_text(self, pos, char, length):
        self.inserted.append((pos, char, length))

    def delete_text(self, start, end):
        self.deleted.append((start, end))


class FakeAtspi:
    """Stand-in for the gi ``Atspi`` namespace."""

    class StateType:
        FOCUSED = "FOCUSED"
        EDITABLE = "EDITABLE"

    def __init__(self, desktop):
        self._desktop = desktop

    def get_desktop(self, _index):
        return self._desktop


# --- load_atspi ---


def test_load_atspi_missing(monkeypatch, capsys):
    """Without PyGObject importable, load_atspi returns None and explains why.

    ``gi`` is forced absent so the test is hermetic — it must not depend on
    whether PyGObject happens to be installed in the test interpreter.
    """
    monkeypatch.setitem(sys.modules, "gi", None)

    result = helper.load_atspi()

    assert result is None
    assert capsys.readouterr().err != ""


def test_load_atspi_success(monkeypatch):
    """With gi importable, load_atspi returns the Atspi namespace."""
    sentinel = object()
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *args: None
    fake_repo = types.ModuleType("gi.repository")
    fake_repo.Atspi = sentinel
    monkeypatch.setitem(sys.modules, "gi", fake_gi)
    monkeypatch.setitem(sys.modules, "gi.repository", fake_repo)

    assert helper.load_atspi() is sentinel


# --- find_focused_editable ---


def test_find_focused_editable_direct():
    """A node that is itself focused and editable is returned."""
    node = FakeAccessible(states=["FOCUSED", "EDITABLE"])

    assert helper.find_focused_editable(FakeAtspi, node) is node


def test_find_focused_editable_nested():
    """The search recurses into children."""
    target = FakeAccessible(states=["FOCUSED", "EDITABLE"])
    root = FakeAccessible(children=[FakeAccessible(), target])

    assert helper.find_focused_editable(FakeAtspi, root) is target


def test_find_focused_editable_none():
    """No focused-editable anywhere yields None."""
    root = FakeAccessible(children=[FakeAccessible(states=["FOCUSED"])])

    assert helper.find_focused_editable(FakeAtspi, root) is None


def test_find_focused_editable_depth_limit():
    """Recursion stops past MAX_DEPTH."""
    node = FakeAccessible(states=["FOCUSED", "EDITABLE"])

    assert (
        helper.find_focused_editable(FakeAtspi, node, depth=helper.MAX_DEPTH + 1)
        is None
    )


def test_find_focused_editable_swallows_errors():
    """An accessible that raises is treated as not-a-match, not a crash."""
    node = FakeAccessible(raises=True)

    assert helper.find_focused_editable(FakeAtspi, node) is None


# --- insert_into ---


def test_insert_into_types_characters():
    """Plain characters are inserted at the advancing caret."""
    node = FakeAccessible(caret=0)

    helper.insert_into(node, "hi")

    assert node.inserted == [(0, "h", 1), (1, "i", 1)]


def test_insert_into_backspace_deletes():
    """A backspace deletes the character before the caret."""
    node = FakeAccessible(caret=2)

    helper.insert_into(node, helper.BACKSPACE)

    assert node.deleted == [(1, 2)]


def test_insert_into_backspace_at_start_is_noop():
    """A backspace with the caret at position 0 deletes nothing."""
    node = FakeAccessible(caret=0)

    helper.insert_into(node, helper.BACKSPACE)

    assert node.deleted == []


def test_insert_into_unknown_caret_starts_at_minus_one():
    """When the caret offset can't be read, insertion still proceeds."""
    node = FakeAccessible(caret=None)

    helper.insert_into(node, "x")

    assert node.inserted == [(-1, "x", 1)]


# --- run / main ---


def test_run_inserts_into_focused_field():
    """run finds the focused editable across apps and reports OK."""
    target = FakeAccessible(states=["FOCUSED", "EDITABLE"], caret=0)
    desktop = FakeAccessible(children=[FakeAccessible(), target])

    assert helper.run(FakeAtspi(desktop), "hi") == helper.OK
    assert target.inserted == [(0, "h", 1), (1, "i", 1)]


def test_run_no_focus():
    """run reports NO_FOCUS when nothing editable is focused."""
    desktop = FakeAccessible(children=[FakeAccessible()])

    assert helper.run(FakeAtspi(desktop), "hi") == helper.NO_FOCUS


def test_main_no_backend(monkeypatch, capsys):
    """main prints NO_BACKEND when AT-SPI can't be loaded."""
    monkeypatch.setitem(sys.modules, "gi", None)

    rc = helper.main(["_atspi_insert.py", "hi"])

    assert rc == 0
    assert capsys.readouterr().out.strip() == helper.NO_BACKEND


def test_main_inserts(monkeypatch, capsys):
    """main loads AT-SPI and prints the run() status token."""
    target = FakeAccessible(states=["FOCUSED", "EDITABLE"], caret=0)
    desktop = FakeAccessible(children=[target])
    monkeypatch.setattr(helper, "load_atspi", lambda: FakeAtspi(desktop))

    rc = helper.main(["_atspi_insert.py", "hi"])

    assert rc == 0
    assert capsys.readouterr().out.strip() == helper.OK


def test_main_defaults_to_empty_text(monkeypatch, capsys):
    """With no text argument main inserts an empty string and reports OK."""
    target = FakeAccessible(states=["FOCUSED", "EDITABLE"], caret=0)
    desktop = FakeAccessible(children=[target])
    monkeypatch.setattr(helper, "load_atspi", lambda: FakeAtspi(desktop))

    rc = helper.main(["_atspi_insert.py"])

    assert rc == 0
    assert capsys.readouterr().out.strip() == helper.OK
    assert target.inserted == []
