// Pure helpers for the GNOME Shell extension.
//
// Everything here is deliberately free of `gi://` / GNOME Shell imports so it
// can be unit-tested with `node --test` outside a running shell (the rest of
// extension.js can only run inside gnome-shell). Keep this file dependency-free.

// Clamp a rectangle so it stays inside the work area. Mirrors the inverse-of-
// nothing identity when there is no work area (e.g. before the grid is shown).
export function clampToWorkArea(x, y, w, h, workArea) {
    if (!workArea) return [x, y, w, h];
    const wa = workArea;
    const newX = Math.max(wa.x, Math.min(x, wa.x + wa.width - w));
    const newY = Math.max(wa.y, Math.min(y, wa.y + wa.height - h));
    return [newX, newY, w, h];
}

// Map a scroll direction to a continuous-scroll delta. Unknown directions are a
// no-op (zero delta) rather than an error.
export function scrollDirectionDelta(direction, amount = 1) {
    switch (direction) {
        case 'up': return { dx: 0, dy: -amount };
        case 'down': return { dx: 0, dy: amount };
        case 'left': return { dx: -amount, dy: 0 };
        case 'right': return { dx: amount, dy: 0 };
        default: return { dx: 0, dy: 0 };
    }
}

// Compute the numeric layout of the 3x3 navigation grid for a bounds rectangle:
// cell size, label font size, the top-left position of each numbered label, and
// the centre crosshair. The drawing code consumes these to place actors.
export function gridGeometry(bx, by, bw, bh) {
    const cellW = Math.floor(bw / 3);
    const cellH = Math.floor(bh / 3);
    const fontSize = Math.max(24, Math.min(72, Math.floor(Math.min(cellW, cellH) / 3)));

    const cells = [];
    for (let num = 1; num <= 9; num++) {
        const row = Math.floor((num - 1) / 3);
        const col = (num - 1) % 3;
        const zoneX = bx + col * cellW;
        const zoneY = by + row * cellH;
        cells.push({
            num,
            x: zoneX + cellW / 2 - fontSize / 2,
            y: zoneY + cellH / 2 - fontSize / 2,
        });
    }

    const center = { x: bx + Math.floor(bw / 2), y: by + Math.floor(bh / 2) };
    const crossSize = Math.min(50, Math.floor(Math.min(bw, bh) / 3));

    return { cellW, cellH, fontSize, cells, center, crossSize };
}

// The tray indicator is shown only while EasySpeak is deactivated ("muted").
// Every running state (listening/active/thinking) hides it.
export function indicatorVisibleForState(state) {
    return state === 'muted';
}

// Whether the Quick Settings toggle should read as "on" for a given daemon
// state: on while EasySpeak is listening, off while it's asleep ("muted") or in
// any other non-listening state. The inverse of the tray's visibility rule — the
// tray surfaces the asleep state, the toggle surfaces the listening one.
export function quickSettingsCheckedForState(state) {
    return state === 'listening';
}

// Set the X-GNOME-Autostart-enabled flag in a .desktop file's text to the given
// state, returning the new text and leaving every other line untouched. The
// per-user ~/.config/autostart/easyspeak.desktop is derived this way from the
// canonical entry (data/easyspeak-autostart.desktop, installed to the user dir
// or /etc/xdg/autostart), so the content lives in one place; written with the
// flag false it overrides a packaged entry — the way gnome-tweaks disables one.
export function setAutostartEnabledInText(text, enabled) {
    const line = `X-GNOME-Autostart-enabled=${enabled ? 'true' : 'false'}`;
    const flag = /^X-GNOME-Autostart-enabled\s*=.*$/m;
    if (flag.test(text)) {
        return text.replace(flag, line);
    }
    // No flag yet: append it as the last key of the (single) [Desktop Entry].
    return (text.endsWith('\n') ? text : text + '\n') + line + '\n';
}

// Read the autostart-enabled flag from a .desktop file's text. A missing key
// counts as enabled: the file's presence means autostart unless it's explicitly
// turned off with X-GNOME-Autostart-enabled=false.
export function autostartEnabledFromText(text) {
    const match = text.match(/^X-GNOME-Autostart-enabled\s*=\s*(\S+)/m);
    return match ? match[1].toLowerCase() !== 'false' : true;
}

// Choose the text the per-user autostart override is built from. The user's own
// entry wins, so a hand-edited file is preserved; otherwise the first packaged
// system entry found (whose Comment/Icon/… then carry over); otherwise the
// minimal fallback. `userText` and each `systemTexts` entry are a file's text,
// or null when it is absent or unreadable.
export function pickAutostartSource(userText, systemTexts, fallback) {
    return userText ?? systemTexts.find((text) => text != null) ?? fallback;
}
