# JavaScript tests

Node's built-in test runner (`node --test`, needs node >= 22.5) exercises
the GNOME Shell extension's JS without a running shell. Anything touching the
`gi://` imports only resolves inside a live session, so these cover the two
slices that don't need one: the pure helper computation, and the D-Bus
interface treated as plain text.

`extension-helpers.test.js` imports the gi-free `extension-helpers.js`
module directly. `dbus-contract.test.js` can't import `extension.js` (its
top-level `gi://` imports only resolve inside the shell), so it reads the
file as text and parses the interface XML against the wired handlers — this
catches the "added the method to the XML but forgot to implement it" drift
(or the reverse) without a running `gnome-shell`.

## How they run

```sh
just test-js        # node --test with coverage thresholds (lines/branches/functions >= 99)
just test-js -v     # extra node args pass through
just lint-js        # eslint over the extension sources (--fix to autocorrect)
```

## Layout

```sh
extension-helpers.test.js  # unit tests for the pure, gi-free helpers in extension-helpers.js
dbus-contract.test.js      # contract: every D-Bus method in the XML has a handler, and vice versa
```
