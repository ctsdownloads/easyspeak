#!/usr/bin/env bash
set -euo pipefail

rpm=$(ls -t dist/easyspeak-*.x86_64.rpm | head -1)
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

echo "The .rpm ships the license and the tray helper for other desktops"
has /usr/share/doc/easyspeak/LICENSE
has easyspeak/core/statusnotifier.py
has easyspeak/core/statusnotifier.xml
has easyspeak/core/autostart.py
has easyspeak/core/about.py

# Package names a dependency query lists, one per line, without versions.
names() { rpm --query --package "--$1" "$rpm" 2>/dev/null | sed 's/[ (].*//'; }
lists() { grep -qx -- "$2" <<<"$(names "$1")" || { echo "  NOT IN $1: $2" >&2; exit 1; }; }
avoids() { ! grep -qx -- "$2" <<<"$(names "$1")" || { echo "  IN $1: $2" >&2; exit 1; }; }

echo "The .rpm only suggests GNOME's parts and kdialog, so other desktops stay lean"
for package in gnome-shell gtk4 libadwaita kdialog; do
    lists suggests "$package"
    avoids requires "$package"
    avoids recommends "$package"
done
lists requires python3-gobject

echo "✔  Red Hat package looks good."
