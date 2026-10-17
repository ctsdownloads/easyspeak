# Design: Compositor-agnostic key injection for EasySpeak

- Date: 2026-10-17
- Status: approved design, pending implementation plan
- Author: Elifarley (with Claude Code)
- Intent: `docs/superpowers/intents/2026-10-17-compositor-agnostic-typing-for-easyspeak-intent.md`
- Depends on: ctsdownloads/easyspeak#233 — this branch is stacked directly on
  its head (`dac70d2`, branch `69-prototype-compositor-agnostic-easyspeak-backend-layer-shell-overlay-ydotool`
  on `elifarley/easyspeak`); merge order: #233 lands, then this
- Verification basis: live tests on the `easyspeak-cosmic` VM (Pop!_OS 24.04 / COSMIC, libvirt, SSH + framebuffer screenshots), 2026-10-17

## 1. Summary

All keystroke injection moves behind one capability-gated backend selection
inside `src/core/mediakeys.py`: Mutter RemoteDesktop when the session provides
it (GNOME — unchanged behavior), otherwise a ydotool/uinput backend whose
plumbing is extracted from PR #233's `_ydotool`. Three consumers migrate:
dictation (paste chord + keystroke commands), browser mode (press-key), and
system/media-key replay. Packaging gains `wl-clipboard` + `ydotool`; the AT-SPI
focus probe falls open off GNOME; the compatibility table gains a COSMIC
column. GNOME behavior is the regression gate: byte-for-byte unchanged.

## 2. Background and evidence

`mediakeys.tap_chord` / `press_key` inject through `org.gnome.Mutter.RemoteDesktop`
(`src/core/mediakeys.py:19-22`), which only Mutter owns. Three consumers share
that one door:

| Consumer | Call site | Purpose today |
|---|---|---|
| `plugins/dictation` | `tap_chord` (`dictation/__init__.py:493`), `press_key` (`:675`) | paste chord, backspace×N / enter / tab… |
| `plugins/browser` | `press_key` (`browser/__init__.py:990-992`) | "press enter"-style keystrokes |
| `plugins/system` | `core.tap_key` (`core/main.py:190-200`) → `mediakeys.tap_key` | media-key replay for the desktop's own OSD |

Live on the COSMIC VM (verified this session):

