#!/usr/bin/env bash
set -euo pipefail

want=$(uv run --no-project python - <<'PY'
import tomllib

with open("pins.toml", "rb") as f:
    print(tomllib.load(f)["stt"]["parakeet"]["version"])
PY
)
deb=$(ls -t dist/easyspeak-stt-parakeet_*.deb | head -1)
rpm=$(ls -t dist/easyspeak-stt-parakeet-*.rpm | head -1)

echo "[parakeet] carries its own version ($want), not the app's"
deb_v=$(dpkg-deb --field "$deb" Version)
rpm_v=$(rpm --query --package "$rpm" --queryformat '%{VERSION}' 2>/dev/null)
[ "$deb_v" = "$want" ] || { echo "  .deb version $deb_v != $want" >&2; exit 1; }
[ "$rpm_v" = "$want" ] || { echo "  .rpm version $rpm_v != $want" >&2; exit 1; }

echo "[parakeet] ships the whole model and the license notice"
for files in "$(dpkg-deb --contents "$deb")" "$(rpm --query --list --package "$rpm" 2>/dev/null)"; do
    for name in config.json vocab.txt encoder-model.int8.onnx decoder_joint-model.int8.onnx; do
        grep -q "/opt/easyspeak/models/parakeet/$name" <<<"$files" || { echo "  MISSING $name" >&2; exit 1; }
    done
    grep -q "/usr/share/doc/easyspeak-stt-parakeet/copyright" <<<"$files" || { echo "  MISSING copyright" >&2; exit 1; }
done

echo "✔  Speech model package looks good."
