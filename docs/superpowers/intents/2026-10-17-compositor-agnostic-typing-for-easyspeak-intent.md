# Intent: Compositor-agnostic key injection for EasySpeak

Author: Elifarley (with Claude Code). Status: draft.

## Problem

Every keystroke EasySpeak injects rides `org.gnome.Mutter.RemoteDesktop`
(`src/core/mediakeys.py`), a Mutter-only D-Bus API. Off GNOME this single
dependency breaks three features at once:

- **Dictation** transcribes and puts text on the clipboard, but the synthetic
  paste chord fails (`RemoteDesktopUnavailableError`), so the user hears
  "I can't type on this desktop yet…" and pastes by hand. Keystroke commands
  (backspace×N, enter, tab) are refused outright ("Dictation isn't set up on
  this system.").
- **Browser mode** "press enter"-style keystrokes are documented
  GNOME-only (docs/compatibility.md [^browser]).
- **System/media-key replay** (voice "volume up") is unavailable, so the
  desktop's own OSD never renders; the system plugin falls back to silent
  direct control (compatibility table: ⚠️ "without the on-screen indicator").

Verified live on the `easyspeak-cosmic` VM (Pop!_OS 24.04 / COSMIC):
`org.gnome.Mutter.RemoteDesktop` is unowned and `tap_chord` raises
`RemoteDesktopUnavailableError: The name is not activatable`.

PR easyspeak#233 adds a compositor-independent injection backend
(uinput via ydotool, capability-gated, verified in the same VM), but it lives
only inside `src/plugins/mousegrid/_ydotool.py`, serving the mouse grid alone.

## Proposed outcome

One capability-gated injection path in core, serving all three consumers:

- Backends: Mutter RemoteDesktop when the session provides it (GNOME — byte
  for byte today's behavior), else the ydotool/uinput plumbing extracted from
  #233's `_ydotool` once it merges.
- `plugins/dictation` (paste chord + keystroke commands), `plugins/browser`
  (press-key), and `plugins/system` (media-key replay) all route through it.
  On COSMIC/KDE, a ydotool-injected volume key is a real input event, so the
  desktop renders its OWN native OSD — the same fidelity goal the replay path
  was built for.
- Packaging (deb/rpm) gains `wl-clipboard` + `ydotool` so the clipboard leg
  and the backend exist out of the box (wl-clipboard is missing on our COSMIC
  VM today).
- Off GNOME, the AT-SPI focus probe falls open: when it cannot see a focused
  field on a non-GNOME session, dictation proceeds with the clipboard path
  instead of refusing ("No text field focused").
- docs/compatibility.md gains a COSMIC column reflecting verified reality.

Strategy: stacked follow-up PR — #233 merges first, focused as the maintainer
requested; this PR then extracts/shares its plumbing. GNOME behavior:
zero change.

## Affected users and systems

- Users on COSMIC (Pop!_OS 24.04, Fedora COSMIC Spin) and KDE Plasma: dictation,
  browser keystrokes, and native media feedback become usable.
- GNOME users: no behavior change (regression gate).
- Code: `src/core/mediakeys.py` (becomes the gated injector or is superseded by
  a core module), `src/plugins/{dictation,browser,system}`, `core/main.py`
  (`tap_key`), `packaging/nfpm.yaml`, `docs/compatibility.md`,
  `docs/troubleshooting.md`, `.po` catalogs for any new spoken strings.
- Sequencing: depends on easyspeak#233's landing; reconciliation with whatever
  shape its ydotool plumbing finally has is an explicit step.

## Constraints

- Never strand the user: the gate fails closed like #233's — when no backend
  can inject, dictation keeps its spoken fallbacks (clipboard + apology), and
  the system plugin keeps its direct-control fallback.
- Reuse #233's reliability model for uinput (permission probing, ydotoold vs
  daemonless, recovery after `/dev/uinput` perms reset) — do not invent a
  second one.
- Backend selection must be explicit enough that media-key replay semantics
  don't silently drift on GNOME.
- Repo gates apply: REUSE licensing, translations, docs strict build, full
  test suite across supported Pythons; make targets, never raw tools.
- No `EASYSPEAK_GRID_*` coupling: the key-injection gate gets its own override
  (naming follows the `EASYSPEAK_GRID_BACKEND` precedent).

## Open questions

- Module identity: extend `core/mediakeys.py` in place into the gated injector
  (it already owns the KEYS/parse vocabulary and all call sites reach it), or
  add a parallel `core/injection.py`? Leaning extend-in-place now that ALL
  consumers migrate; mediakeys' docstring/identity gets rewritten accordingly.
- Env override name (e.g. `EASYSPEAK_KEY_BACKEND`) and accepted values.
- Whether replaying brightness keys via the fallback flips that compatibility
  row to ✅ on COSMIC — verify in the VM, don't assert.
- Acceptance scope for the volume-OSD scenario on COSMIC (one VM screenshot
  scenario is planned; exact assertions settled during spec review).
