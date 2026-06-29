#!/usr/bin/env bash
set -euo pipefail

rpm=$(ls -t dist/easyspeak-*.rpm | grep -v -- '-lang-' | head -1)
files=$(rpm --query --list --package "$rpm" 2>/dev/null)

has() { grep -q "$1" <<<"$files" || { echo "  MISSING: $1" >&2; exit 1; }; }

echo "The .rpm installs the launcher, autostart entry and refresh unit"
has /usr/bin/easyspeak
has /usr/share/applications/easyspeak.desktop
has /etc/xdg/autostart/easyspeak.desktop
has /usr/lib/systemd/user/easyspeak-extension-refresh.service

echo "The .rpm bundles the GNOME extension, schema included"
has easyspeak/gnome/extension.js
has easyspeak/gnome/extension-helpers.js
has easyspeak/gnome/grid.js
has easyspeak/gnome/windows.js
has easyspeak/gnome/screenshot.js
has easyspeak/gnome/indicator.js
has easyspeak/gnome/prefs.js
has easyspeak/gnome/metadata.json
has easyspeak/gnome/schemas/org.gnome.shell.extensions.easyspeak.gschema.xml
has easyspeak/gnome/schemas/gschemas.compiled

echo "✔  Red Hat package looks good."
