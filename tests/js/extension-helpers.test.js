// Unit tests for the pure, gi-free helpers in extension-helpers.js.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    localToStageCoordinates,
    cycleMonitorIndex,
    resolveMonitorTarget,
    dragPath,
    clampToWorkArea,
    scrollDirectionDelta,
    gridGeometry,
    indicatorVisibleForState,
    quickSettingsCheckedForState,
    setAutostartEnabledInText,
    autostartEnabledFromText,
    pickAutostartSource,
    isPrefsWindow,
} from '../../src/gnome@easyspeak.dev/extension-helpers.js';

test('localToStageCoordinates returns local coordinates unchanged without a monitor', () => {
    assert.deepEqual(localToStageCoordinates(100, 200, null), { stageX: 100, stageY: 200 });
    assert.deepEqual(localToStageCoordinates(100, 200, undefined), { stageX: 100, stageY: 200 });
});

test('localToStageCoordinates translates local coordinates by monitor origin', () => {
    const laptop = { x: 0, y: 0, width: 1728, height: 1080 };
    const external = { x: 1728, y: 0, width: 2560, height: 1440 };

    assert.deepEqual(localToStageCoordinates(864, 540, laptop), { stageX: 864, stageY: 540 });
    assert.deepEqual(localToStageCoordinates(1280, 720, external), { stageX: 3008, stageY: 720 });
});

test('localToStageCoordinates rounds fractional coordinates and defaults missing offsets', () => {
    assert.deepEqual(localToStageCoordinates(10.4, 20.6, {}), { stageX: 10, stageY: 21 });
});

test('cycleMonitorIndex cycles between displays using modular arithmetic', () => {
    assert.equal(cycleMonitorIndex(0, 2), 1);
    assert.equal(cycleMonitorIndex(1, 2), 0);
    assert.equal(cycleMonitorIndex(0, 3), 1);
    assert.equal(cycleMonitorIndex(1, 3), 2);
    assert.equal(cycleMonitorIndex(2, 3), 0);
    assert.equal(cycleMonitorIndex(null, 2), 1);
    assert.equal(cycleMonitorIndex(0, 0), 0);
    assert.equal(cycleMonitorIndex(0, -1), 0);
});

test('resolveMonitorTarget resolves numeric indices clamped to range', () => {
    const monitors = [
        { index: 0, x: 0, y: 0, is_builtin: true, connector: 'eDP-1' },
        { index: 1, x: 1728, y: 0, is_builtin: false, connector: 'DP-1' },
    ];
    assert.equal(resolveMonitorTarget(monitors, 1, 0), 0);
    assert.equal(resolveMonitorTarget(monitors, 1, 1), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, 5), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, -2), 0);
    assert.equal(resolveMonitorTarget([], 0, 1), 0);
    assert.equal(resolveMonitorTarget(null, 0, 1), 0);
});

test('resolveMonitorTarget resolves primary and default keywords', () => {
    const monitors = [{ index: 0 }, { index: 1 }];
    assert.equal(resolveMonitorTarget(monitors, 1, 'primary'), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, 'default'), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, ''), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, null), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, undefined), 1);
    assert.equal(resolveMonitorTarget(monitors, -1, 'primary'), 0);
});

test('resolveMonitorTarget resolves external and secondary keywords', () => {
    const monitors = [{ index: 0 }, { index: 1 }];
    assert.equal(resolveMonitorTarget(monitors, 1, 'external'), 0);
    assert.equal(resolveMonitorTarget(monitors, 0, 'secondary'), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, 'other'), 0);
    // Single monitor fallback
    assert.equal(resolveMonitorTarget([{ index: 0 }], 0, 'external'), 0);
    assert.equal(resolveMonitorTarget([{ index: 0 }], -1, 'external'), 0);
});

