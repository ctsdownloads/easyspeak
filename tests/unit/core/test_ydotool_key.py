"""Key-verb synthesis: the argv oracle is the captured client usage, not the synthesizer.

The two ydotool dialects disagree about the `key` grammar itself, so every
expected argv below is a literal taken from the Task 0 fixtures, with the
fixture line it came from cited in place:

- ``tests/unit/core/fixtures/ydotool_key_usage_legacy.txt`` (0.1.8, live VM
  capture): `key [--delay] [--key-delay] [--repeat <times>] [--repeat-delay]
  <key sequence> ...` where a key sequence is ONE combo of key/modifier NAMES
  joined with '+'.
- ``tests/unit/core/fixtures/ydotool_key_usage_modern.txt`` (1.0.x,
  source-derived): `key [-d,--key-delay] [<KEYCODE:PRESSED> ...]` where each
  token is an independent down/up event and combos are consecutive tokens —
  with NO repeat flag at all.

The legacy fixture's crash-probe transcript (`ydotool key 29:1 29:0`, its
lines 73-75) documents a client abort, not a grammar — the fixture disavows
it and nothing here derives from those lines.
"""

import pytest

from easyspeak.core import ydotool as yd


def _pin_dialect(monkeypatch, dialect):
    """Pin the seam's resolved dialect instead of letting it probe the host.

    Same discipline as the grid suite: the dialect is cached module state the
    autouse reset clears, and an unpinned test would consult (and cache) the
    real host binary's answer.
    """
    monkeypatch.setattr(yd, "_dialect", dialect)


# --- modern (1.0.x): raw KEYCODE:PRESSED tokens, no repeat flag -------------


def test_modern_chord_downs_in_order_then_ups_in_reverse(monkeypatch):
    # Modern fixture line 28: ":1 = key down, :0 = key up; a combo is spelled
    # as consecutive tokens" — that pins the token grammar. (Its line 29 "LOL"
    # example is a typing sequence — shift down, letters pressed and released
    # one by one — not a chord cycle, so it pins nothing about ordering.) The
    # down-in-order/up-in-reverse shape is mediakeys.tap_chord's documented
    # contract, which key_argv exists to mirror on this dialect.
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_MODERN)
    assert yd.key_argv((29, 47)) == (
        "ydotool",
        "key",
        "29:1",
        "47:1",
        "47:0",
        "29:0",
    )


def test_modern_repeats_are_consecutive_pairs_in_one_argv(monkeypatch):
    # Modern fixture lines 34-35: "NO --delay/--repeat/--repeat-delay on key
    # in this dialect". Batching repeats therefore cannot use a flag — it is
    # N consecutive down/up cycles (line 28) in ONE argv, never N invocations.
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_MODERN)
    argv = yd.key_argv((14,), repeats=10)
    assert argv[:2] == ("ydotool", "key")
    assert argv[2:] == ("14:1", "14:0") * 10


def test_modern_needs_no_name_table(monkeypatch):
    # Modern fixture lines 30-31: keycodes are "RAW linux keycodes ... NOT
    # names". A code that has no legacy combo name still synthesizes here —
    # the name table is legacy-only.
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_MODERN)
    assert yd.key_argv((104,)) == ("ydotool", "key", "104:1", "104:0")


# --- legacy (0.1.8): one name combo per invocation, --repeat for batches ----


def test_legacy_chord_is_one_plus_joined_name_combo(monkeypatch):
    # Legacy fixture lines 18-19 and 93: the usage line ends in ONE
    # `<key sequence>`, and lines 21-22 define it as NAMES joined with '+'
    # ("ctrl+Backspace" appears verbatim at lines 22 and 105). ctrl is 29 and
    # v is 47 in the repo's chord tables (dictation.KEYCODES); the single
    # lowercase letter spelling follows from the client's own "alt+r" example
    # (lines 22 and 105).
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_LEGACY)
    assert yd.key_argv((29, 47)) == ("ydotool", "key", "ctrl+v")
    # The dialect branch and the direct legacy builder agree.
    assert yd.key_legacy_argv((29, 47)) == yd.key_argv((29, 47))


