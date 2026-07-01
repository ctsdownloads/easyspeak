#!/usr/bin/env bash
set -euo pipefail

sdist=$(ls -t dist/easyspeak_linux-*.tar.gz | head -1)
files=$(tar tzf "$sdist")

has() { grep -q "$1" <<<"$files" || { echo "  MISSING: $1" >&2; exit 1; }; }
lacks() { ! grep -qE "$1" <<<"$files" || { echo "  FORBIDDEN: $1" >&2; exit 1; }; }

echo "The sdist ships no markdown, docs, tests, or dev tooling config"
lacks 'C.*\.md|DEPENDENCIES\.md|pins\.toml|docs|package\.json|tests|\.lock|\.mjs|\.nix|\.ya?ml'

echo "The sdist ships the core module and the plugins"
has core
has plugins

echo "The sdist ships the launcher data and the GNOME extension"
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

echo "✔  Python sdist looks good."
