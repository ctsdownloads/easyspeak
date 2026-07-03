"""Resolve which language packs the Release workflow should build.

Reads the triggering event from the environment and writes the `matrix` GitHub
Actions output: an Actions `{"include": [...]}` object of the language codes,
each with its pack version, to fan out over.

- A `lang-<code>-<version>` release tag builds that one pack; the version
  segment must match `pins.toml`.
- Any other release tag is an application release and builds no language packs,
  so the matrix is empty and the build job is skipped.
- A manual `workflow_dispatch` builds the named codes — or every language in
  `pins.toml` when none are given — and uploads artifacts instead of publishing.
"""

import json
import os
from pathlib import Path

import tomllib


def resolve(event, tag, inputs, pins):
    """Return the Actions matrix object for the given trigger.

    Each entry carries the language `code` and its pack `version`. An
    application release (a tag not starting with `lang-`) yields an empty
    matrix. Raises `SystemExit` if a language tag's version segment does not
    match the pack's `version` in `pins`.
    """
    if event == "release":
        if not tag.startswith("lang-"):
            return {"include": []}
        code, _, want = tag.removeprefix("lang-").rpartition("-")
        have = pins.get(code, {}).get("version")
        if want != have:
            msg = f"::error::tag {tag} says {want}, pins.toml has {code}={have}"
            raise SystemExit(msg)
        codes = [code]
    else:
        codes = inputs.split() or list(pins)
    return {"include": [{"code": c, "version": pins[c]["version"]} for c in codes]}


def main():
    """Resolve from the environment and write the GitHub Actions output."""
    pins = tomllib.loads(Path("pins.toml").read_text(encoding="utf-8"))["lang"]
    matrix = resolve(
        os.environ["EVENT"],
        os.environ.get("TAG", ""),
        os.environ.get("INPUT_CODES", ""),
        pins,
    )
    output = Path(os.environ["GITHUB_OUTPUT"])
    with output.open("a", encoding="utf-8") as out:
        out.write(f"matrix={json.dumps(matrix)}\n")


if __name__ == "__main__":
    main()