test('resolveMonitorTarget resolves laptop and builtin keywords', () => {
    const monitors = [
        { index: 0, is_builtin: true },
        { index: 1, is_builtin: false },
    ];
    assert.equal(resolveMonitorTarget(monitors, 1, 'laptop'), 0);
    assert.equal(resolveMonitorTarget(monitors, 1, 'builtin'), 0);
    assert.equal(resolveMonitorTarget(monitors, 1, 'internal'), 0);

    // Fallback when is_builtin flag is absent: picks non-primary
    const noFlag = [{ index: 0 }, { index: 1 }];
    assert.equal(resolveMonitorTarget(noFlag, 1, 'laptop'), 0);
    assert.equal(resolveMonitorTarget([{ index: 0 }], 0, 'laptop'), 0);
});

test('resolveMonitorTarget parses string numbers and connector names', () => {
    const monitors = [
        { index: 0, connector: 'eDP-1' },
        { index: 1, connector: 'DP-1' },
    ];
    assert.equal(resolveMonitorTarget(monitors, 1, '0'), 0);
    assert.equal(resolveMonitorTarget(monitors, 0, '1'), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, 'dp-1'), 1);
    assert.equal(resolveMonitorTarget(monitors, 1, 'edp'), 0);
    assert.equal(resolveMonitorTarget(monitors, 1, 'unknown-display'), 1);
});

test('clampToWorkArea returns the rectangle unchanged without a work area', () => {
    assert.deepEqual(clampToWorkArea(10, 20, 30, 40, null), [10, 20, 30, 40]);
});

test('clampToWorkArea keeps a rectangle inside the work area', () => {
    const wa = { x: 0, y: 0, width: 1000, height: 800 };
    // Overflowing right/bottom: pinned so the far edge sits on the work area edge.
    assert.deepEqual(clampToWorkArea(950, 790, 100, 50, wa), [900, 750, 100, 50]);
    // Past the top-left origin: pinned to wa.x / wa.y.
    assert.deepEqual(clampToWorkArea(-30, -30, 100, 50, wa), [0, 0, 100, 50]);
    // Already inside: unchanged.
    assert.deepEqual(clampToWorkArea(100, 100, 100, 50, wa), [100, 100, 100, 50]);
});

test('clampToWorkArea respects a non-zero work area origin', () => {
    const wa = { x: 200, y: 100, width: 800, height: 600 };
    assert.deepEqual(clampToWorkArea(0, 0, 100, 50, wa), [200, 100, 100, 50]);
});

test('scrollDirectionDelta maps each direction to a unit delta', () => {
    assert.deepEqual(scrollDirectionDelta('up'), { dx: 0, dy: -1 });
    assert.deepEqual(scrollDirectionDelta('down'), { dx: 0, dy: 1 });
    assert.deepEqual(scrollDirectionDelta('left'), { dx: -1, dy: 0 });
    assert.deepEqual(scrollDirectionDelta('right'), { dx: 1, dy: 0 });
});

test('scrollDirectionDelta is a no-op for unknown directions', () => {
    assert.deepEqual(scrollDirectionDelta('sideways'), { dx: 0, dy: 0 });
    assert.deepEqual(scrollDirectionDelta(undefined), { dx: 0, dy: 0 });
});

test('scrollDirectionDelta scales by the amount argument', () => {
    assert.deepEqual(scrollDirectionDelta('down', 5), { dx: 0, dy: 5 });
    assert.deepEqual(scrollDirectionDelta('left', 3), { dx: -3, dy: 0 });
});

test('gridGeometry computes cells, font and crosshair for a 1920x1080 grid', () => {
    const g = gridGeometry(0, 0, 1920, 1080);
    assert.equal(g.cellW, 640);
    assert.equal(g.cellH, 360);
    assert.equal(g.fontSize, 72); // clamped to the 72px ceiling
    assert.equal(g.crossSize, 50); // clamped to the 50px ceiling
    assert.deepEqual(g.center, { x: 960, y: 540 });

    assert.equal(g.cells.length, 9);
    assert.deepEqual(g.cells[0], { num: 1, x: 284, y: 144 });
    assert.deepEqual(g.cells[4], { num: 5, x: 924, y: 504 });
    assert.deepEqual(g.cells[8], { num: 9, x: 1564, y: 864 });
});

