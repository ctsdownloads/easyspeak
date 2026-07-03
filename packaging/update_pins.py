"""Bump the hand-maintained pins in pins.toml to their current upstream versions.

One policy per pin:

- `python.bundle` — newest stable CPython minor that satisfies the project's
  `requires-python` range.
- `toolchain.ubuntu_image` — advances only when the pinned LTS leaves standard
  support: the container's glibc is the packages' compatibility floor, so
  "newest LTS" would silently drop older target distros.
- `toolchain.nfpm` — latest GitHub release.
- `lang.*.whisper.revision` — the model repo's current snapshot commit.
- `lang.*.piper.revision` — the voice repo's newest tag.
- `lang.*.version` — the language pack's own release version. Not fetched from
  upstream: its patch component is bumped whenever that pack's downloaded
  content (its `.files` checksums) changes, so the version always tracks the
  delivered models. Hand-edit it for a larger, semantic bump (e.g. a new voice).

The `lang.*.<model>.files` checksum tables are regenerated from the pinned
revision on every run (large LFS weights read their sha256 from the Hugging
Face tree listing, so this stays cheap), so an in-place `voice`/`path` edit is
reflected with no extra step.

Values are rewritten in place, so comments in pins.toml survive. Nothing is
committed; review with `git diff pins.toml`.
"""

import datetime
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

import tomllib
from packaging.specifiers import SpecifierSet
from packaging.version import Version

PINS = Path("pins.toml")


def fetch_json(url, token=None):
    """Return the JSON document at `url`."""
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def github_token():
    """Return a GitHub token from `GITHUB_TOKEN` or the gh CLI, else None."""
    if token := os.environ.get("GITHUB_TOKEN"):
        return token
    try:
        gh = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return gh.stdout.strip() or None


def sha256_of(url):
    """Return the hex SHA-256 of the file at `url`."""
    digest = hashlib.sha256()
    with urllib.request.urlopen(url) as response:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_python(requires_python):
    """Return the newest stable CPython cycle allowed by `requires_python`."""
    cycles = fetch_json("https://endoflife.date/api/python.json")
    allowed = SpecifierSet(requires_python)
    return max(
        (c["cycle"] for c in cycles if Version(c["cycle"]) in allowed),
        key=Version,
    )


def supported_ubuntu_image(current):
    """Advance the LTS base image only once the pinned one has gone EOL."""
    pinned = current.removeprefix("ubuntu:")
    today = datetime.datetime.now(tz=datetime.timezone.utc).date()
    supported = [
        c["cycle"]
        for c in fetch_json("https://endoflife.date/api/ubuntu.json")
        if c.get("lts") and datetime.date.fromisoformat(c["eol"]) > today
    ]
    if pinned in supported:
        return current
    oldest = min(
        (c for c in supported if Version(c) > Version(pinned)),
        key=Version,
    )
    return f"ubuntu:{oldest}"


def latest_nfpm():
    """Return the newest nfpm release version."""
    release = fetch_json(
        "https://api.github.com/repos/goreleaser/nfpm/releases/latest",
        token=github_token(),
    )
    return release["tag_name"].removeprefix("v")


def whisper_revision(repo):
    """Return the current snapshot commit of the Hugging Face `repo`."""
    return fetch_json(f"https://huggingface.co/api/models/{repo}")["sha"]


def whisper_files(repo, revision):
    """Return `{filename: hex_sha256}` for the Whisper model files at `revision`.

    Mirrors stage-lang.sh's `*.bin`/`*.json`/`*.txt` selection. LFS weights
    already carry their sha256 in the tree listing; the smaller files are hashed
    by download, since their tree `oid` is a git SHA-1, not a content hash.
    """
    tree = fetch_json(
        f"https://huggingface.co/api/models/{repo}/tree/{revision}?recursive=true"
    )
    files = {}
    for entry in tree:
        path = entry["path"]
        if entry.get("type") != "file" or not path.endswith((".bin", ".json", ".txt")):
            continue
        if lfs := entry.get("lfs"):
            files[path] = lfs["oid"].removeprefix("sha256:")
        else:
            files[path] = sha256_of(
                f"https://huggingface.co/{repo}/resolve/{revision}/{path}"
            )
    return files


def piper_files(piper, revision):
    """Return `{filename: hex_sha256}` for the Piper voice's two files at `revision`.

    The `.onnx` weight is LFS, so its sha256 comes from the tree listing (no
    multi-MB download); the small `.onnx.json` is hashed by download. The listing
    is scoped to `path` because the voice repo holds every language's voices.
    """
    tree = fetch_json(
        f"https://huggingface.co/api/models/{piper['repo']}/tree/{revision}/{piper['path']}"
    )
    wanted = {f"{piper['voice']}.onnx", f"{piper['voice']}.onnx.json"}
    files = {}
    for entry in tree:
        name = entry["path"].rsplit("/", 1)[-1]
        if name not in wanted:
            continue
        if lfs := entry.get("lfs"):
            files[name] = lfs["oid"].removeprefix("sha256:")
        else:
            files[name] = sha256_of(
                f"https://huggingface.co/{piper['repo']}/resolve"
                f"/{revision}/{piper['path']}/{name}"
            )
    return files


