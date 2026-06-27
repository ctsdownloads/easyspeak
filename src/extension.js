import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Clutter from 'gi://Clutter';
import Shell from 'gi://Shell';
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import {
    clampToWorkArea,
    scrollDirectionDelta,
    gridGeometry,
    indicatorVisibleForState,
    quickSettingsCheckedForState,
} from './extension-helpers.js';

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

class GridOverlay {
    constructor() {
        this.container = null;
        this.bounds = [0, 0, 1920, 1080];
        this.screenW = 1920;
        this.screenH = 1080;
        this.workArea = null;
        this._pointer = null;
        this._dragging = false;
    }

    _getPointer() {
        if (!this._pointer) {
            const seat = Clutter.get_default_backend().get_default_seat();
            this._pointer = seat.create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
        }
        return this._pointer;
    }

    _clampToWorkArea(x, y, w, h) {
        return clampToWorkArea(x, y, w, h, this.workArea);
    }

    show(width, height) {
        if (this.container) this.hide();

        const monitor = Main.layoutManager.primaryMonitor;
        // Use monitor's actual dimensions, ignore what Python sends
        this.screenW = monitor.width;
        this.screenH = monitor.height;
        
        this.bounds = [0, 0, this.screenW, this.screenH];

        this.container = new St.Widget({
            reactive: false,
            x: monitor.x,
            y: monitor.y,
            width: this.screenW,
            height: this.screenH,
        });

        this._draw();
        Main.uiGroup.add_child(this.container);
        
        log(`EasySpeak: Grid shown ${this.screenW}x${this.screenH} at (${monitor.x},${monitor.y})`);
    }

    getScreenSize() {
        const monitor = Main.layoutManager.primaryMonitor;
        return [monitor.width, monitor.height];
    }

    hide() {
        if (this.container) {
            this.container.destroy();
            this.container = null;
        }
    }

    update(x, y, width, height) {
        if (!this.container) return;
        this.bounds = [x, y, width, height];
        this._draw();
    }

