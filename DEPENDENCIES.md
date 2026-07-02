# Dependencies

Every version EasySpeak pins lives in one of four data files; nothing is
pinned inside scripts or code. When a version changes, exactly one of these
files changes — the consuming scripts stay untouched.

| Lock file        | Maintained          | Pins                                                  |
|------------------|---------------------|-------------------------------------------------------|
| `pins.toml`      | `just update-pins`  | Speech models, bundled CPython, build container, nfpm |
| `pyproject.toml` | by hand             | Supported Python range, dependency lower bounds       |
| `uv.lock`        | `just requirements` | Exact Python library versions, wheel hashes           |
| `flake.lock`     | `nix flake update`  | nixpkgs revision for dev shell and `nix run`          |

## pins.toml

The hand-maintained lock file for everything that is *downloaded* by the
packaging scripts and the Nix flake rather than resolved by a package manager.
Each language pack pins an immutable Hugging Face revision — a commit for the
Whisper model, a tag for the Piper voice — next to a `[lang.<code>.<model>.files]`
table mapping every downloaded filename to its SHA-256. Other entries pin the
bundled CPython, the build-container image, and nfpm. Its consumers:

- `flake.nix` — fetches the Piper voice via `builtins.fromTOML`, each file
  checksum-verified by `fetchurl` against the `piper.files` table.
- `packaging/stage-lang.sh` — downloads the speech models for each
  `easyspeak-lang-*` package; Piper files are checksum-verified with
  `sha256sum`, the Whisper model by its pinned revision.
- `packaging/stage-bundle.sh` — materialises the pinned standalone CPython.
- `packaging/build-in-docker.sh` — pulls the pinned build-container image and
  nfpm release.

The per-file `.files` tables are generated, not hand-written — they also let an
out-of-tree Nix package pin each file up front instead of hashing whole repos.
`just update-pins` regenerates every `.files` table from the pinned revision on
each run — large LFS weights read their sha256 from the Hugging Face tree
listing, so it stays cheap — so any edit is picked up with no extra step:

- Add a language by writing only its scalar fields — `[lang.<code>.whisper]`
  (`model`/`repo`/`revision`) and `[lang.<code>.piper]`
  (`voice`/`repo`/`revision`/`path`) — then run `just update-pins` to bump the
  revisions and fill both `.files` tables.
- Change a voice or model in place by editing its scalar fields and running
  `just update-pins`; the `.files` table follows automatically.

The `easyspeak-lang-*` packages carry the app's release version, so a newer
package version does not imply newer model content — the model content changes
only when `pins.toml` does.

`just update-pins` bumps every entry to its current upstream version and
recomputes checksums; the build container advances only when its LTS leaves
standard support, since its glibc is the packages' compatibility floor.
Review the diff before committing.

## Deliberately floating

- uv itself: latest in CI (`astral-sh/setup-uv`) and in the build container
  (install script); pinned only for the dev shell via `flake.lock`.
- GitHub Actions: pinned by major version tag, floating within it.
- The Whisper model at *runtime*: with `EASYSPEAK_OFFLINE=relaxed` and no
  local model, faster-whisper fetches the latest snapshot from Hugging Face
  (`src/core/config.py`); installing the language package avoids this
  entirely.
