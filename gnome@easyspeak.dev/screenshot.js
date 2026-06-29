// Screen capture primitive. On Wayland only the compositor can grab the
// framebuffer, so capture lives here; OCR and any image post-processing are
// done by Python plugins that read the file this writes.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export class ScreenshotManager {
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
        } catch {}

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
            await screenshot.screenshot_area(x, y, width, height, stream, false);

            stream.close(null);
            log('EasySpeak: screenshot saved to ' + this._path);

        } catch (e) {
            log('EasySpeak: capture error: ' + e.message);
            log('EasySpeak: stack: ' + e.stack);
        }
    }
}