    click(x, y) {
        this.hide();
        const pointer = this._getPointer();
        const t = GLib.get_monotonic_time();
        pointer.notify_absolute_motion(t, x, y);
        pointer.notify_button(t + 5000, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        pointer.notify_button(t + 10000, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
    }

    doubleClick(x, y) {
        this.hide();
        const pointer = this._getPointer();
        const t = GLib.get_monotonic_time();
        pointer.notify_absolute_motion(t, x, y);
        pointer.notify_button(t + 5000, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        pointer.notify_button(t + 10000, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
        pointer.notify_button(t + 60000, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        pointer.notify_button(t + 65000, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
    }

    rightClick(x, y) {
        this.hide();
        const pointer = this._getPointer();
        const t = GLib.get_monotonic_time();
        pointer.notify_absolute_motion(t, x, y);
        pointer.notify_button(t + 5000, Clutter.BUTTON_SECONDARY, Clutter.ButtonState.PRESSED);
        pointer.notify_button(t + 10000, Clutter.BUTTON_SECONDARY, Clutter.ButtonState.RELEASED);
    }

    middleClick(x, y) {
        this.hide();
        const pointer = this._getPointer();
        const t = GLib.get_monotonic_time();
        pointer.notify_absolute_motion(t, x, y);
        pointer.notify_button(t + 5000, Clutter.BUTTON_MIDDLE, Clutter.ButtonState.PRESSED);
        pointer.notify_button(t + 10000, Clutter.BUTTON_MIDDLE, Clutter.ButtonState.RELEASED);
    }

    moveTo(x, y) {
        const pointer = this._getPointer();
        pointer.notify_absolute_motion(GLib.get_monotonic_time(), x, y);
    }

    startDrag(x, y) {
        // Keep grid visible so user can navigate to end point
        const pointer = this._getPointer();
        const t = GLib.get_monotonic_time();
        pointer.notify_absolute_motion(t, x, y);
        pointer.notify_button(t + 5000, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        this._dragging = true;
    }

    endDrag(x, y) {
        if (!this._dragging) return;
        this.hide();
        const pointer = this._getPointer();
        const t = GLib.get_monotonic_time();
        pointer.notify_absolute_motion(t, x, y);
        pointer.notify_button(t + 5000, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
        this._dragging = false;
    }

    scroll(x, y, direction, clicks) {
        this.hide();
        const pointer = this._getPointer();
        const t = GLib.get_monotonic_time();
        pointer.notify_absolute_motion(t, x, y);

        const { dx, dy } = scrollDirectionDelta(direction);

        for (let i = 0; i < clicks; i++) {
            pointer.notify_scroll_continuous(t + (i * 50000), dx, dy,
                Clutter.ScrollSource.FINGER, Clutter.ScrollFinishFlags.NONE);
        }
    }

    _draw() {
        this.container.destroy_all_children();
        const [bx, by, bw, bh] = this.bounds;

        // Semi-transparent background
        this.container.add_child(new St.Widget({
            style: 'background-color: rgba(0,0,0,0.15);',
            x: bx, y: by, width: bw, height: bh
        }));

        // Grid lines and labels
        const { cellW, cellH, fontSize, cells, center, crossSize } =
            gridGeometry(bx, by, bw, bh);

        // Vertical lines
        for (let i = 1; i < 3; i++) {
            this.container.add_child(new St.Widget({
                style: 'background-color: rgba(255,255,255,0.8);',
                x: bx + i * cellW - 1, y: by, width: 3, height: bh
            }));
        }

        // Horizontal lines
        for (let i = 1; i < 3; i++) {
            this.container.add_child(new St.Widget({
                style: 'background-color: rgba(255,255,255,0.8);',
                x: bx, y: by + i * cellH - 1, width: bw, height: 3
            }));
        }

        // Number labels 1-9
        for (const cell of cells) {
            const label = new St.Label({
                text: String(cell.num),
                style: `font-size: ${fontSize}px; font-weight: bold; color: #ffe600; ` +
                    `background-color: rgba(0,0,0,0.8); border-radius: 8px; padding: 8px 16px;`
            });

            label.set_position(cell.x, cell.y);
            this.container.add_child(label);
        }

        // Crosshair at center
        const centerX = center.x;
        const centerY = center.y;
        const crossThick = 4;

        // White outline
        this.container.add_child(new St.Widget({
            style: 'background-color: #ffffff;',
            x: centerX - crossSize / 2 - 2, y: centerY - crossThick / 2 - 2,
            width: crossSize + 4, height: crossThick + 4
        }));
        this.container.add_child(new St.Widget({
            style: 'background-color: #ffffff;',
            x: centerX - crossThick / 2 - 2, y: centerY - crossSize / 2 - 2,
            width: crossThick + 4, height: crossSize + 4
        }));

        // Red cross
        this.container.add_child(new St.Widget({
            style: 'background-color: #ff0000;',
            x: centerX - crossSize / 2, y: centerY - crossThick / 2,
            width: crossSize, height: crossThick
        }));
        this.container.add_child(new St.Widget({
            style: 'background-color: #ff0000;',
            x: centerX - crossThick / 2, y: centerY - crossSize / 2,
            width: crossThick, height: crossSize
        }));
    }
}

class WindowManager {
    _getFocusedWindow() {
        return global.display.focus_window;
    }

    closeWindow() {
        const win = this._getFocusedWindow();
        if (win) win.delete(global.get_current_time());
    }

    minimizeWindow() {
        const win = this._getFocusedWindow();
        if (win) win.minimize();
    }

    maximizeWindow() {
        const win = this._getFocusedWindow();
        if (win) win.maximize(Meta.MaximizeFlags.BOTH);
    }

    unmaximizeWindow() {
        const win = this._getFocusedWindow();
        if (win) win.unmaximize(Meta.MaximizeFlags.BOTH);
    }

    fullscreenWindow() {
        const win = this._getFocusedWindow();
        if (win) win.make_fullscreen();
    }

    unfullscreenWindow() {
        const win = this._getFocusedWindow();
        if (win) win.unmake_fullscreen();
    }

    tileLeft() {
        const win = this._getFocusedWindow();
        if (!win) return;
        
        const monitor = win.get_monitor();
        const workArea = Main.layoutManager.getWorkAreaForMonitor(monitor);
        
        win.unmaximize(Meta.MaximizeFlags.BOTH);
        win.move_resize_frame(
            false,
            workArea.x,
            workArea.y,
            Math.floor(workArea.width / 2),
            workArea.height
        );
    }

    tileRight() {
        const win = this._getFocusedWindow();
        if (!win) return;
        
        const monitor = win.get_monitor();
        const workArea = Main.layoutManager.getWorkAreaForMonitor(monitor);
        
        win.unmaximize(Meta.MaximizeFlags.BOTH);
        win.move_resize_frame(
            false,
            workArea.x + Math.floor(workArea.width / 2),
            workArea.y,
            Math.floor(workArea.width / 2),
            workArea.height
        );
    }

    getWindows() {
        const windows = global.get_window_actors().map(actor => {
            const win = actor.get_meta_window();
            if (!win || win.get_window_type() !== Meta.WindowType.NORMAL) return null;
            return {
                id: win.get_id(),
                title: win.get_title(),
                wm_class: win.get_wm_class(),
                workspace: win.get_workspace()?.index() ?? -1,
                focused: win === this._getFocusedWindow()
            };
        }).filter(w => w !== null);
        
        return JSON.stringify(windows);
    }

    focusWindow(titleSubstring) {
        const lowerTitle = titleSubstring.toLowerCase();
        const actors = global.get_window_actors();
        
        for (const actor of actors) {
            const win = actor.get_meta_window();
            if (!win || win.get_window_type() !== Meta.WindowType.NORMAL) continue;
            
            const title = win.get_title()?.toLowerCase() || '';
            const wmClass = win.get_wm_class()?.toLowerCase() || '';
            
            if (title.includes(lowerTitle) || wmClass.includes(lowerTitle)) {
                win.activate(global.get_current_time());
                return true;
            }
        }
        return false;
    }

    switchWorkspace(index) {
        const workspaceManager = global.workspace_manager;
        const ws = workspaceManager.get_workspace_by_index(index);
        if (ws) ws.activate(global.get_current_time());
    }

    nextWorkspace() {
        const workspaceManager = global.workspace_manager;
        const current = workspaceManager.get_active_workspace_index();
        const next = Math.min(current + 1, workspaceManager.get_n_workspaces() - 1);
        this.switchWorkspace(next);
    }

    prevWorkspace() {
        const workspaceManager = global.workspace_manager;
        const current = workspaceManager.get_active_workspace_index();
        const prev = Math.max(current - 1, 0);
        this.switchWorkspace(prev);
    }

    getWorkspaceCount() {
        return global.workspace_manager.get_n_workspaces();
    }

    getCurrentWorkspace() {
        return global.workspace_manager.get_active_workspace_index();
    }
}

class ScreenshotManager {
    constructor() {
        this._cacheDir = GLib.get_home_dir() + '/.cache/easyspeak';
        this._path = this._cacheDir + '/screen.png';
        this._ensureCacheDir();
    }

    _ensureCacheDir() {
        const dir = Gio.File.new_for_path(this._cacheDir);
        if (!dir.query_exists(null)) {
            dir.make_directory_with_parents(null);
        }
    }

    takeScreenshotSync() {
        // Delete old file first
        try {
            Gio.File.new_for_path(this._path).delete(null);
        } catch (e) {}
        
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._captureViaScreenshotClass();
            return GLib.SOURCE_REMOVE;
        });
        
        return this._path;
    }
    
    async _captureViaScreenshotClass() {
        try {
            const screenshot = new Shell.Screenshot();
            
            // Get primary monitor dimensions
            const monitor = Main.layoutManager.primaryMonitor;
            const x = monitor.x;
            const y = monitor.y;
            const width = monitor.width;
            const height = monitor.height;
            
            log('EasySpeak: capturing area ' + x + ',' + y + ' ' + width + 'x' + height);
            
            // Create output file stream
            const file = Gio.File.new_for_path(this._path);
            const stream = file.replace(null, false, Gio.FileCreateFlags.NONE, null);
            
            // GNOME 48: screenshot_area(x, y, width, height, stream, flash)
            const [content, scale] = await screenshot.screenshot_area(x, y, width, height, stream, false);
            
            stream.close(null);
            log('EasySpeak: screenshot saved to ' + this._path);
            
        } catch (e) {
            log('EasySpeak: capture error: ' + e.message);
            log('EasySpeak: stack: ' + e.stack);
        }
    }
}

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
const TrayIndicator = GObject.registerClass(
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

const EasySpeakQuickSettings = GObject.registerClass(
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
            Show: (width, height) => this._grid.show(width, height),
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
