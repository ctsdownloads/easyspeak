// Thin entrypoint: the Extension subclass, enable()/disable(), and the D-Bus
// interface + handler wiring. Every feature primitive lives in its own module
// (grid, windows, screenshot, indicator); this file only owns their lifecycle
// and routes D-Bus calls to them. Keep it generic — see issue #75.

import Gio from 'gi://Gio';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import { GridOverlay } from './grid.js';
import { WindowManager } from './windows.js';
import { ScreenshotManager } from './screenshot.js';
import { TrayIndicator, EasySpeakQuickSettings } from './indicator.js';

const DBUS_INTERFACE = `
<node>
  <interface name="org.easyspeak.Desktop">
    <!-- Grid overlay -->
    <method name="Show">
      <arg type="i" direction="in" name="width"/>
      <arg type="i" direction="in" name="height"/>
    </method>
    <method name="Hide"/>
    <method name="Update">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
      <arg type="i" direction="in" name="width"/>
      <arg type="i" direction="in" name="height"/>
    </method>

    <!-- Mouse control -->
    <method name="Click">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
    </method>
    <method name="DoubleClick">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
    </method>
    <method name="RightClick">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
    </method>
    <method name="MiddleClick">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
    </method>
    <method name="MoveTo">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
    </method>
    <method name="StartDrag">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
    </method>
    <method name="EndDrag">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
    </method>
    <method name="Scroll">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
      <arg type="s" direction="in" name="direction"/>
      <arg type="i" direction="in" name="clicks"/>
    </method>

    <!-- Screenshot for OCR -->
    <method name="TakeScreenshot">
      <arg type="s" direction="out" name="path"/>
    </method>

    <!-- Window management (focused window) -->
    <method name="CloseWindow"/>
    <method name="MinimizeWindow"/>
    <method name="MaximizeWindow"/>
    <method name="UnmaximizeWindow"/>
    <method name="FullscreenWindow"/>
    <method name="UnfullscreenWindow"/>
    <method name="TileLeft"/>
    <method name="TileRight"/>

    <!-- Window queries and focus -->
    <method name="GetWindows">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="FocusWindow">
      <arg type="s" direction="in" name="title"/>
      <arg type="b" direction="out" name="success"/>
    </method>

    <!-- Workspace control -->
    <method name="SwitchWorkspace">
      <arg type="i" direction="in" name="index"/>
    </method>
    <method name="NextWorkspace"/>
    <method name="PrevWorkspace"/>
    <method name="GetWorkspaceCount">
      <arg type="i" direction="out" name="count"/>
    </method>
    <method name="GetCurrentWorkspace">
      <arg type="i" direction="out" name="index"/>
    </method>

    <!-- Screen info -->
    <method name="GetScreenSize">
      <arg type="i" direction="out" name="width"/>
      <arg type="i" direction="out" name="height"/>
    </method>

    <!-- Panel indicator state (listening / active / thinking / muted) -->
    <method name="SetState">
      <arg type="s" direction="in" name="state"/>
    </method>
  </interface>
</node>`;

export default class EasySpeakGridExtension extends Extension {
    enable() {
        this._grid = new GridOverlay();
        this._winMgr = new WindowManager();
        this._screenMgr = new ScreenshotManager();
        this._tray = new TrayIndicator(() => this.openPreferences());
        Main.panel.addToStatusArea('easyspeak', this._tray);
        // addToStatusArea drops new indicators at the LEFT end of the status
        // area (the "application content" zone). Move ours to the RIGHT end of
        // that zone, immediately before GNOME's system menu, so it sits where
        // the red microphone privacy icon shows: when the daemon sleeps and
        // releases the mic, GNOME's red mic disappears and our struck-through
        // mic takes its place. (Same idea as brendaw/add-username-toppanel#28,
        // which used set_child_above_sibling to escape the default zone.)
        const rightBox = Main.panel._rightBox;
        const systemMenu = Main.panel.statusArea.quickSettings;
        if (systemMenu && rightBox.contains(systemMenu.container)) {
            rightBox.set_child_below_sibling(this._tray.container, systemMenu.container);
        } else {
            rightBox.set_child_above_sibling(this._tray.container, null);
        }

        // Last state the daemon pushed, so the tray's visibility can be recomputed
        // when the setting changes. Null until it first reports in.
        this._lastState = null;

        // getSettings() throws if the compiled schema isn't in place yet (e.g. an
        // update not yet picked up at login); fall back to "off" (tray-only)
        // rather than breaking the whole extension.
        try {
            this._settings = this.getSettings();
        } catch (e) {
            log('EasySpeak: settings schema unavailable, defaulting to tray: ' + e.message);
            this._settings = null;
        }

        // Always added to the panel; the setting only governs whether the toggle
        // shows, so flipping it takes effect live.
        this._quickSettings = new EasySpeakQuickSettings(() => this.openPreferences());
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._quickSettings);
        if (this._settings) {
            this._settingsChangedId = this._settings.connect(
                'changed::show-in-quick-settings',
                () => this._applyQuickSettingsSetting());
        }
        this._applyQuickSettingsSetting();

