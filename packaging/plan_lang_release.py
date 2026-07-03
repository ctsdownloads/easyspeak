"""Resolve which language packs the release-lang workflow should build.

Reads the triggering event from the environment and writes two GitHub Actions
outputs: `matrix` (an Actions `{"include": [...]}` object of language codes to
fan out over) and `release` (the tag to publish to, empty for a manual run).

- A `lang-<code>-<version>` tag push builds that one pack and publishes it to a
  release named for the tag; the version segment must match pins.toml.
- A manual `workflow_dispatch` builds the named codes — or every language in
  pins.toml when none are given — and uploads artifacts instead of publishing a
  release.
"""

import json
import os
from pathlib import Path

import tomllib


def resolve(event, ref, inputs, pins):
    """Return `(matrix, release)` for the given trigger.

    `matrix` is the Actions matrix object; `release` is the tag to publish to,
    or `""` for a manual run. Raises `SystemExit` if a tag's version segment
    does not match the pack's `version` in `pins`.
    """
    if event == "push":
        code, _, want = ref.removeprefix("lang-").rpartition("-")
        have = pins.get(code, {}).get("version")
        if want != have:
            msg = f"::error::tag {ref} says {want}, pins.toml has {code}={have}"
            raise SystemExit(msg)
        codes, release = [code], ref
    else:
        codes, release = inputs.split() or list(pins), ""
    return {"include": [{"code": code} for code in codes]}, release


def main():
    """Resolve from the environment and write the GitHub Actions outputs."""
    pins = tomllib.loads(Path("pins.toml").read_text(encoding="utf-8"))["lang"]
    matrix, release = resolve(
        os.environ["EVENT"],
        os.environ["REF_NAME"],
        os.environ.get("INPUT_CODES", ""),
        pins,
    )
    output = Path(os.environ["GITHUB_OUTPUT"])
    with output.open("a", encoding="utf-8") as out:
        out.write(f"matrix={json.dumps(matrix)}\n")
        out.write(f"release={release}\n")


if __name__ == "__main__":
    main()
