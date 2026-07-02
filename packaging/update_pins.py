"""Bump the hand-maintained pins in pins.toml to their current upstream versions.

One policy per pin:

- `python.bundle` — newest stable CPython minor that satisfies the project's
  `requires-python` range.
- `toolchain.ubuntu_image` — advances only when the pinned LTS leaves standard
  support: the container's glibc is the packages' compatibility floor, so
  "newest LTS" would silently drop older target distros.
- `toolchain.nfpm` — latest GitHub release.
- `lang.*.whisper.revision` — the model repo's current snapshot commit.
- `lang.*.piper.revision` — the voice repo's newest tag; the file checksums
  are re-downloaded and recomputed when the tag moves.

Values are rewritten in place, so comments in pins.toml survive. Nothing is
committed; review with `git diff pins.toml`.
"""

import datetime
import hashlib
import json
import os
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


def main():
    """Refresh every pin and rewrite pins.toml when anything moved."""
    text = original = PINS.read_text(encoding="utf-8")
    pins = tomllib.loads(text)
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    requires_python = pyproject["project"]["requires-python"]

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
    text = bump(
        text, "nfpm", pins["toolchain"]["nfpm"], latest_nfpm(), "toolchain.nfpm"
    )

    for code, lang in pins["lang"].items():
        whisper, piper = lang["whisper"], lang["piper"]
        text = bump(
            text,
            "revision",
            whisper["revision"],
            whisper_revision(whisper["repo"]),
            f"lang.{code}.whisper.revision",
        )
        new_tag = latest_piper_tag(piper["repo"])
        if new_tag != piper["revision"]:
            base = (
                f"https://huggingface.co/{piper['repo']}/resolve"
                f"/{new_tag}/{piper['path']}/{piper['voice']}"
            )
            text = bump(
                text,
                "revision",
                piper["revision"],
                new_tag,
                f"lang.{code}.piper.revision",
            )
            text = bump(
                text,
                "onnx_sha256",
                piper["onnx_sha256"],
                sha256_of(f"{base}.onnx"),
                f"lang.{code}.piper.onnx_sha256",
            )
            text = bump(
                text,
                "json_sha256",
                piper["json_sha256"],
                sha256_of(f"{base}.onnx.json"),
                f"lang.{code}.piper.json_sha256",
            )
        else:
            print(f"  ok    lang.{code}.piper.revision = {new_tag}")

    if text != original:
        PINS.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
