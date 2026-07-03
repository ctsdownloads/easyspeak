#!/usr/bin/env bash
set -euo pipefail

code="${1:-en}"

# The pack version lives in pins.toml, independent of the application's release
# version — that independence is the whole point of a data package, so assert it.
want=$(uv run --no-project python - "$code" <<'PY'
import sys
import tomllib

with open("pins.toml", "rb") as f:
    print(tomllib.load(f)["lang"][sys.argv[1]]["version"])
PY
)

deb=$(ls -t "dist/easyspeak-lang-${code}_"*.deb | head -1)
rpm=$(ls -t "dist/easyspeak-lang-${code}-"*.rpm | head -1)

echo "The language package carries its own version ($want), not the app's"
deb_version=$(dpkg-deb --field "$deb" Version)
rpm_version=$(rpm --query --package "$rpm" --queryformat '%{VERSION}' 2>/dev/null)
[ "$deb_version" = "$want" ] || { echo "  .deb version $deb_version != $want" >&2; exit 1; }
[ "$rpm_version" = "$want" ] || { echo "  .rpm version $rpm_version != $want" >&2; exit 1; }

echo "The language package ships the Whisper model and the Piper voice"
for files in "$(dpkg-deb --contents "$deb")" "$(rpm --query --list --package "$rpm" 2>/dev/null)"; do
    has() { grep -q "$1" <<<"$files" || { echo "  MISSING: $1" >&2; exit 1; }; }
    has /opt/easyspeak/models/whisper/
    has /opt/easyspeak/models/piper/
done

echo "✔  Language package looks good."