- `org.gnome.Mutter.RemoteDesktop` unowned → `tap_chord` raises
  `RemoteDesktopUnavailableError: The name is not activatable`. Consequences:
  dictation speaks "I can't type on this desktop yet…" (clipboard-only),
  browser keystrokes refuse, replay never runs (system plugin's direct
  fallback changes volume silently — compatibility.md ⚠️ "without the
  on-screen indicator").
- The COSMIC VM lacks `wl-clipboard` entirely, so today dictation there falls
  into the AT-SPI-typing fallback, which Chromium/Electron discard silently.
- The tray item (StatusNotifierItem) already works on COSMIC with zero code
  change — established earlier the same day; typing is the remaining gap.

PR #233 (unmerged as of this design) proves the fallback on the same VM: its
`_ydotool` backend injects through uinput — compositor-independent, kernel
level — and its `type` verb works under COSMIC.

## 3. Goals and non-goals

**Goals**

1. Dictation fully works on COSMIC/KDE: transcribe → clipboard → automatic
   paste; keystroke commands (backspace, enter, …) work.
2. Browser-mode press-key works off GNOME.
3. Media-key replay works off GNOME through the same gate: the injected volume
   key is a real input event, so COSMIC/KDE render their own native OSD —
   the same fidelity goal the GNOME replay path was built for.
4. Works out of the box from deb/rpm on a clean COSMIC install.
5. GNOME unchanged (regression gate).

**Non-goals**

- No new spoken verbs or vocabulary beyond what exists.
- No mouse-grid behavior change (it keeps its own verbs; it only *imports* the
  extracted plumbing).
- No AT-SPI insertion improvements (the Chromium-discards-AT-SPI-text problem
  is untouched; wl-clipboard remains the primary path).
- No native COSMIC applet / Quick-Settings-like surface.
- No brightness guarantee (verify in the VM; only then flip the table row).

## 4. Architecture

### 4.1 The gate lives in `core/mediakeys.py`, extended in place

With all three consumers migrating, no "second master" remains, so a parallel
`core/injection.py` would only relocate the same functions and churn imports.
`mediakeys.py` already owns the `KEYS` / `KEY_NAMES` / `parse_key_request`
vocabulary and every call site already reaches it. Its module docstring and
identity are rewritten from "replay multimedia keys through GNOME" to
"key injection with per-desktop backends"; the replay story becomes one
backend among two, not the module's reason to exist.

### 4.2 Backend selection — explicit, cheap, sticky, fail-closed

Selection order, resolved lazily at first injection and **sticky for the
process lifetime**:

1. `EASYSPEAK_KEY_BACKEND` env override — `remote-desktop` | `uinput` |
   `auto` (default). The `uinput` value deliberately mirrors #233's
   `EASYSPEAK_GRID_BACKEND=uinput|gnome` vocabulary (the tool is ydotool; the
   *backend* is uinput). Unknown value → log a warning listing the accepted
   values and continue with auto (precedent: the grid gate's own
   unknown-value handling, `mousegrid/__init__.py:91-104`).
2. Auto: GNOME session (`on_gnome()`) **and** `org.gnome.Mutter.RemoteDesktop`
   owned → RemoteDesktop backend; else → ydotool backend. The odd corner of a
   GNOME session with Mutter unexpectedly unowned therefore degrades to the
   ydotool attempt (and from there to the fail-closed paths of §6) rather
   than crashing.
3. Neither usable (e.g. ydotool absent, uinput inaccessible) → raise the
   unavailable error at injection time; consumers keep their existing
   fail-closed fallbacks (§6).

Rationale for stickiness: the backend set cannot change mid-session (switching
compositor requires re-login), and per-utterance `NameHasOwner` round trips on
a wedged session bus are exactly the failure mode existing code caps with
timeouts elsewhere. One resolution, one log line stating the chosen backend
(`logger.info`), is predictable and debuggable.

GNOME detection reuses `on_gnome()` from `core.tray` (import, not copy — no
import cycle: `core.tray` does not import `core.mediakeys`). One definition of
"which desktop is this" stays in one tested place.

### 4.3 Backends

**RemoteDesktop backend** — today's `_call`/`tap_key`/`tap_chord` body moved
behind the gate, verbatim. Same CreateSession → Start →
NotifyKeyboardKeycode → Stop on one connection; same exception on refusal.

**Ydotool backend** — delegates to plumbing extracted from #233's
`_ydotool` (reconciliation contract in §10): uinput access probing,
ydotoold socket discovery / daemonless fallback, and recovery guidance.
New surface needed beyond the grid's verbs: keycode-level synthesis mapping
`tap_key(keycode)` and `tap_chord(keycodes)` onto the ydotool `key` verb
(`code:1` … `code:0` press/release pairs, chord = hold modifiers, tap target,
release modifiers in reverse). The grid keeps `mousemove` / `click` / `type`
and imports the shared plumbing; nothing about the grid's behavior changes.

Exception naming: `RemoteDesktopUnavailableError` becomes
`InjectionUnavailableError` (the ydotool backend raising a name that says
"RemoteDesktop" would lie). Renamed outright — no alias shim; this is an
application, not a library, and all importers are migrated in this same PR.

### 4.4 Consumer migration

- `plugins/dictation`: imports stay `mediakeys.*`; behavior change is only the
  added off-GNOME success path. The `except mediakeys.RemoteDesktopUnavailableError`
  clause updates to the renamed exception; `NO_KEYSTROKES` messaging unchanged.
- `plugins/browser`: same one-line exception rename; on COSMIC/KDE its
  keystrokes now land; compatibility footnote [^browser] updated.
- `plugins/system` / `core.tap_key`: unchanged call sites; on GNOME the
  RemoteDesktop backend preserves today's OSD semantics; off GNOME the
  ydotool backend makes the desktop's own handler (and its OSD) respond.

### 4.5 Probe leniency off GNOME

`has_focused_text_field()` / `insert_text`: when the AT-SPI probe answers
`NO_FOCUS` **and** the session is not GNOME, log at debug and proceed with the
clipboard+paste path instead of refusing ("No text field focused"). Rationale:
off GNOME the AT-SPI tree is unreliable (COSMIC-native iced apps may expose
nothing), so a negative probe is weak evidence; a paste that lands nowhere is
harmless, while a refusal blocks a working path. GNOME semantics unchanged; a
helper that cannot run at all still falls open as today (`:434-446`).

## 5. Data flow

Dictation utterance (unchanged up to insertion):

```
voice → transcribe → format_text → insert_text
    → has_focused_text_field()   [AT-SPI probe; lenient off GNOME]
    → wl-copy text                [wl-clipboard]
    → paste_chord()               [unchanged, incl. terminal Ctrl+Shift+V]
    → mediakeys.tap_chord(chord)
        → gate: sticky backend
        → RemoteDesktop: CreateSession…NotifyKeyboardKeycode…Stop
        → ydotool: key 29:1 47:1 47:0 29:0   (via extracted plumbing)
    → clipboard restore after CLIPBOARD_SETTLE
```

Replay (`plugins/system` → `core.tap_key` → `mediakeys.tap_key`): same gate,
single key instead of chord. Browser mode: same gate via `press_key`.

## 6. Error handling — nobody gets stranded

| Situation | Dictation | Browser keystrokes | System replay |
|---|---|---|---|
| GNOME, Mutter present | RemoteDesktop path (today) | today | today (native OSD) |
| COSMIC/KDE, gate healthy | paste lands | keys land | desktop's own OSD |
| No usable backend | `NO_KEYSTROKES` → spoken "…text is on the clipboard, paste it with Control V." | refusal message (today's wording) | system plugin's direct-control fallback (today) |
| wl-clipboard missing, backend healthy | AT-SPI fallback (today's behavior + warning) | n/a | n/a |
| uinput perms lost (reboot) | gate probe fails → fail-closed messages above; log names the fix (input group / udev rule) | same | same |

Design rule carried from #233: the gate fails closed and *says so*; no silent
swallowing, no fallback that strands the user without a way back.

## 7. Packaging and deployment

- `packaging/nfpm.yaml`: add `wl-clipboard` and `ydotool` as hard dependencies
  (deb `Depends` / rpm `Requires`) — dedupe if #233 already added ydotool.
  Out-of-the-box means: clean COSMIC install → dictation works with no manual
  package steps (the runbook's clean-environment tier).
- uinput provisioning (udev rule and/or `input` group guidance) is **reused
  from #233**, not reinvented here; this PR extends `docs/troubleshooting.md`
  with the recovery path for perms lost at reboot.
- Open packaging question deferred to reconciliation: whether #233's helper
  model expects `ydotoold` (system service) or daemonless mode; whatever it
  landed becomes the single documented path.

## 8. Docs and translations

- `docs/compatibility.md`: new COSMIC column, marking only verified/landed
  reality (tray ✅ already verified; dictation / browser keystrokes / volume
  reflect this PR's acceptance results; brightness only if the VM proves it).
- `docs/troubleshooting.md`: uinput perms, `input` group, ydotoold socket,
  `EASYSPEAK_KEY_BACKEND` override.
- `docs/how-it-works.md`: the dictation line gains "…synthetic paste keystroke
  via the platform's injection backend (Mutter RemoteDesktop or ydotool)".
- New spoken strings (if any wording changes) → all five `.po` catalogs per
  repo convention; target: no new strings needed (existing apologies already
  cover the failure paths).

## 9. Testing strategy

**Unit** (alongside existing core tests; gate logic pure and injected):

- selection matrix: override×{remote-desktop, ydotool, auto, unknown-value} ×
  {GNOME, non-GNOME} × {Mutter owned, unowned}
- stickiness (second call does not re-resolve), backend log line
- `tap_key`/`tap_chord` routing per backend; exception rename fallout
- probe leniency: NO_FOCUS × {GNOME → refuse, non-GNOME → proceed}
- full repo gates: unit across 5 Pythons, integration, acceptance, types,
  REUSE, translations, docs strict, wheel/sdist — via make targets.

**Acceptance** (easyspeak-cosmic VM, harness pattern from #233's
`test_mousegrid_ydotool_harness.py`; framebuffer screenshots via
`virsh screenshot`):

1. dictation pastes formatted text into a focused GTK field (screenshot)
2. browser-mode "press enter" lands
3. voice "volume up" pops COSMIC's own OSD (screenshot)
4. keystroke commands: "backspace five" removes five chars
5. `EASYSPEAK_KEY_BACKEND` forces a backend regardless of session (unit-tested
   on both session kinds); an unknown value warns and proceeds with auto

**GNOME regression** (dev host, Pop!_OS 22.04 / GNOME 42): dictation paste,
browser keystroke, volume replay all route to the RemoteDesktop backend (log
asserts), behavior identical to pre-change.

## 10. Sequencing and reconciliation with #233

Hard ordering softened into stacking: this branch sits directly on #233's
head (`dac70d2`), so the extraction reads the landed `_ydotool` in-tree —
no guessing. Merge order stays: #233 lands first, this follows. This PR then:

1. Extract to core exactly the reusable plumbing: uinput access probe,
   ydotool 0.1.8 daemonless and 1.0.x daemon-socket support, recovery
   diagnostics. The grid keeps its mouse verbs and imports the shared module
   (the consolidation #233's review asked for; the grid's conversation loops
   are untouched).
2. Add the `key`-verb synthesis the grid never needed (chords/keycodes).
3. Reconcile packaging (dedupe ydotool dep) and troubleshooting docs.
4. Re-run the full gate + VM acceptance on the reconciled tree.

Coordination note: #234 carries the grid-side issue record; a comment there
points at this design when the PR opens.

## 11. Risks and mitigations

- **GitHub phantom `mergeable=CONFLICTING`** (observed on #233's push):
  verify with `git merge-tree` before assuming real conflicts.
- **Sticky gate vs. dev iteration**: developers toggling backends mid-session
  use `EASYSPEAK_KEY_BACKEND` + daemon restart; documented, not accidential.
- **ydotool `key` verb semantics** (press/release pairs, chord ordering):
  covered by unit tests on the synthesized argv + one VM scenario; ordering
  bug would surface immediately as "nothing pasted".
- **AT-SPI leniency pastes into nothing** off GNOME when truly nothing is
  focused: harmless (Ctrl+V lands nowhere), and strictly better than refusing
  a path that works most of the time.
- **OSD scenario flakiness in VM**: acceptance uses the established screenshot
  retry practice; the scenario asserts the OSD appears, not its pixels.
- **Scope creep via replay**: replay migrates *as routing only* — no new
  brightness/volume features are promised; the compatibility table moves only
  on VM-verified evidence.

## 12. Acceptance criteria

- [ ] On the COSMIC VM, dictated text inserts into a focused field without
      manual paste; screenshot evidence captured
- [ ] Browser-mode "press enter" works on COSMIC; footnote [^browser] updated
- [ ] Voice "volume up" on COSMIC triggers the COSMIC OSD; screenshot captured
- [ ] Keystroke commands ("backspace five") work on COSMIC
- [ ] GNOME host: all three consumers route to the RemoteDesktop backend;
      behavior identical to pre-change (log-asserted)
- [ ] No-backend environment degrades exactly per §6 (spoken fallbacks, no
      stranding); covered by unit tests
- [ ] `EASYSPEAK_KEY_BACKEND` override honored; unknown values warn + auto
- [ ] Probe leniency: non-GNOME NO_FOCUS proceeds to clipboard path; GNOME
      unchanged
- [ ] deb/rpm deps include wl-clipboard + ydotool; clean-VM install works
      without manual steps
- [ ] compatibility.md COSMIC column reflects only verified results
- [ ] Full repo gates green (unit×5 pythons, integration, acceptance, types,
      REUSE, translations, docs strict, wheel/sdist)
