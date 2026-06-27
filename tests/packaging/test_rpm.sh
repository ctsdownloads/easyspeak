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
has easyspeak/extension.js
has easyspeak/extension-helpers.js
has easyspeak/prefs.js
has easyspeak/metadata.json
has easyspeak/schemas/org.gnome.shell.extensions.easyspeak.gschema.xml
has easyspeak/schemas/gschemas.compiled

echo "✔  Red Hat package looks good."
