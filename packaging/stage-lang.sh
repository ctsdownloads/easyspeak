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

# Per-language model selection. faster-whisper models live in Systran HF repos;
# Piper voices live under rhasspy/piper-voices at <path>/<voice>.onnx(.json).
case "$CODE" in
  en)
    WHISPER_NAME="base.en"
    WHISPER_REPO="Systran/faster-whisper-base.en"
    PIPER_VOICE="en_US-amy-medium"
    PIPER_PATH="en/en_US/amy/medium"
    ;;
  *)
    echo "error: no model mapping for language '$CODE'" >&2
    exit 1
    ;;
esac

STAGE="$REPO_ROOT/dist/stage-lang-$CODE"
MODELS="$STAGE/opt/easyspeak/models"
rm -rf "$STAGE"
mkdir -p "$MODELS/whisper" "$MODELS/piper"

echo ">> [$CODE] downloading Whisper model ($WHISPER_NAME) from $WHISPER_REPO"
uv run --no-project --with huggingface_hub python - "$WHISPER_REPO" "$MODELS/whisper/$WHISPER_NAME" <<'PY'
import sys
from huggingface_hub import snapshot_download
repo, dest = sys.argv[1], sys.argv[2]
# Only the files faster-whisper needs; skip README/.gitattributes.
snapshot_download(repo, local_dir=dest, allow_patterns=["*.bin", "*.json", "*.txt"])
PY
rm -rf "$MODELS/whisper/$WHISPER_NAME/.cache"

echo ">> [$CODE] downloading Piper voice ($PIPER_VOICE)"
PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/$PIPER_PATH"
curl -fsSL "$PIPER_BASE/$PIPER_VOICE.onnx"      -o "$MODELS/piper/$PIPER_VOICE.onnx"
curl -fsSL "$PIPER_BASE/$PIPER_VOICE.onnx.json" -o "$MODELS/piper/$PIPER_VOICE.onnx.json"

echo ">> [$CODE] language data staged at $STAGE ($(du -sh "$MODELS" | cut -f1))"
