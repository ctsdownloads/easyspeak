#!/usr/bin/env bash
# Stage the Parakeet speech model into a tree that mirrors the install layout
# (/opt/easyspeak/models/parakeet/...), for nfpm to package as easyspeak-stt-parakeet
# (a noarch data package shared by every language the model covers). Every file
# is checksum-verified against pins.toml.
#
#   packaging/stage-stt.sh <code>     e.g. `parakeet`
set -euo pipefail

CODE="${1:?usage: stage-stt.sh <model-code>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

command -v uv >/dev/null   || { echo "error: uv is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "error: curl is required" >&2; exit 1; }

# The download base URL, then one "name sha256" line per file, from pins.toml.
FILES="$(uv run --no-project python - "$REPO_ROOT/pins.toml" "$CODE" <<'PY'
import sys
import tomllib

pins_file, code = sys.argv[1], sys.argv[2]
with open(pins_file, "rb") as f:
    stt = tomllib.load(f)["stt"].get(code)
if stt is None:
    sys.exit(f"error: no model pins for speech model '{code}' in pins.toml")
print(f"https://huggingface.co/{stt['repo']}/resolve/{stt['revision']}")
for name, sha256 in stt["files"].items():
    print(f"{name} {sha256}")
PY
)"
BASE="$(head -n1 <<<"$FILES")"

STAGE="$REPO_ROOT/dist/stage-stt-$CODE"
MODELS="$STAGE/opt/easyspeak/models/$CODE"
rm -rf "$STAGE"
mkdir -p "$MODELS"

echo ">> [$CODE] downloading the model from $BASE"
tail -n +2 <<<"$FILES" | while read -r name sha256; do
    curl -fsSL "$BASE/$name" -o "$MODELS/$name"
    echo "$sha256  $MODELS/$name" | sha256sum --check --quiet -
done

echo ">> [$CODE] speech model staged at $STAGE ($(du -sh "$MODELS" | cut -f1))"
