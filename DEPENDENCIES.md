# Dependencies

Every version EasySpeak pins lives in one of four data files; nothing is
pinned inside scripts or code. When a version changes, exactly one of these
files changes — the consuming scripts stay untouched.

| Lock file        | Maintained          | Pins                                                  |
|------------------|---------------------|-------------------------------------------------------|
| `pins.toml`      | by hand             | Speech models, bundled CPython, build container, nfpm |
| `pyproject.toml` | by hand             | Supported Python range, dependency lower bounds       |
| `uv.lock`        | `just requirements` | Exact Python library versions, wheel hashes           |
| `flake.lock`     | `nix flake update`  | nixpkgs revision for dev shell and `nix run`          |

## pins.toml

The hand-maintained lock file for everything that is *downloaded* by the
packaging scripts and the Nix flake rather than resolved by a package manager.
Each entry pins an immutable revision (a Hugging Face commit or tag, a release
version, an image tag), plus SHA-256 checksums where the artifact is a single
file. Its consumers:

- `flake.nix` — fetches the Piper voice via `builtins.fromTOML`,
  checksum-verified by `fetchurl`.
- `packaging/stage-lang.sh` — downloads the speech models for each
  `easyspeak-lang-*` package; Piper files are checksum-verified with
  `sha256sum`.
- `packaging/stage-bundle.sh` — materialises the pinned standalone CPython.
- `packaging/build-in-docker.sh` — pulls the pinned build-container image and
  nfpm release.

The `easyspeak-lang-*` packages carry the app's release version, so a newer
package version does not imply newer model content — the model content changes
only when `pins.toml` does.

## Deliberately floating

- uv itself: latest in CI (`astral-sh/setup-uv`) and in the build container
  (install script); pinned only for the dev shell via `flake.lock`.
- GitHub Actions: pinned by major version tag, floating within it.
- The Whisper model at *runtime*: with `EASYSPEAK_OFFLINE=relaxed` and no
  local model, faster-whisper fetches the latest snapshot from Hugging Face
  (`src/core/config.py`); installing the language package avoids this
  entirely.
