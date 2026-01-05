import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import Shell from 'gi://Shell';
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const DBUS_INTERFACE = `
<node>
  <interface name="org.easyspeak.Grid">
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
        if (!this.workArea) return [x, y, w, h];
        const wa = this.workArea;
        let newX = Math.max(wa.x, Math.min(x, wa.x + wa.width - w));
        let newY = Math.max(wa.y, Math.min(y, wa.y + wa.height - h));
        return [newX, newY, w, h];
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

        let dx = 0, dy = 0;
        const scrollAmount = 1;
        switch (direction) {
            case 'up': dy = -scrollAmount; break;
            case 'down': dy = scrollAmount; break;
            case 'left': dx = -scrollAmount; break;
            case 'right': dx = scrollAmount; break;
        }

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
        const cellW = Math.floor(bw / 3);
        const cellH = Math.floor(bh / 3);

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
        const fontSize = Math.max(24, Math.min(72, Math.floor(Math.min(cellW, cellH) / 3)));
        for (let num = 1; num <= 9; num++) {
            const row = Math.floor((num - 1) / 3);
            const col = (num - 1) % 3;
            const zoneX = bx + col * cellW;
            const zoneY = by + row * cellH;

            const label = new St.Label({
                text: String(num),
                style: `font-size: ${fontSize}px; font-weight: bold; color: #ffe600; ` +
                    `background-color: rgba(0,0,0,0.8); border-radius: 8px; padding: 8px 16px;`
            });

            label.set_position(zoneX + cellW / 2 - fontSize / 2, zoneY + cellH / 2 - fontSize / 2);
            this.container.add_child(label);
        }

        // Crosshair at center
        const centerX = bx + Math.floor(bw / 2);
        const centerY = by + Math.floor(bh / 2);
        const crossSize = Math.min(50, Math.floor(Math.min(bw, bh) / 3));
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

export default class EasySpeakGridExtension {
    constructor() {
        this._dbus = null;
        this._grid = null;
        this._winMgr = null;
        this._screenMgr = null;
    }

    enable() {
        this._grid = new GridOverlay();
        this._winMgr = new WindowManager();
        this._screenMgr = new ScreenshotManager();

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
        });

        this._dbus.export(Gio.DBus.session, '/org/easyspeak/Grid');
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
        this._winMgr = null;
        this._screenMgr = null;
    }
}
