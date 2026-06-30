// Grid overlay primitive: draws the numbered navigation grid and injects
// pointer input (move, click, drag, scroll) through the compositor's virtual
// device. Where to click and which cell to pick is decided by Python plugins;
// this module only exposes the generic primitives.

import St from 'gi://St';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {
    clampToWorkArea,
    scrollDirectionDelta,
    gridGeometry,
} from './extension-helpers.js';

export class GridOverlay {
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

    show() {
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
