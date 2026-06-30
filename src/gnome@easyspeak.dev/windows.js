// Window and workspace operations on the focused window. These are
// compositor-only on Wayland: only the shell can move, tile, close, or switch
// other windows. Which window, and why, is decided by Python plugins.

import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export class WindowManager {
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
