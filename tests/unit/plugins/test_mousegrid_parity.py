"""Differential parity battery: one phrase surface, two backends.

The roast-4 MAJOR was a divergence no shared table could catch — branch
precedence. This battery is the guarantee that no other instance of the
class survives: every row drives BOTH production mode loops (the real
`_extension._run_grid_mode` and `_ydotool._run_mode`, mocked only at their
seams) over the same utterance and asserts the exact decision each backend
must produce — the pointer actions, the spoken replies, and whether the
mode continues. Where the backends legitimately differ (verbs only the
extension can serve), the row declares the designed boundary explicitly
instead of equality, so a silent divergence can never hide behind a
capability gap.

The extension rows include the trailing `Hide` their teardown performs on
every utterance the mode survives; the ydotool loop has no such tail (the
session teardown lives in `_open_session`, which these rows do not run).

Adding a verb, a mishearing or a reply? Add a row. The battery fails on
any change to vocabulary, precedence, speech or mode-end that the two
loops do not make alike.
"""

import importlib
from unittest.mock import Mock

import pytest

ext = importlib.import_module("easyspeak.plugins.mousegrid._extension")
yd = importlib.import_module("easyspeak.plugins.mousegrid._ydotool")

BOUNDARY = "That needs the GNOME extension."


@pytest.fixture(autouse=True)
def _fresh_backends(monkeypatch):
    """Both loops are module-global state machines; every row starts from
    the import-time shape (the same discipline the backend suites pin).
    The extension's show path speaks via the module-global `core` that
    `setup()` stores; the battery never asserts through it, so a plain
    Mock stands in."""
    monkeypatch.setattr(ext, "core", Mock())
    monkeypatch.setattr(ext, "grid_active", False)
    monkeypatch.setattr(ext, "grid_bounds", None)
    monkeypatch.setattr(ext, "screen_size", None)
    monkeypatch.setattr(ext, "last_bounds", None)
    monkeypatch.setattr(ext, "drag_start", None)
    monkeypatch.setattr(yd, "_monitor_origin", (0, 0))
    monkeypatch.setattr(yd, "_bounds", None)
    monkeypatch.setattr(yd, "_last_bounds", None)
    monkeypatch.setattr(yd, "_helper", None)


def _listen(core, utterances):
    """A listen_modal whose pulls are counted, so the test can tell an
    utterance the loop ended on from one it came back from: a second pull
    is what "the mode continues" means."""
    consumed = []

    def gen():
        for utterance in utterances:
            consumed.append(utterance)
            yield utterance

    core.listen_modal = Mock(return_value=gen())
    return consumed


def drive_extension(monkeypatch, utterance):
    """Run the extension loop on one utterance; (dbus methods, speaks)."""
    methods = []

    def dbus(method, *args):
        methods.append(method)
        return True

    monkeypatch.setattr(ext, "dbus_call", dbus)
    monkeypatch.setattr(ext, "grid_active", True)
    monkeypatch.setattr(ext, "grid_bounds", (0, 0, 900, 600))
    monkeypatch.setattr(ext, "screen_size", (900, 600))
    core = Mock()
    consumed = _listen(core, [utterance, "parity-sentinel"])
    ext.listen_for_grid_commands(core)
    speaks = [call.args[0] for call in core.speak.call_args_list]
    return tuple(methods), tuple(speaks), len(consumed) > 1


def drive_ydotool(monkeypatch, utterance):
    """Run the ydotool loop on one utterance; (injection actions, speaks)."""
    actions = []
    monkeypatch.setattr(yd, "_bounds", (0, 0, 900, 600))
    monkeypatch.setattr(yd, "_helper", Mock(poll=Mock(return_value=None), stdin=Mock()))
    monkeypatch.setattr(yd, "_dismiss", lambda: actions.append("dismiss"))
    monkeypatch.setattr(yd, "_redraw", lambda bounds: actions.append("redraw"))
    monkeypatch.setattr(yd, "move_to", lambda x, y: actions.append("move") or "ran")
    monkeypatch.setattr(
        yd,
        "click",
        lambda button="click": actions.append(f"click:{button}") or "ran",
    )
    core = Mock()
    consumed = _listen(core, [utterance, "parity-sentinel"])
    yd._run_mode(core)
    speaks = [call.args[0] for call in core.speak.call_args_list]
    return tuple(actions), tuple(speaks), len(consumed) > 1


