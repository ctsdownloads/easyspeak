#!/usr/bin/env bash
set -euo pipefail

codes=("$@")
[ "${#codes[@]}" -gt 0 ] || mapfile -t codes < <(grep -Po '^\[lang\.\K[^.\]]+(?=\]$)' pins.toml)
[ "${#codes[@]}" -gt 0 ] || { echo "no languages defined in pins.toml" >&2; exit 1; }

want_version() {
    uv run --no-project python - "$1" <<'PY'
import sys
import tomllib

with open("pins.toml", "rb") as f:
    print(tomllib.load(f)["lang"][sys.argv[1]]["version"])
PY
}

check() {
    local code="$1" want deb rpm deb_v rpm_v files
    want=$(want_version "$code")
    deb=$(ls -t "dist/easyspeak-lang-${code}_"*.deb | head -1)
    rpm=$(ls -t "dist/easyspeak-lang-${code}-"*.rpm | head -1)

    # The pack version comes from pins.toml, independent of the app release —
    # that independence is the whole point of a data package.
    echo "[$code] carries its own version ($want), not the app's"
    deb_v=$(dpkg-deb --field "$deb" Version)
    rpm_v=$(rpm --query --package "$rpm" --queryformat '%{VERSION}' 2>/dev/null)
    [ "$deb_v" = "$want" ] || { echo "  [$code] .deb version $deb_v != $want" >&2; exit 1; }
    [ "$rpm_v" = "$want" ] || { echo "  [$code] .rpm version $rpm_v != $want" >&2; exit 1; }

    echo "[$code] ships the Whisper model and the Piper voice"
    for files in "$(dpkg-deb --contents "$deb")" "$(rpm --query --list --package "$rpm" 2>/dev/null)"; do
        grep -q /opt/easyspeak/models/whisper/ <<<"$files" || { echo "  [$code] MISSING whisper" >&2; exit 1; }
        grep -q /opt/easyspeak/models/piper/ <<<"$files" || { echo "  [$code] MISSING piper" >&2; exit 1; }
    done
}

for code in "${codes[@]}"; do
    check "$code"
done

echo "✔  Language packages look good."