test('gridGeometry offsets every coordinate by the bounds origin', () => {
    const base = gridGeometry(0, 0, 900, 600);
    const moved = gridGeometry(100, 50, 900, 600);
    assert.equal(moved.center.x, base.center.x + 100);
    assert.equal(moved.center.y, base.center.y + 50);
    assert.equal(moved.cells[0].x, base.cells[0].x + 100);
    assert.equal(moved.cells[0].y, base.cells[0].y + 50);
});

test('gridGeometry floors the font size for small grids', () => {
    // min(cellW, cellH)/3 below the 24px floor must clamp up to 24.
    const g = gridGeometry(0, 0, 120, 120);
    assert.equal(g.fontSize, 24);
});

test('indicatorVisibleForState shows the tray icon only when muted', () => {
    assert.equal(indicatorVisibleForState('muted'), true);
    for (const state of ['listening', 'active', 'thinking', '', undefined]) {
        assert.equal(indicatorVisibleForState(state), false);
    }
});

test('quickSettingsCheckedForState is on only while listening', () => {
    assert.equal(quickSettingsCheckedForState('listening'), true);
    for (const state of ['muted', 'active', 'thinking', '', undefined]) {
        assert.equal(quickSettingsCheckedForState(state), false);
    }
});

test('quickSettingsCheckedForState and indicatorVisibleForState never agree', () => {
    // The tray surfaces "asleep", the toggle surfaces "listening": for any state
    // at most one of the two is true, so they never both show at once.
    for (const state of ['listening', 'muted', 'active', 'thinking', '', undefined]) {
        assert.equal(
            quickSettingsCheckedForState(state) && indicatorVisibleForState(state),
            false,
        );
    }
});

test('setAutostartEnabledInText flips an existing flag, preserving other lines', () => {
    const src = '[Desktop Entry]\nName=EasySpeak\nIcon=audio-input-microphone\n' +
        'X-GNOME-Autostart-enabled=true\n';
    const out = setAutostartEnabledInText(src, false);
    assert.match(out, /^X-GNOME-Autostart-enabled=false$/m);
    assert.doesNotMatch(out, /enabled=true/);
    // Canonical fields carry over untouched, not re-authored.
    assert.match(out, /^Icon=audio-input-microphone$/m);
});

test('setAutostartEnabledInText flips a disabled flag back to enabled', () => {
    assert.match(
        setAutostartEnabledInText('X-GNOME-Autostart-enabled=false\n', true),
        /^X-GNOME-Autostart-enabled=true$/m);
});

test('setAutostartEnabledInText appends the flag when none is present', () => {
    const out = setAutostartEnabledInText('[Desktop Entry]\nExec=easyspeak\n', false);
    assert.match(out, /^Exec=easyspeak$/m);
    assert.match(out, /^X-GNOME-Autostart-enabled=false$/m);
});

test('setAutostartEnabledInText adds a newline before an appended flag', () => {
    // Source without a trailing newline must not run the flag onto the last line.
    const out = setAutostartEnabledInText('[Desktop Entry]', true);
    assert.match(out, /^\[Desktop Entry\]$/m);
    assert.match(out, /^X-GNOME-Autostart-enabled=true$/m);
});

test('setAutostartEnabledInText round-trips through autostartEnabledFromText', () => {
    const src = '[Desktop Entry]\nExec=easyspeak\n';
    assert.equal(autostartEnabledFromText(setAutostartEnabledInText(src, true)), true);
    assert.equal(autostartEnabledFromText(setAutostartEnabledInText(src, false)), false);
});

