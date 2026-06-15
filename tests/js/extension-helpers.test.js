// Unit tests for the pure, gi-free helpers in extension-helpers.js.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    clampToWorkArea,
    scrollDirectionDelta,
    gridGeometry,
    indicatorVisibleForState,
} from '../../src/extension-helpers.js';

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
