// Contract test: every D-Bus method in extension.js's XML has a handler,
// and vice versa.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../src/gnome@easyspeak.dev/extension.js', import.meta.url), 'utf8');

// Method names declared in the <interface> XML.
function declaredMethods(src) {
    return new Set([...src.matchAll(/<method name="(\w+)"/g)].map((m) => m[1]));
}

// Handler keys in the object literal passed to wrapJSObject(DBUS_INTERFACE, {...}).
function wiredHandlers(src) {
    // Tolerate incidental whitespace/newlines between the call's tokens so a
    // reformat (e.g. prettier wrapping the args) doesn't break the contract test.
    const match = /wrapJSObject\(\s*DBUS_INTERFACE\s*,\s*\{/.exec(src);
    assert.notEqual(match, null, 'could not locate the wrapJSObject handler map');

    // Walk braces from the map's opening `{` (the last char the regex matched)
    // to its matching `}`.
    const open = match.index + match[0].length - 1;
    let depth = 0;
    let end = -1;
    for (let i = open; i < src.length; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') {
            depth--;
            if (depth === 0) {
                end = i;
                break;
            }
        }
    }
    assert.notEqual(end, -1, 'unbalanced braces in the handler map');

    const block = src.slice(open + 1, end);
    // Each handler is `Name: (args) => ...` at the start of a line.
    return new Set([...block.matchAll(/^\s*(\w+):\s*\(/gm)].map((m) => m[1]));
}

test('every declared D-Bus method has a handler and vice versa', () => {
    const methods = declaredMethods(source);
    const handlers = wiredHandlers(source);

    assert.ok(methods.size > 0, 'no D-Bus methods found in the interface XML');

    const missingHandlers = [...methods].filter((m) => !handlers.has(m)).sort();
    const orphanHandlers = [...handlers].filter((h) => !methods.has(h)).sort();

    assert.deepEqual(
        missingHandlers,
        [],
        `D-Bus methods declared in XML but not wired in enable(): ${missingHandlers.join(', ')}`,
    );
    assert.deepEqual(
        orphanHandlers,
        [],
        `handlers in enable() with no matching XML method: ${orphanHandlers.join(', ')}`,
    );
});