def set_files(text, code, model, files):
    """Insert or replace the `[lang.<code>.<model>.files]` table in `text`.

    The table is machine-owned, so it is rewritten wholesale rather than bumped
    key by key; a first run drops it in after the model's scalar keys, before
    the next table.
    """
    block = "\n".join(
        [f"[lang.{code}.{model}.files]"]
        + [f'"{name}" = "{files[name]}"' for name in sorted(files)]
    )
    if match := re.search(rf"\[lang\.{re.escape(code)}\.{model}\.files\][^\[]*", text):
        separator = "\n\n" if match.end() < len(text) else "\n"
        return text[: match.start()] + block + separator + text[match.end() :]
    scalars = re.search(
        rf"\[lang\.{re.escape(code)}\.{model}\]\n(?:[^\[\n].*\n)*", text
    )
    return text[: scalars.end()] + "\n" + block + "\n" + text[scalars.end() :]


def latest_piper_tag(repo):
    """Return the newest release tag of the Hugging Face `repo`."""
    refs = fetch_json(f"https://huggingface.co/api/models/{repo}/refs")
    return max(
        (tag["name"] for tag in refs["tags"]),
        key=lambda name: Version(name.removeprefix("v")),
    )


def bump(text, key, old, new, label):
    """Replace `key = "old"` in `text` with `new`, reporting the change."""
    if old == new:
        print(f"  ok    {label} = {old}")
        return text
    print(f"  bump  {label}: {old} -> {new}")
    return text.replace(f'{key} = "{old}"', f'{key} = "{new}"', 1)


def content(lang):
    """Return a language pack's file→checksum map: its actual shipped content.

    Empty until the `.files` tables have been generated, so a newly added pack
    (scalars only) reads as no content yet.
    """
    return {**lang["whisper"].get("files", {}), **lang["piper"].get("files", {})}


def next_patch(version):
    """Return `version` (X.Y.Z) with its patch component incremented."""
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def bump_lang_version(text, code, old, new):
    """Replace the `version` under the `[lang.<code>]` header, reporting it.

    Anchored to the pack's own table header so packs that share a version number
    don't collide, unlike the section-agnostic `bump`.
    """
    print(f"  bump  lang.{code}.version: {old} -> {new}")
    header = re.escape(f"[lang.{code}]")
    return re.sub(
        rf'({header}\nversion = ")({re.escape(old)})(")',
        rf"\g<1>{new}\g<3>",
        text,
        count=1,
    )


def update_toolchain(text, pins, requires_python):
    """Bump the bundled CPython, build-container image, and nfpm pins in `text`."""
    text = bump(
        text,
        "bundle",
        pins["python"]["bundle"],
        latest_python(requires_python),
        "python.bundle",
    )
    text = bump(
        text,
        "ubuntu_image",
        pins["toolchain"]["ubuntu_image"],
        supported_ubuntu_image(pins["toolchain"]["ubuntu_image"]),
        "toolchain.ubuntu_image",
    )
    return bump(
        text, "nfpm", pins["toolchain"]["nfpm"], latest_nfpm(), "toolchain.nfpm"
    )


def update_language(text, code, lang):
    """Bump one language pack's Whisper and Piper revisions and refill its `.files`."""
    whisper, piper = lang["whisper"], lang["piper"]
    new_revision = whisper_revision(whisper["repo"])
    text = bump(
        text,
        "revision",
        whisper["revision"],
        new_revision,
        f"lang.{code}.whisper.revision",
    )
    files = whisper_files(whisper["repo"], new_revision)
    text = set_files(text, code, "whisper", files)
    print(f"  files lang.{code}.whisper.files ({len(files)} files)")

    new_tag = latest_piper_tag(piper["repo"])
    text = bump(
        text, "revision", piper["revision"], new_tag, f"lang.{code}.piper.revision"
    )
    files = piper_files(piper, new_tag)
    text = set_files(text, code, "piper", files)
    print(f"  files lang.{code}.piper.files ({len(files)} files)")
    return text


def bump_versions(text, pins):
    """Bump each language pack's version to follow its regenerated content.

    A pack's version tracks its models: where the refreshed `.files` checksums in
    `text` differ from what `pins` held, the patch component is bumped, so a
    changed model always ships under a new version. A newly added pack (no
    `.files` yet) keeps its hand-set version — the first checksum fill is not a
    change.
    """
    updated = tomllib.loads(text)["lang"]
    for code, lang in pins["lang"].items():
        was = content(lang)
        if was and was != content(updated[code]):
            text = bump_lang_version(
                text, code, lang["version"], next_patch(lang["version"])
            )
        else:
            print(f"  ok    lang.{code}.version = {lang['version']}")
    return text


def main():
    """Refresh every pin and rewrite pins.toml when anything moved."""
    text = original = PINS.read_text(encoding="utf-8")
    pins = tomllib.loads(text)
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    text = update_toolchain(text, pins, pyproject["project"]["requires-python"])
    for code, lang in pins["lang"].items():
        text = update_language(text, code, lang)
    text = bump_versions(text, pins)

    if text != original:
        PINS.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
