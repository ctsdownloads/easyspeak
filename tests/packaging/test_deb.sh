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

echo "The .deb ships the license and the tray helper for other desktops"
has /usr/share/doc/easyspeak/LICENSE
has easyspeak/core/statusnotifier.py
has easyspeak/core/statusnotifier.xml
has easyspeak/core/autostart.py
has easyspeak/core/about.py

# Package names a control field lists, one per line, without versions.
names() { dpkg-deb --field "$deb" "$1" | tr ',|' '\n' | sed 's/^ *//; s/[ (].*//'; }
lists() { grep -qx -- "$2" <<<"$(names "$1")" || { echo "  NOT IN $1: $2" >&2; exit 1; }; }
avoids() { ! grep -qx -- "$2" <<<"$(names "$1")" || { echo "  IN $1: $2" >&2; exit 1; }; }

echo "The .deb only suggests GNOME's parts and kdialog, so other desktops stay lean"
for package in gnome-shell libgtk-4-1 libadwaita-1-0 gir1.2-gtk-4.0 gir1.2-adw-1 kdialog; do
    lists Suggests "$package"
    avoids Depends "$package"
    avoids Recommends "$package"
done
lists Depends python3-gi

echo "✔  Debian package looks good."