test('autostartEnabledFromText reads an explicit false as disabled', () => {
    assert.equal(autostartEnabledFromText('X-GNOME-Autostart-enabled=false\n'), false);
});

test('autostartEnabledFromText reads true (or any non-false) as enabled', () => {
    assert.equal(autostartEnabledFromText('X-GNOME-Autostart-enabled=true\n'), true);
});

test('autostartEnabledFromText treats a missing key as enabled', () => {
    assert.equal(autostartEnabledFromText('[Desktop Entry]\nExec=easyspeak\n'), true);
});

test('pickAutostartSource prefers the user entry over system and fallback', () => {
    assert.equal(pickAutostartSource('USER', ['SYS'], 'MIN'), 'USER');
});

test('pickAutostartSource falls back to the first present system entry', () => {
    assert.equal(pickAutostartSource(null, [null, 'SYS', 'OTHER'], 'MIN'), 'SYS');
});

test('pickAutostartSource uses the fallback when nothing is installed', () => {
    assert.equal(pickAutostartSource(null, [null, null], 'MIN'), 'MIN');
    assert.equal(pickAutostartSource(null, [], 'MIN'), 'MIN');
});

test('dragPath ends exactly on the target', () => {
    const path = dragPath(100, 100, 400, 200, 24);
    assert.equal(path.length, 24);
    assert.deepEqual(path.at(-1), { x: 400, y: 200 });
});

test('dragPath never emits the press point itself', () => {
    // The press already happened there; re-sending it is a wasted event.
    const path = dragPath(50, 50, 250, 50, 12);
    assert.notDeepEqual(path[0], { x: 50, y: 50 });
});

test('dragPath eases in, so early motion stays near the source', () => {
    const path = dragPath(0, 0, 1000, 0, 20);
    // A tenth of the way through the steps, well under a tenth of the distance.
    assert.ok(path[1].x < 100, `expected an eased start, got ${path[1].x}`);
});

test('dragPath crosses the GTK drag threshold within a few steps', () => {
    // GTK starts a drag only after 8px of travel; a path that creeps below that
    // for too long never becomes a drag at all.
    const path = dragPath(0, 0, 200, 0, 24);
    const crossed = path.findIndex((point) => Math.abs(point.x) > 8);
    assert.ok(crossed >= 0 && crossed < 6, `threshold crossed at step ${crossed}`);
});

test('dragPath moves monotonically toward the target', () => {
    const path = dragPath(0, 0, 300, 150, 16);
    for (let i = 1; i < path.length; i++) {
        assert.ok(path[i].x >= path[i - 1].x);
        assert.ok(path[i].y >= path[i - 1].y);
    }
});

test('dragPath handles a backwards drag', () => {
    const path = dragPath(400, 300, 100, 50, 10);
    assert.deepEqual(path.at(-1), { x: 100, y: 50 });
    assert.ok(path[0].x < 400 && path[0].y < 300);
});

test('isPrefsWindow recognises the shell-hosted prefs dialog by app id and title', () => {
    assert.equal(isPrefsWindow('EasySpeak', 'org.gnome.Shell.Extensions', 'EasySpeak'), true);
});

test('isPrefsWindow ignores other windows named after the extension', () => {
    // A terminal or a browser tab titled like the project is not the dialog.
    assert.equal(isPrefsWindow('EasySpeak', 'com.mitchellh.ghostty', 'EasySpeak'), false);
    assert.equal(isPrefsWindow('EasySpeak - Brave', 'brave-browser', 'EasySpeak'), false);
});

test("isPrefsWindow ignores another extension's prefs dialog", () => {
    assert.equal(isPrefsWindow('GSConnect', 'org.gnome.Shell.Extensions', 'EasySpeak'), false);
});

test('isPrefsWindow copes with a window that has no title or class yet', () => {
    assert.equal(isPrefsWindow(null, null, 'EasySpeak'), false);
});
