// EasySpeak GNOME Shell extension preferences (gjs / GTK4 / libadwaita).
//
// Backs the "Settings" button the GNOME Extensions app shows for any extension
// that ships a prefs.js. It toggles whether EasySpeak starts at login — by
// writing the per-user autostart entry — and opens an About dialog. The pure
// autostart text handling lives in extension-helpers.js so it can be unit-tested;
// this file is the Gio/Adw glue, which only runs inside the prefs process.

import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';
import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

import {
    autostartDesktopEntry,
    autostartEnabledFromText,
} from './extension-helpers.js';

// ~/.config/autostart/easyspeak.desktop, matching core.desktop_integration.
const AUTOSTART_SUBPATH = ['autostart', 'easyspeak.desktop'];

const ABOUT = {
    application_name: 'EasySpeak',
    application_icon: 'audio-input-microphone',
    developer_name: 'Matt Hartley',
    comments:
        'Voice control for Linux desktops. Fully local, no cloud, Wayland-native.',
    website: 'https://ctsdownloads.github.io/easyspeak/',
    issue_url: 'https://github.com/ctsdownloads/easyspeak/issues',
    copyright: '© Matt Hartley and the EasySpeak contributors',
};

export default class EasySpeakPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const page = new Adw.PreferencesPage();
        const group = new Adw.PreferencesGroup({ title: 'Configure EasySpeak' });
        page.add(group);

        const autostart = new Adw.SwitchRow({
            title: 'Start EasySpeak on login',
            subtitle: 'Launch EasySpeak automatically when you log in',
            active: this._autostartEnabled(),
        });
        autostart.connect('notify::active', (row) =>
            this._setAutostartEnabled(row.active));
        group.add(autostart);

        // Persisted in dconf via the extension's GSettings schema, and read by
        // extension.js to decide between the tray icon and the Quick Settings
        // toggle. Bound both ways so a change here takes effect live in the shell.
        const quickSettings = new Adw.SwitchRow({
            title: 'Show EasySpeak in Quick Settings Menu',
            subtitle:
                'Use a Quick Settings toggle instead of the panel tray icon',
            active: false,
        });
        this.getSettings().bind(
            'show-in-quick-settings', quickSettings, 'active',
            Gio.SettingsBindFlags.DEFAULT);
        group.add(quickSettings);

        const aboutGroup = new Adw.PreferencesGroup();
        page.add(aboutGroup);

        const about = new Adw.ActionRow({
            title: 'About EasySpeak',
            activatable: true,
        });
        about.add_suffix(new Gtk.Image({ icon_name: 'go-next-symbolic' }));
        about.connect('activated', () => this._presentAbout(window));
        aboutGroup.add(about);

        window.add(page);
    }

    _autostartFile() {
        return Gio.File.new_for_path(
            GLib.build_filenamev([GLib.get_user_config_dir(), ...AUTOSTART_SUBPATH]));
    }

    _autostartEnabled() {
        const file = this._autostartFile();
        if (!file.query_exists(null))
            return true;
        const [ok, contents] = file.load_contents(null);
        return ok ? autostartEnabledFromText(new TextDecoder().decode(contents)) : true;
    }

    _setAutostartEnabled(enabled) {
        const file = this._autostartFile();
        const dir = file.get_parent();
        if (!dir.query_exists(null))
            dir.make_directory_with_parents(null);
        const data = new TextEncoder().encode(autostartDesktopEntry(enabled));
        file.replace_contents(
            data, null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
    }

    _presentAbout(window) {
        const dialog = new Adw.AboutDialog({
            ...ABOUT,
            license_type: Gtk.License.GPL_3_0,
        });
        dialog.add_link('Source Code', 'https://github.com/ctsdownloads/easyspeak');
        dialog.add_link(
            'Discussions', 'https://github.com/ctsdownloads/easyspeak/discussions');
        dialog.present(window);
    }
}
