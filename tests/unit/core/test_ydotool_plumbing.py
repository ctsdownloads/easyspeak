"""The core run seam reads no grid env of its own."""

import easyspeak.core.ydotool as yd
from easyspeak.plugins.mousegrid import _ydotool as grid_module


def test_core_reads_no_grid_env(monkeypatch):
    # The grid's dry-run switch must be SET while the seam runs: the contract
    # under test is that core ignores it, so a regression that re-adds the env
    # read fails this by returning the dry-run "ran" — with the var unset the
    # test proves nothing.
    monkeypatch.setenv("EASYSPEAK_GRID_DRY_RUN", "1")
    # dry_run=None never short-circuits: a guaranteed-refusing argv reaches
    # _spawn and comes back as a failure outcome, not the dry-run "ran"
    assert yd._run_bounded(("nonexistent-ydotool-binary",), dry_run=None) in {
        "errored",
        "unknown",
    }


def test_dry_run_is_a_parameter():
    assert yd._run_bounded(("anything",), dry_run=True) == "ran"


def test_grid_reexports_are_the_seam_itself():
    # Identity, not equality: `_ydotool` re-exports the seam's names, and the
    # grid's tests patch them in one or both module dicts expecting the patch
    # to reach the very object every caller resolves. A "refactor" that turned
    # a re-export into a wrapper function would strand the callers resolving
    # the other dict on the real function — stubbed tests would start firing
    # real clicks. Same-function identity fails loudly the day that happens.
    assert grid_module._run_bounded is yd._run_bounded
