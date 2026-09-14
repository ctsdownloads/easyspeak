// Contract test: every Settings entry (tray menu and Quick Settings) reaches
// the prefs dialog through the one path that raises an open dialog first.
//
// GNOME Shell allows a single prefs dialog and refuses to open a second one, so
// an entry that called openPreferences() directly would do nothing while the
// dialog sits behind other windows. Like dbus-contract.test.js this reads the
// gi-bound sources as text, since they only load inside a running shell.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const extensionDir = new URL('../../src/gnome@easyspeak.dev/', import.meta.url);
const extension = readFileSync(new URL('extension.js', extensionDir), 'utf8');
const indicator = readFileSync(new URL('indicator.js', extensionDir), 'utf8');

test('both surfaces are handed the raise-or-open path', () => {
    assert.match(extension, /new TrayIndicator\(\(\) => this\._showPreferences\(\)\)/);
    assert.match(extension, /new EasySpeakQuickSettings\(\(\) => this\._showPreferences\(\)\)/);
});

test('the shell\'s openPreferences is called only as the fallback of that path', () => {
    const calls = extension.match(/this\.openPreferences\(\)/g) ?? [];
    assert.equal(calls.length, 1, 'openPreferences() must be called in one place');

    const body = /_showPreferences\(\) \{([\s\S]*?)\n    \}/.exec(extension)?.[1];
    assert.ok(body, 'could not locate _showPreferences()');
    assert.match(body, /isPrefsWindow\(/);
    assert.match(body, /Main\.activateWindow\(/);
    assert.match(body, /this\.openPreferences\(\)/);
});

test('the surfaces never open the dialog on their own', () => {
    assert.doesNotMatch(indicator, /openPreferences\(\)\s*\{|extensionManager|openExtensionPrefs/);
});
