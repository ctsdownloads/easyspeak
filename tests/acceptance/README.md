# Acceptance tests

Behavioral, user-facing scenarios written in **Gherkin** and run by
**pytest-bdd**.

They describe the *contract* of a behaviour in business-readable language
— `Given / When / Then` — rather than poking at internals.

## How they run

Spoken audio can't be verified by listening in an automated run, so these
scenarios drive the real `EasySpeak` object with the **subprocess boundary
stubbed** and assert the observable contract (model loaded once, blank
ignored, flushed on shutdown, recovery).

Like `tests/integration` and `tests/benchmarks`, this folder is **excluded
from default discovery** (see `pyproject.toml`) and is opt-in:

```sh
just acceptance       # uv run --extra=acceptance pytest tests/acceptance
just acceptance -v    # extra pytest args pass through
```

## Layout

```sh
features/*.feature    # Gherkin scenarios (the readable spec)
test_*.py             # scenarios(...) binding + @given/@when/@then steps
conftest.py           # stubs the ML/audio imports so EasySpeak loads
```
