"""The core run seam reads no grid env of its own."""

import easyspeak.core.ydotool as yd


def test_core_reads_no_grid_env():
    # dry_run=None never short-circuits: a guaranteed-refusing argv reaches
    # _spawn and comes back as a failure outcome, not the dry-run "ran"
    assert yd._run_bounded(("nonexistent-ydotool-binary",), dry_run=None) in {
        "errored",
        "unknown",
    }


def test_dry_run_is_a_parameter():
    assert yd._run_bounded(("anything",), dry_run=True) == "ran"
