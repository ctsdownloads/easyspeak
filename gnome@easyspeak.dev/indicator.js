// Panel indicator and Quick Settings toggle (core surfaces). Rendering an
// indicator and a Quick Settings item is compositor-only, so the widgets live
// here; the sleep/quit/help/about *behaviour* they trigger lives in the daemon,
// reached through the one-shot control file below.

import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {
    indicatorVisibleForState,
    quickSettingsCheckedForState,
} from './extension-helpers.js';

const CACHE_DIR = GLib.get_home_dir() + '/.cache/easyspeak';
const CONTROL_FILE = CACHE_DIR + '/control';

// Menu actions (tray and Quick Settings alike) reach the daemon via a one-shot
// control file it polls each audio loop; it can't serve D-Bus while reading audio.
function writeControlCommand(command) {
    try {
        const dir = Gio.File.new_for_path(CACHE_DIR);
        if (!dir.query_exists(null)) dir.make_directory_with_parents(null);
        GLib.file_set_contents(CONTROL_FILE, command);
    } catch (e) {
        log('EasySpeak: failed to write control command: ' + e.message);
    }
}

// The indicator is shown ONLY while EasySpeak is deactivated. While it's running
// it listens continuously, so GNOME's own red microphone privacy icon already
// signals the open mic and the assistant is driven by voice — a second icon would
// just be noise. When deactivated the mic is released (GNOME's dot disappears) and
// voice is off, so this dimmed, struck-through mic becomes the one affordance to
// wake the assistant back up.
export const TrayIndicator = GObject.registerClass(
class TrayIndicator extends PanelMenu.Button {
    _init(openPreferences) {
        super._init(0.0, 'EasySpeak');
        this.visible = false;  // hidden until the daemon reports "muted"
        this._openPreferences = openPreferences;

        this._icon = new St.Icon({
            icon_name: 'microphone-disabled-symbolic',  // mic with a slash
            style_class: 'system-status-icon',
            style: 'color: rgba(255, 255, 255, 0.5);',  // dimmed: "asleep"
        });
        this.add_child(this._icon);

        const reactivateItem = new PopupMenu.PopupMenuItem('Reactivate EasySpeak');
        reactivateItem.connect('activate', () => writeControlCommand('unmute'));
        this.menu.addMenuItem(reactivateItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Settings opens this extension's own prefs window (prefs.js) in-process.
        // Help and About route through the daemon (which knows its interpreter
        // and the docs URL) via the same control-file channel as the other items.
        const settingsItem = new PopupMenu.PopupMenuItem('Settings…');
        settingsItem.connect('activate', () => this._openPreferences());
        this.menu.addMenuItem(settingsItem);

        const helpItem = new PopupMenu.PopupMenuItem('Help');
        helpItem.connect('activate', () => writeControlCommand('help'));
        this.menu.addMenuItem(helpItem);

        const aboutItem = new PopupMenu.PopupMenuItem('About EasySpeak');
        aboutItem.connect('activate', () => writeControlCommand('about'));
        this.menu.addMenuItem(aboutItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const quitItem = new PopupMenu.PopupMenuItem('Quit EasySpeak');
        quitItem.connect('activate', () => {
            writeControlCommand('quit');
            this.visible = false;  // the daemon is exiting; don't leave a stale icon
        });
        this.menu.addMenuItem(quitItem);
    }

    // Visible only while asleep, and only when the Quick Settings toggle (the
    // user's chosen alternative) isn't taking the tray's place.
    setState(state, hiddenForQuickSettings) {
        this.visible =
            indicatorVisibleForState(state) && !hiddenForQuickSettings;
    }
});

// Quick Settings alternative to the tray icon: on while listening, off while
// asleep; clicking sleeps/wakes the daemon. The expander holds Help and
// EasySpeak Settings, mirroring two of the tray menu's items.
const EasySpeakToggle = GObject.registerClass(
class EasySpeakToggle extends QuickSettings.QuickMenuToggle {
    _init(openPreferences) {
        super._init({
            title: 'EasySpeak',
            iconName: 'audio-input-microphone-symbolic',
            toggleMode: true,
        });

        // toggleMode flips `checked` before this fires, so it's the user's intent.
        this.connect('clicked', () =>
            writeControlCommand(this.checked ? 'unmute' : 'mute'));

        this.menu.setHeader('audio-input-microphone-symbolic', 'EasySpeak');
        this.menu.addAction('Help', () => writeControlCommand('help'));
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('EasySpeak Settings', () => {
            // Dismiss the whole Quick Settings popup first (as AZWallpaper does);
            // otherwise it keeps its modal grab and the prefs window opens behind
            // it, so the first click only closes the popup instead of reaching
            // the dialog.
            Main.panel.closeQuickSettings();
            openPreferences();
        });
    }

    // Setting `checked` directly doesn't emit 'clicked', so this won't loop back.
    setState(state) {
        this.checked = quickSettingsCheckedForState(state);
    }
});

export const EasySpeakQuickSettings = GObject.registerClass(
class EasySpeakQuickSettings extends QuickSettings.SystemIndicator {
    _init(openPreferences) {
        super._init();
        this.toggle = new EasySpeakToggle(openPreferences);
        this.quickSettingsItems.push(this.toggle);
    }

    setState(state) {
        this.toggle.setState(state);
    }

    setVisible(visible) {
        this.toggle.visible = visible;
    }
});