# (utterance,
#  extension:  (dbus methods, speaks, mode continues),
#  ydotool:    (actions,      speaks, mode continues))
#
# Rows where the extension acts and ydotool names the boundary are the
# designed capability gap (no wheel, no press-and-hold, no nudge) — the
# assertion is that the gap is exactly the declared one, never silence
# where a verb is named, and never a zoom or a click where the extension
# would have acted.
BATTERY = [
    # Zones: the extension repaints through D-Bus per zone (intermediate
    # frames), the ydotool backend once per utterance (final frame only) —
    # a rendering-transport difference; the final cell is identical.
    ("3 7 5", ("Update", "Update", "Update", "Hide"), (), True, ("redraw",), (), True),
    ("5", ("Update", "Hide"), (), True, ("redraw",), (), True),
    (
        "won tree five",
        ("Update", "Update", "Update", "Hide"),
        (),
        True,
        ("redraw",),
        (),
        True,
    ),
    (
        "click",
        ("Click",),
        ("Clicked",),
        False,
        ("move", "click:click", "dismiss"),
        ("Clicked",),
        False,
    ),
    (
        "double click",
        ("DoubleClick",),
        ("Double clicked",),
        False,
        ("move", "click:click", "click:click", "dismiss"),
        ("Double clicked",),
        False,
    ),
    (
        "right click",
        ("RightClick",),
        ("Right clicked",),
        False,
        ("move", "click:right", "dismiss"),
        ("Right clicked",),
        False,
    ),
    (
        "middle click",
        ("MiddleClick",),
        ("Middle clicked",),
        False,
        ("move", "click:middle", "dismiss"),
        ("Middle clicked",),
        False,
    ),
    (
        "3 click",
        ("Click",),
        ("Clicked",),
        False,
        ("move", "click:click", "dismiss"),
        ("Clicked",),
        False,
    ),
    (
        "click nudge",
        ("Click",),
        ("Clicked",),
        False,
        ("move", "click:click", "dismiss"),
        ("Clicked",),
        False,
    ),
    (
        "close",
        ("Hide",),
        ("Grid closed",),
        False,
        ("dismiss",),
        ("Grid closed",),
        False,
    ),
    (
        "stopwatch",
        ("Hide",),
        ("Grid closed",),
        False,
        ("dismiss",),
        ("Grid closed",),
        False,
    ),
    ("scroll down 3", ("Scroll",), ("Scrolled",), False, (), (BOUNDARY,), True),
    ("scroll up", ("Scroll",), ("Scrolled",), False, (), (BOUNDARY,), True),
    ("scroll click", ("Hide",), (), True, (), (BOUNDARY,), True),
    # The mark rows carry the extension's EndDrag: the mode exit releases
    # the pending drag, so a mark that never became a "drag" still leaves
    # no button down.
    (
        "mark",
        ("StartDrag", "Update", "EndDrag", "Hide"),
        ("Holding",),
        True,
        (),
        (BOUNDARY,),
        True,
    ),
    (
        "mark 3",
        ("StartDrag", "Update", "EndDrag", "Hide"),
        ("Holding",),
        True,
        (),
        (BOUNDARY,),
        True,
    ),
    ("drag", ("Hide",), (), True, (), (BOUNDARY,), True),
    ("nudge", ("Hide",), (), True, (), (BOUNDARY,), True),
    # A fullwidth zero passes isdecimal but names no zone: the extension's
    # update_grid returns False at its ZONE_MAP guard (no Update), and the
    # ydotool loop must skip it the same way — before this row, it reached
    # `subdivide`, raised KeyError, and killed the session on one backend
    # only (the adversarial pass verified the crash by execution).
    (
        "０",  # noqa: RUF001 — the fullwidth zero IS the fixture data
        ("Hide",),
        (),
        True,
        (),
        (),
        True,
    ),
    ("nudge up 5", ("Update", "Hide"), (), True, (), (BOUNDARY,), True),
    ("up 5", ("Update", "Hide"), (), True, (), (BOUNDARY,), True),
    ("up", ("Update", "Hide"), (), True, (), (BOUNDARY,), True),
    ("left 3", ("Update", "Hide"), (), True, (), (BOUNDARY,), True),
    ("right", ("Update", "Hide"), (), True, (), (BOUNDARY,), True),
    ("again", ("Hide",), (), True, (), (), True),
    ("open firefox", ("Hide",), (), True, (), (), True),
]


