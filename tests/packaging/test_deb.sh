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
has easyspeak/extension.js
has easyspeak/extension-helpers.js
has easyspeak/prefs.js
has easyspeak/metadata.json
has easyspeak/schemas/org.gnome.shell.extensions.easyspeak.gschema.xml
has easyspeak/schemas/gschemas.compiled

echo "✔  Debian package looks good."
