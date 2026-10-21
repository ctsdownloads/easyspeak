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
    dragPath,
} from './extension-helpers.js';

// A drag is a journey, not a jump. GTK begins one only after the pointer travels
// past its threshold with the button held, and picks a drop target from where the
// pointer comes to rest, so a press, a single teleport and an immediate release
// read as a plain click and drop nothing. The travel is
// spread over real time via timeouts, because the application on the other side
// has to run its own main loop to process each motion.
const DRAG_STEPS = 24;
const DRAG_STEP_MS = 12;
const DRAG_SETTLE_MS = 200;

export class GridOverlay {
    constructor() {
        this.container = null;
        this.bounds = [0, 0, 1920, 1080];
        this.screenW = 1920;
        this.screenH = 1080;
        this.workArea = null;
        this._pointer = null;
        this._dragging = false;
        this._dragOrigin = null;
        this._dragTimer = null;
        this._dropTimer = null;
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
        this._cancelDragTimers();
        const pointer = this._getPointer();
        pointer.notify_absolute_motion(GLib.get_monotonic_time(), x, y);
        pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY,
            Clutter.ButtonState.PRESSED);
        // Remembered so the release can travel here from there, rather than
        // teleporting straight to the drop point.
        this._dragOrigin = [x, y];
        this._dragging = true;
    }

    endDrag(x, y) {
        if (!this._dragging) return;
        this.hide();
        this._cancelDragTimers();

        const [sx, sy] = this._dragOrigin ?? [x, y];
        const path = dragPath(sx, sy, x, y, DRAG_STEPS);
        const pointer = this._getPointer();
        let step = 0;

        this._dragTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, DRAG_STEP_MS, () => {
            pointer.notify_absolute_motion(GLib.get_monotonic_time(),
                path[step].x, path[step].y);
            step++;
            if (step < path.length) return GLib.SOURCE_CONTINUE;

            this._dragTimer = null;
            // Rest on the target before letting go: the drop site needs a moment
            // to recognise the pointer and accept, and a release in the same
            // millisecond as the last motion gives it none.
            this._dropTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, DRAG_SETTLE_MS, () => {
                this._dropTimer = null;
                this._releaseDragButton();
                return GLib.SOURCE_REMOVE;
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    // Let go of the primary button and forget the drag.
    _releaseDragButton() {
        const pointer = this._getPointer();
        pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY,
            Clutter.ButtonState.RELEASED);
        this._dragging = false;
        this._dragOrigin = null;
    }

    _cancelDragTimers() {
        for (const name of ['_dragTimer', '_dropTimer']) {
            if (this[name]) {
                GLib.Source.remove(this[name]);
                this[name] = null;
            }
        }
    }

    // Abandon any drag at once, button up. Called when the extension is disabled
    // so a half-finished drag can never leave the button held compositor-wide.
    abortDrag() {
        this._cancelDragTimers();
        if (this._dragging) this._releaseDragButton();
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

        this.container.add_child(new St.Widget({
            style: 'background-color: rgba(0,0,0,0.15);',
            x: bx, y: by, width: bw, height: bh
        }));

        const { cellW, cellH, fontSize, cells, center, crossSize } =
            gridGeometry(bx, by, bw, bh);

        for (let i = 1; i < 3; i++) {
            this.container.add_child(new St.Widget({
                style: 'background-color: rgba(255,255,255,0.8);',
                x: bx + i * cellW - 1, y: by, width: 3, height: bh
            }));
        }

        for (let i = 1; i < 3; i++) {
            this.container.add_child(new St.Widget({
                style: 'background-color: rgba(255,255,255,0.8);',
                x: bx, y: by + i * cellH - 1, width: bw, height: 3
            }));
        }

        for (const cell of cells) {
            const label = new St.Label({
                text: String(cell.num),
                style: `font-size: ${fontSize}px; font-weight: bold; color: #ffe600; ` +
                    `background-color: rgba(0,0,0,0.8); border-radius: 8px; padding: 8px 16px;`
            });

            label.set_position(cell.x, cell.y);
            this.container.add_child(label);
        }

        const centerX = center.x;
        const centerY = center.y;
        const crossThick = 4;

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
