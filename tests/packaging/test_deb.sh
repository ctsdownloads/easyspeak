#!/usr/bin/env bash
set -euo pipefail

deb=$(ls -t dist/easyspeak_*.deb | head -1)
files=$(dpkg-deb --contents "$deb")

has() { grep -q "$1" <<<"$files" || { echo "  MISSING: $1" >&2; exit 1; }; }

echo "The .deb installs the launcher, autostart entry and refresh unit"
has /usr/bin/easyspeak
has /usr/share/applications/easyspeak.desktop
has /etc/xdg/autostart/easyspeak.desktop
has /usr/lib/systemd/user/easyspeak-extension-refresh.service

echo "The .deb bundles the GNOME extension, schema included"
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

echo "✔  Debian package looks good."
