#!/usr/bin/env bash
# Stage the speech models for one EasySpeak language pack into a tree that mirrors
# the install layout (/opt/easyspeak/models/...), for nfpm to package as
# easyspeak-lang-<code> (a noarch data package). No app build needed.
#
#   packaging/stage-lang.sh <code>     e.g. `en`
set -euo pipefail

CODE="${1:?usage: stage-lang.sh <language-code>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

command -v uv >/dev/null   || { echo "error: uv is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "error: curl is required" >&2; exit 1; }

# Per-language model selection, read from the pins.toml lock file at the repo
# root (repos, revisions, and checksums live there, not here).
MODEL_VARS="$(uv run --no-project python - "$REPO_ROOT/pins.toml" "$CODE" <<'PY'
import sys
import tomllib

pins_file, code = sys.argv[1], sys.argv[2]
with open(pins_file, "rb") as f:
    lang = tomllib.load(f)["lang"].get(code)
if lang is None:
    sys.exit(f"error: no model pins for language '{code}' in pins.toml")
whisper, piper = lang["whisper"], lang["piper"]
print(f'WHISPER_NAME="{whisper["model"]}"')
print(f'WHISPER_REPO="{whisper["repo"]}"')
print(f'WHISPER_REV="{whisper["revision"]}"')
print(f'PIPER_VOICE="{piper["voice"]}"')
print(f'PIPER_BASE="https://huggingface.co/{piper["repo"]}/resolve/{piper["revision"]}/{piper["path"]}"')
print(f'PIPER_ONNX_SHA256="{piper["files"][piper["voice"] + ".onnx"]}"')
print(f'PIPER_JSON_SHA256="{piper["files"][piper["voice"] + ".onnx.json"]}"')
PY
)"
eval "$MODEL_VARS"

STAGE="$REPO_ROOT/dist/stage-lang-$CODE"
MODELS="$STAGE/opt/easyspeak/models"
rm -rf "$STAGE"
mkdir -p "$MODELS/whisper" "$MODELS/piper"

echo ">> [$CODE] downloading Whisper model ($WHISPER_NAME) from $WHISPER_REPO @ $WHISPER_REV"
uv run --no-project --with huggingface_hub python - "$WHISPER_REPO" "$WHISPER_REV" "$MODELS/whisper/$WHISPER_NAME" <<'PY'
import sys
from huggingface_hub import snapshot_download
repo, rev, dest = sys.argv[1], sys.argv[2], sys.argv[3]
# Only the files faster-whisper needs; skip README/.gitattributes.
snapshot_download(repo, revision=rev, local_dir=dest, allow_patterns=["*.bin", "*.json", "*.txt"])
PY
rm -rf "$MODELS/whisper/$WHISPER_NAME/.cache"

echo ">> [$CODE] downloading Piper voice ($PIPER_VOICE)"
curl -fsSL "$PIPER_BASE/$PIPER_VOICE.onnx"      -o "$MODELS/piper/$PIPER_VOICE.onnx"
curl -fsSL "$PIPER_BASE/$PIPER_VOICE.onnx.json" -o "$MODELS/piper/$PIPER_VOICE.onnx.json"
sha256sum --check --quiet - <<EOF
$PIPER_ONNX_SHA256  $MODELS/piper/$PIPER_VOICE.onnx
$PIPER_JSON_SHA256  $MODELS/piper/$PIPER_VOICE.onnx.json
EOF

echo ">> [$CODE] language data staged at $STAGE ($(du -sh "$MODELS" | cut -f1))"
