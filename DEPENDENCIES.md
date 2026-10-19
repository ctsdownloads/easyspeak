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
table mapping every downloaded filename to its SHA-256. The `[tts.kokoro]`
family pins the optional Kokoro reply voice the same way: the Kokoro-82M model
from the `onnx-community/Kokoro-82M-v1.0-ONNX` Hugging Face repo at a pinned
revision, and the voice binaries from the `kokoro-onnx` GitHub release tagged
`model-files-v1.1`. Other entries pin the bundled CPython, the build-container
image, and nfpm. Its consumers:

- `flake.nix` — fetches the Piper voice via `builtins.fromTOML`, each file
  checksum-verified by `fetchurl` against the `piper.files` table.
- `packaging/stage-lang.sh` — downloads the speech models for each
  `easyspeak-lang-*` package; Piper files are checksum-verified with
  `sha256sum`, the Whisper model by its pinned revision.
- `packaging/stage-bundle.sh` — materialises the pinned standalone CPython.
- `packaging/build-in-docker.sh` — pulls the pinned build-container image and
  nfpm release, and reads each language pack's `version` to stamp its package.
- `src/core/provision.py` — installs the Kokoro engine on demand
  (`easyspeak --provision-kokoro`). `pins.toml` ships in no package, so it
  reads the generated `src/core/runtime_pins.toml` copy instead and
  checksum-verifies the model downloads against its `[tts.kokoro.files]`
  table.

The per-file `.files` tables are generated, not hand-written — they also let an
out-of-tree Nix package pin each file up front instead of hashing whole repos.
`just update-pins` regenerates every `.files` table from the pinned revision on
each run — large LFS weights read their sha256 from the Hugging Face tree
listing, and `[tts.kokoro]`'s GitHub-release voice bin reads the release
asset's `digest` field (hash-by-download when an asset lacks it), so it stays
cheap — and it also rewrites `src/core/runtime_pins.toml`, the packaged copy
the Kokoro provisioner reads. `pins.toml` remains the single hand-edited
source of truth; the copy is build output, like the `.files` tables themselves.
Any edit is picked up with no extra step:

- Add a language by writing its `[lang.<code>]` `version` and the scalar fields
  of `[lang.<code>.whisper]` (`model`/`repo`/`revision`) and
  `[lang.<code>.piper]` (`voice`/`repo`/`revision`/`path`) — then run
  `just update-pins` to bump the revisions and fill both `.files` tables.
- Change a voice or model in place by editing its scalar fields and running
  `just update-pins`; the `.files` table and the pack `version` both follow
  automatically.

The `[tts.kokoro]` entries pin what provisioning downloads; the library itself
is pinned like any other Python dependency. The `tts-kokoro` extra
(`kokoro-onnx>=0.6.1,<0.7`, marked `python_version < '3.14'`) exists so
`uv.lock` records a tested CPU resolution for source installs — and the GPU
wheel flavor is deliberately in neither file, because the provisioner installs
it from its own major-bounded specs that `uv.lock` never sees.

Each `easyspeak-lang-*` package carries its own `[lang.<code>].version`,
independent of the application's release version. `just update-pins` bumps its
patch component whenever that language's pinned content changes, so the version
always tracks the delivered models (hand-edit it for a larger, semantic bump).
The app package only `recommends` the language pack by name, without a version
constraint, so the two release on their own cadence.

`just update-pins` bumps every entry to its current upstream version and
recomputes checksums; the build container advances only when its LTS leaves
standard support, since its glibc is the packages' compatibility floor.
Review the diff before committing.

## Deliberately floating

- uv itself: latest in CI (`astral-sh/setup-uv`) and in the build container
  (install script); pinned only for the dev shell via `flake.lock`.
- GitHub Actions: pinned by major version tag, floating within it.
- The speech model at *runtime*: with `EASYSPEAK_OFFLINE=relaxed` and no
  local model, onnx-asr fetches the latest Parakeet snapshot from Hugging Face
  into the models directory, and faster-whisper a Whisper one when that is the
  backend (`src/core/config.py`); installing the packages avoids this entirely.
