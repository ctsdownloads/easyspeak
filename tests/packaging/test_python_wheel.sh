#!/usr/bin/env bash
set -euo pipefail

wheel=$(ls -t dist/easyspeak_linux-*-py3-none-any.whl | head -1)
files=$(unzip -Z1 "$wheel")

has() { grep -q "$1" <<<"$files" || { echo "  MISSING: $1" >&2; exit 1; }; }
lacks() { m=$(grep -E "$1" <<<"$files") || return 0; sed 's/^/  FORBIDDEN: /' <<<"$m" >&2; exit 1; }

echo "The wheel ships no markdown, docs, tests, or dev tooling config"
lacks 'C.*\.md|DEPENDENCIES\.md|pins\.toml|docs|package\.json|tests|\.lock|\.mjs|\.nix|\.ya?ml'

echo "The wheel ships the core module and the plugins"
has core
has plugins

echo "The wheel ships the launcher data and the GNOME extension"
has easyspeak.desktop
has easyspeak-autostart.desktop
has easyspeak-extension-refresh.service.in
has extension.js
has extension-helpers.js
has grid.js
has windows.js
has screenshot.js
has indicator.js
has prefs.js
has metadata.json
has schemas/org.gnome.shell.extensions.easyspeak.gschema.xml
has schemas/gschemas.compiled

echo "✔  Python wheel looks good."