def test_legacy_repeats_are_one_invocation_with_the_repeat_flag(monkeypatch):
    # Legacy fixture lines 18-19 and 93: `--repeat <times>` sits on the key
    # verb, and line 102 says it is "Times to repeat the key sequence" — so
    # ten backspaces are ONE invocation carrying the flag, never ten combos
    # and never ten processes. The other flags stay off because their
    # documented defaults are already what we want: `--repeat-delay` defaults
    # to 0ms (line 103) and `--key-delay` to the client's own 12ms pacing
    # (line 101). "backspace" is 14 per mediakeys.KEYS and the fixture's
    # "ctrl+Backspace" example (lines 22, 105) grounds the name spelling.
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_LEGACY)
    argv = yd.key_argv((14,), repeats=10)
    assert argv == ("ydotool", "key", "--repeat", "10", "backspace")
    # One invocation, so the sequence token appears exactly once.
    assert argv.count("backspace") == 1


def test_unknown_legacy_code_raises_naming_the_code(monkeypatch):
    # Legacy fixture lines 25-27: an unknown NAME aborts the client with
    # "no matching keycode" — and a guessed name would be worse than an abort,
    # because the client's single-letter fallback presses the wrong key
    # silently. Codes with no grounded legacy name therefore raise here,
    # before any process is spawned. 104 has none: its repo name is the
    # two-word spoken form "page up" (mediakeys.KEYS), and a space is not a
    # combo name.
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_LEGACY)
    with pytest.raises(ValueError, match="104"):
        yd.key_argv((104,))
    with pytest.raises(ValueError, match="9999"):
        yd.key_legacy_argv((9999,))


# --- the loud programming-error guards --------------------------------------


def test_a_zero_repeat_is_a_loud_programming_error_on_both_dialects(monkeypatch):
    # `parse_key_request` can hand back repeats=0 ("backspace 0" — spoken
    # digits are accepted). GNOME's `range(0)` loop there is a clean no-op;
    # here a zero would make 1.0.x emit a keyless argv the client refuses and
    # 0.1.8 silently press the key ONCE — a deletion the user never asked
    # for. The seam raises before any process runs, on either branch.
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_MODERN)
    with pytest.raises(ValueError, match="repeats"):
        yd.key_argv((14,), repeats=0)
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_LEGACY)
    with pytest.raises(ValueError, match="repeats"):
        yd.key_argv((14,), repeats=0)


def test_an_empty_chord_is_a_loud_programming_error_on_both_dialects(monkeypatch):
    # A keyless batch would hand 1.0.x a bare `key` argv (its help text and a
    # non-injection exit) and 0.1.8 its "Which keys do you want to press?"
    # refusal — a caller bug, so it is named as one before any process runs.
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_MODERN)
    with pytest.raises(ValueError, match="chord"):
        yd.key_argv(())
    _pin_dialect(monkeypatch, yd.YDTOOL_DIALECT_LEGACY)
    with pytest.raises(ValueError, match="chord"):
        yd.key_argv(())


# --- the batched timeout ----------------------------------------------------


def test_key_timeout_never_drops_below_the_floor_and_grows_with_repeats():
    assert yd.key_timeout(1) >= yd.INJECT_TIMEOUT
    assert yd.key_timeout(0) == yd.INJECT_TIMEOUT
    # "backspace two hundred" must outlast "backspace ten": the bound scales
    # with the batch, never a fixed one-size timeout.
    assert yd.key_timeout(200) > yd.key_timeout(10)
    # The exact formula, so a `*`-for-`+` slip cannot stay green: floor plus
    # one budget per repeat. `per_repeat` resolves the constant in the body
    # (a def-time default would freeze Task 7's recalibration out).
    assert yd.key_timeout(3) == yd.INJECT_TIMEOUT + 3 * yd.KEY_PER_REPEAT_BUDGET
