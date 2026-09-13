"""Resolve which data packs the Release workflow should build.

Reads the triggering event from the environment and writes the `matrix` GitHub
Actions output: an Actions `{"include": [...]}` object of the packs, each with
its kind (`lang` or `stt`), code and version, to fan out over.

- A `lang-<code>-<version>` or `stt-<code>-<version>` release tag builds that one
  pack; the version segment must match `pins.toml`.
- Any other release tag is an application release and builds no packs, so the
  matrix is empty and the build job is skipped.
- A manual `workflow_dispatch` builds the named packs (`lang-de`, `stt-parakeet`,
  a bare `de` being a language) — or every pack in `pins.toml` when none are
  given — and uploads artifacts instead of publishing.
"""

import json
import os
from pathlib import Path

import tomllib

KINDS = ("lang", "stt")


def resolve(event, tag, inputs, pins):
    """Return the Actions matrix object for the given trigger.

    Each entry carries the pack's `kind`, `code` and `version`. An application
    release (a tag not starting with a pack kind) yields an empty matrix. Raises
    `SystemExit` if a pack tag's version segment does not match the pack's
    `version` in `pins`.
    """
    if event == "release":
        kind, _, rest = tag.partition("-")
        if kind not in KINDS:
            return {"include": []}
        code, _, want = rest.rpartition("-")
        have = pins.get(kind, {}).get(code, {}).get("version")
        if want != have:
            msg = f"::error::tag {tag} says {want}, pins.toml has {kind}.{code}={have}"
            raise SystemExit(msg)
        packs = [(kind, code)]
    elif inputs.split():
        packs = [
            tuple(name.split("-", 1)) if "-" in name else ("lang", name)
            for name in inputs.split()
        ]
    else:
        packs = [(kind, code) for kind in KINDS for code in pins.get(kind, {})]
    return {
        "include": [
            {"kind": kind, "code": code, "version": pins[kind][code]["version"]}
            for kind, code in packs
        ]
    }


def main():
    """Resolve from the environment and write the GitHub Actions output."""
    pins = tomllib.loads(Path("pins.toml").read_text(encoding="utf-8"))
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