        this._dbus = Gio.DBusExportedObject.wrapJSObject(DBUS_INTERFACE, {
            // Grid
            Show: () => this._grid.show(),
            Hide: () => this._grid.hide(),
            Update: (x, y, width, height) => this._grid.update(x, y, width, height),

            // Mouse
            Click: (x, y) => this._grid.click(x, y),
            DoubleClick: (x, y) => this._grid.doubleClick(x, y),
            RightClick: (x, y) => this._grid.rightClick(x, y),
            MiddleClick: (x, y) => this._grid.middleClick(x, y),
            MoveTo: (x, y) => this._grid.moveTo(x, y),
            StartDrag: (x, y) => this._grid.startDrag(x, y),
            EndDrag: (x, y) => this._grid.endDrag(x, y),
            Scroll: (x, y, direction, clicks) => this._grid.scroll(x, y, direction, clicks),

            // Screenshot
            TakeScreenshot: () => this._screenMgr.takeScreenshotSync(),

            // Window management
            CloseWindow: () => this._winMgr.closeWindow(),
            MinimizeWindow: () => this._winMgr.minimizeWindow(),
            MaximizeWindow: () => this._winMgr.maximizeWindow(),
            UnmaximizeWindow: () => this._winMgr.unmaximizeWindow(),
            FullscreenWindow: () => this._winMgr.fullscreenWindow(),
            UnfullscreenWindow: () => this._winMgr.unfullscreenWindow(),
            TileLeft: () => this._winMgr.tileLeft(),
            TileRight: () => this._winMgr.tileRight(),

            // Window queries
            GetWindows: () => this._winMgr.getWindows(),
            FocusWindow: (title) => this._winMgr.focusWindow(title),

            // Workspaces
            SwitchWorkspace: (index) => this._winMgr.switchWorkspace(index),
            NextWorkspace: () => this._winMgr.nextWorkspace(),
            PrevWorkspace: () => this._winMgr.prevWorkspace(),
            GetWorkspaceCount: () => this._winMgr.getWorkspaceCount(),
            GetCurrentWorkspace: () => this._winMgr.getCurrentWorkspace(),

            // Screen info
            GetScreenSize: () => this._grid.getScreenSize(),

            // Panel indicator
            SetState: (state) => this._setState(state),
        });

        this._dbus.export(Gio.DBus.session, '/org/easyspeak/Desktop');
    }

    // Fan a daemon-pushed state out to both surfaces.
    _setState(state) {
        this._lastState = state;
        this._tray.setState(state, this._showInQuickSettings);
        this._quickSettings.setState(state);
    }

    // Show/hide the toggle and recompute the tray's visibility so the two never
    // show at once.
    _applyQuickSettingsSetting() {
        this._showInQuickSettings =
            this._settings?.get_boolean('show-in-quick-settings') ?? false;
        this._quickSettings.setVisible(this._showInQuickSettings);
        this._tray.setState(this._lastState, this._showInQuickSettings);
    }

    disable() {
        if (this._grid) {
            this._grid.hide();
            this._grid = null;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
        if (this._settings) {
            if (this._settingsChangedId)
                this._settings.disconnect(this._settingsChangedId);
            this._settings = null;
            this._settingsChangedId = null;
        }
        if (this._quickSettings) {
            this._quickSettings.quickSettingsItems.forEach((item) => item.destroy());
            this._quickSettings.destroy();
            this._quickSettings = null;
        }
        if (this._tray) {
            this._tray.destroy();
            this._tray = null;
        }
        this._winMgr = null;
        this._screenMgr = null;
    }
}