@pytest.mark.parametrize(
    [
        "utterance",
        "ext_methods",
        "ext_speaks",
        "ext_continues",
        "yd_actions",
        "yd_speaks",
        "yd_continues",
    ],
    BATTERY,
)
def test_one_utterance_two_backends(
    utterance,
    ext_methods,
    ext_speaks,
    ext_continues,
    yd_actions,
    yd_speaks,
    yd_continues,
    monkeypatch,
):
    got_methods, got_speaks, got_continues = drive_extension(monkeypatch, utterance)
    assert (got_methods, got_speaks, got_continues) == (
        ext_methods,
        ext_speaks,
        ext_continues,
    ), f"extension backend answered {utterance!r} differently than declared"

    got_actions, got_speaks, got_continues = drive_ydotool(monkeypatch, utterance)
    assert (got_actions, got_speaks, got_continues) == (
        yd_actions,
        yd_speaks,
        yd_continues,
    ), f"ydotool backend answered {utterance!r} differently than declared"


@pytest.mark.parametrize(
    ["utterance", "expected"],
    [
        ("grid", True),
        ("mouse", True),
        ("grit", True),
        ("grid close", None),
        ("grid hide", None),
        ("against the wall", None),
        ("again", None),
        ("open firefox", None),
    ],
)
def test_the_claim_boundary_claims_alike(utterance, expected, monkeypatch):
    """One utterance must be claimed by whichever backend answers — or by
    neither. Never by one and not the other."""
    core = Mock()
    core.listen_modal = Mock(return_value=iter([]))

    monkeypatch.setattr(ext, "get_screen_size", lambda: (900, 600))
    monkeypatch.setattr(ext, "dbus_call", lambda method, *args: True)
    assert ext.handle(utterance, core) is expected

    monkeypatch.setattr(yd, "_active", True)
    monkeypatch.setattr(yd, "_open_session", Mock())
    monkeypatch.setattr(yd, "_last_bounds", None)
    assert yd.handle(utterance, core) is expected


@pytest.mark.parametrize(
    ["screen", "remembered", "expected_bounds"],
    [
        # The remembered cell still fits: both backends redraw it verbatim.
        ((900, 600), (100, 200, 300, 400), (100, 200, 300, 400)),
        # The geometry changed between sessions: a clipped rectangle must not
        # survive on either backend — both reopen the whole output. This is
        # the PR's headline claim (one utterance, one pixel) holding on the
        # reopen path, not only on a fresh open.
        ((900, 600), (500, 400, 700, 500), (0, 0, 900, 600)),
    ],
)
def test_again_reopens_at_one_rectangle_per_utterance(
    screen, remembered, expected_bounds, monkeypatch
):
    """The "again" path must land on the same rectangle on whichever backend
    answers: a remembered cell that no longer fits the fresh geometry reopens
    as the full output on both, and a cell that still fits reopens verbatim
    on both. `_ydotool._open_session` has carried the fit check from the
    start; this row pins `_extension.handle` to the same rule."""
    monkeypatch.setattr(ext, "last_bounds", remembered)
    monkeypatch.setattr(ext, "get_screen_size", lambda: screen)
    calls = []

    def dbus(method, *args):
        calls.append((method, args))
        return True

    monkeypatch.setattr(ext, "dbus_call", dbus)
    core = Mock()
    core.listen_modal = Mock(return_value=iter([]))
    assert ext.handle("again", core) is True
    # The trailing Hide is the extension's mode-exit teardown, the same tail
    # every battery row carries.
    assert calls == [
        ("Show", screen),
        ("Update", expected_bounds),
        ("Hide", ()),
    ]
    assert ext.last_bounds == expected_bounds
    assert [call.args[0] for call in core.speak.call_args_list] == ["Grid"]

    monkeypatch.setattr(yd, "_active", True)
    monkeypatch.setattr(yd, "_last_bounds", remembered)
    # `_open_session` reads `_helper.stdout` to await the presented frame;
    # the helper is a mock, so is the stream it reads from.
    monkeypatch.setattr(yd, "_helper", Mock(stdout=Mock()))
    shows = []
    monkeypatch.setattr(yd, "_start_helper", lambda: (0, 0, *screen))
    monkeypatch.setattr(yd, "_redraw", lambda bounds: shows.append(tuple(bounds)))
    monkeypatch.setattr(yd, "read_until", lambda *_a, **_k: None)
    monkeypatch.setattr(yd, "_send", lambda payload: True)
    monkeypatch.setattr(yd, "stop_helper", lambda reason: None)
    core = Mock()
    core.listen_modal = Mock(return_value=iter([]))
    assert yd.handle("again", core) is True
    assert shows == [expected_bounds]
    assert [call.args[0] for call in core.speak.call_args_list] == ["Grid"]
