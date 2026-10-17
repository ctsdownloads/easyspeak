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
system/media-key replay. Packaging gains `ydotool` (wl-clipboard is already a
hard dep); the AT-SPI
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
4. Works from deb/rpm on a clean COSMIC install after the documented one-time
   uinput provisioning — the same deployment step #233 documents and the same
   `input`-group grant hold-to-dictate already needs — with no other manual
   steps **on the 0.1.8 daemonless dialect (Ubuntu 24.04, the acceptance
   VM's)**. On 1.0.x dialects a running `ydotoold` is additionally required
   (`docs/troubleshooting.md:85-96`); that step is documented, not packaged —
   see §7. (Package installation cannot grant `/dev/uinput` write access;
   #233 deliberately made that a deployment step, not a session tweak, and
   packaging a silent input-injection-grade grant from a desktop-app package
   would reverse that security stance.)
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

Row nouns used in §6, defined against the sticky gate: a backend is
**selected** at first injection (§4.2 stickiness) and **healthy** when it
answers at *injection* time. A backend that dies mid-session (ydotoold
crashes, socket goes stale, uinput perms revoked) keeps its sticky selection
and fails closed per injection via `InjectionUnavailableError` — the §6
"injection-time failure" row — with no re-resolution and no retry. Disclosed
corner: a Mutter restart window at *first* injection can stick a GNOME
session to the uinput backend for its lifetime; benign (an injected key is a
real event and still renders the OSD), accepted, and visible in the
selected-backend log line.

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
`tap_key(keycode, repeats=1)` and `tap_chord(keycodes)` onto the ydotool
`key` verb. **The repeats channel lives in the backend**: the uinput backend
emits `repeats` as ONE batched argv (`code:1 code:0` × repeats — one device,
one settle), while the RemoteDesktop backend keeps its per-repeat loop so the
GNOME path stays byte-for-byte identical; `press_key` passes `repeats`
through unchanged (`mediakeys.py:168-176`).
The argv is the keycodes **in the order given, each as `code:1`, then in
reverse, each as `code:0`** — identical to `tap_chord`'s documented contract
("keys go down in the order given and come up in reverse", `mediakeys.py:52-53`);
there is no modifier classification and none is needed. The exact `key` argv
grammar is dialect-dependent (§10): it is pinned from each dialect's own
`key --help` usage line before the synthesis lands, not assumed. The grid
keeps `mousemove` / `click` / `type` and imports the shared plumbing;
nothing about the grid's behavior changes.

Exception naming: `RemoteDesktopUnavailableError` becomes
`InjectionUnavailableError` (the ydotool backend raising a name that says
"RemoteDesktop" would lie). Renamed outright — no alias shim; this is an
application, not a library, and all importers are migrated in this same PR.

**The failure contract is total and raise-only.** The extracted seam returns
outcome strings (`ran` / `errored` / `unknown` — the stderr-scanning
vocabulary that survives because the client's exit codes lie). The backend
boundary translates that vocabulary completely into exceptions:

- `InjectionUnavailableError` keeps its **`RuntimeError` base** —
  `press_key`'s existing catch is `(RuntimeError, OSError)` by family
  (`mediakeys.py:173-175`), and callers (`dictation/__init__.py:675`,
  `browser/__init__.py:992-993`) are unguarded; a re-parented class would
  silently disarm both. A unit test asserts the subclass relation.
- `tap_key` / `tap_chord` are **raise-only** — they return nothing, so a
  backend that returns an outcome instead of raising cannot be silently
  ignored by `insert_text` (which checks only exceptions and would report
  `INSERTED`, then restore the old clipboard over the paste).
- The outcome mapping is **total**: `ran` → return; `errored` → raise
  `InjectionUnavailableError`; `unknown` (timeout mid-chord) → **also**
  raise `InjectionUnavailableError`, with the outcome distinction preserved
  in the log line (the plumbing already logs it) — a timeout is not a
  missing backend in the logs, but it lands in the same spoken fallback
  (§6). Every failure mode the backend can hit (binary absent, spawn
  `OSError`, `subprocess.TimeoutExpired`, non-zero exit / stderr refusal)
  resolves to that one exception type at the boundary — nothing foreign
  escapes to the dispatcher's catch-all (`core/main.py:306-308`), which
  would swallow the spoken refusal.

### 4.4 Consumer migration

- `plugins/dictation`: imports stay `mediakeys.*`; behavior change is only the
  added off-GNOME success path. The `except mediakeys.RemoteDesktopUnavailableError`
  clause updates to the renamed exception, and its warning log — which today
  says "Dictation needs GNOME's RemoteDesktop interface, which this desktop
  doesn't provide" (`dictation/__init__.py:496-498`) — is reworded
  desktop-neutrally (it would name a bus irrelevant to the now-common uinput
  failure). Log strings are developer-facing English, not `_()`-wrapped, so
  this costs no catalog churn. `NO_KEYSTROKES` spoken messaging unchanged.
- `plugins/browser`: no exception handling of its own — it calls
  `mediakeys.press_key` and speaks only on a `False` return
  (`browser/__init__.py:992-993`). The real migration site is
  `press_key`'s internal catch, whose warning names GNOME's RemoteDesktop
  (`mediakeys.py:174`) and is reworded with the rename. The spoken refusal
  "Keystrokes need GNOME." becomes **false** on the desktops this PR
  targets, so it is reworded to name the actual remedy (one new `_()`
  string ×4 catalogs, §8); compatibility footnotes [^browser], [^dictation],
  and [^volume] are all updated in the same sweep.
- `plugins/system` / `core.tap_key`: unchanged call sites; on GNOME the
  RemoteDesktop backend preserves today's OSD semantics; off GNOME the
  ydotool backend makes the desktop's own handler (and its OSD) respond.
  `core.main.tap_key`'s docstring ("False if unavailable (e.g. a non-GNOME
  session)", `core/main.py:193-195`) joins §4.1's identity rewrite — after
  the gate, unavailable also means "backend probe failed" and "GNOME with
  Mutter unowned".

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

**Repeats batch into one invocation.** Daemonless ydotool pays a fresh uinput
device plus a settle delay per invocation (measured on a live COSMIC session:
`--delay 0` delivers nothing, the default 100ms delivers,
`_ydotool.py:415-425`), and `press_key` loops `tap_chord` per repeat up to
`MAX_KEY_REPEATS = 200`. The uinput synthesis therefore emits repeats as ONE
`key` argv — `14:1 14:0 14:1 14:0 …` for "backspace ten" — one device, one
settle, not ten. The examples above are the modern dialect's grammar; the
legacy form is pinned per dialect before synthesis lands (§10).

## 6. Error handling — nobody gets stranded

| Situation | Dictation | Browser keystrokes | System replay |
|---|---|---|---|
| GNOME, Mutter present | RemoteDesktop path (today) | today | today (native OSD) |
| COSMIC/KDE, backend selected and answering at injection time | paste lands | keys land | desktop's own OSD |
| Backend dies mid-session (ydotoold crash, stale socket, revoked perms) — sticky selection unchanged | per-injection `InjectionUnavailableError` → `NO_KEYSTROKES` → spoken "…text is on the clipboard, paste it with Control V." | `press_key` returns False → spoken refusal (reworded, §4.4) | system plugin's direct-control fallback |
| No usable backend at selection time | same spoken fallback as the row above | same refusal | direct-control fallback (today) |
| Injection times out (`unknown` outcome, possibly mid-chord) | same spoken fallback; the log keeps `unknown` distinct from `unavailable`; VM-verify whether a timed-out daemonless chord leaves a modifier latched (persistent-device 1.0.x case) | same | same |
| wl-clipboard missing, backend healthy | AT-SPI fallback (today's behavior + warning) | n/a | n/a |
| uinput perms lost (reboot) | gate probe fails → fail-closed messages above; log names the fix (input group / udev rule) | same | same |

Design rule carried from #233: the gate fails closed and *says so*; no silent
swallowing, no fallback that strands the user without a way back.

## 7. Packaging and deployment

- `packaging/nfpm.yaml`: add `ydotool` as a hard dependency (deb `Depends` /
  rpm `Requires`). wl-clipboard is already a hard dep (`nfpm.yaml:56`, `:80`) —
  the COSMIC VM lacked it only because the VM runs from the checkout, not the
  package.
- "Out of the box" is defined against #233's own security stance: package
  installation does NOT grant `/dev/uinput` write access. The documented
  one-time provisioning step (`docs/troubleshooting.md:63-75`: a udev rule or
  the `input` group — "a deployment step, not a session tweak") remains the
  user's single manual step, shared with hold-to-dictate's existing
  `input`-group need; everything else works with no package-level manual
  steps. Packaging a silent, input-injection-grade udev grant from a
  desktop-app package would reverse the stance #233 set — not done here;
  revisiting that is its own conversation.
- uinput provisioning guidance is **reused from #233**, not reinvented; this
  PR extends `docs/troubleshooting.md` with the recovery path for perms lost
  at reboot.
- The daemon model is dialect-dependent by design, not an open question:
  0.1.8 (Ubuntu 24.04) injects daemonless per invocation; 1.0.x requires a
  running `ydotoold` (`docs/troubleshooting.md:85-96`). The extraction keeps
  #233's dual-mode support as the single documented path, and
  troubleshooting.md covers the daemon step for 1.0.x distros — where the
  `ydotool` package is CLI-only on 24.04/25.10 and the daemon ships
  separately (`ydotoold` package / user unit).

## 8. Docs and translations

- `docs/compatibility.md`: new COSMIC column, marking only verified/landed
  reality (tray ✅ already verified; dictation / browser keystrokes / volume
  reflect this PR's acceptance results; brightness only if the VM proves
  it). The same sweep updates the KDE footnotes [^dictation], [^browser],
  and [^volume], whose claims this change invalidates — softened to "as of
  the last KDE test" unless a KDE verification lands in §9.
- `docs/usage.md`: an `EASYSPEAK_KEY_BACKEND` row in the env-var reference
  table (`remote-desktop | uinput | auto`, default auto, sticky for the
  process lifetime) — the same table the base branch's own HEAD commit
  (`dac70d2`) just extended for `EASYSPEAK_GRID_TYPELIB`; shipping the
  override without its row re-creates the exact drift that commit fixed.
- `docs/commands.md`: the dictation precondition ("needs `wl-clipboard`
  installed and a text field focused", `:140-141`) is reworded — off GNOME a
  missed focus probe no longer blocks the paste (§4.5).
- `docs/troubleshooting.md`: uinput perms, `input` group, ydotoold socket,
  `EASYSPEAK_KEY_BACKEND` override.
- `docs/how-it-works.md`: the dictation line gains "…synthetic paste keystroke
  via the platform's injection backend (Mutter RemoteDesktop or ydotool)".
- Spoken strings: exactly ONE new `_()` string (the browser refusal, §4.4)
  → the four `.po` catalogs (de/es/fr/it) per repo convention (`just
  translations <lang>`). The reworded failure-path logs are developer-facing
  English (not `_()`-wrapped) and cost nothing.

## 9. Testing strategy

**Unit** (alongside existing core tests; gate logic pure and injected):

- selection matrix: override×{remote-desktop, uinput, auto, unknown-value} ×
  {GNOME, non-GNOME} × {Mutter owned, unowned}
- stickiness (second call does not re-resolve), backend log line
- `tap_key`/`tap_chord` routing per backend; exception rename fallout; the
  subclass relation `issubclass(InjectionUnavailableError, RuntimeError)`;
  the **total outcome mapping** — a stub backend that RETURNS `errored` or
  `unknown` instead of raising must still produce the spoken-refusal paths
  (the test that fails any return-style implementation, §4.3)
- probe leniency: NO_FOCUS × {GNOME → refuse, non-GNOME → proceed}
- full repo gates: unit across 5 Pythons, integration, acceptance, types,
  REUSE, translations, docs strict, wheel/sdist — via make targets.

**Acceptance** (easyspeak-cosmic VM, harness pattern from #233's
`test_mousegrid_ydotool_harness.py`; framebuffer screenshots via
`virsh screenshot`):

1. dictation pastes formatted text into a focused GTK field (screenshot)
2. browser-mode "press enter" lands
3. voice "volume up" pops COSMIC's own OSD (screenshot)
4. keystroke commands: "backspace ten" removes ten chars as ONE batched
   invocation, inside ~2s on the VM (one device creation + settle; baseline
   measured during acceptance and the bound tightened to it)
5. `EASYSPEAK_KEY_BACKEND` forces a backend regardless of session (unit-tested
   on both session kinds); an unknown value warns and proceeds with auto
6. key-verb argv grammar captured from BOTH dialects' `key --help` usage
   lines; the argv unit tests assert against those captured fixtures
   (per-dialect) — never against the synthesizer's own output

**GNOME regression** (dev host, Pop!_OS 22.04 / GNOME 42): the gate is
**end-to-end**, not log-asserted — dictated text must land in a field (the
same text-lands assertion as acceptance item 1) and a volume key must fire;
a moved `tap_chord` body that regresses logs the identical selected-backend
line, so the log lines are secondary evidence, never the gate.

## 10. Sequencing and reconciliation with #233

Hard ordering softened into stacking: this branch sits directly on #233's
head (`dac70d2`), so the extraction reads the landed `_ydotool` in-tree —
no guessing. Merge order stays: #233 lands first, this follows. This PR then:

1. Extract to core exactly the reusable plumbing: uinput access probe,
   ydotool 0.1.8 daemonless and 1.0.x daemon-socket support, recovery
   diagnostics. The grid keeps its mouse verbs and imports the shared module
   (the consolidation #233's review asked for; the grid's conversation loops
   are untouched).
2. Add the `key`-verb synthesis the grid never needed (chords/keycodes),
   pinning the argv grammar from BOTH dialects' own `key --help` usage lines
   (the same client-derived probing the dialect detection uses) and batching
   repeats into one argv (§5).
3. Reconcile packaging (add the ydotool dep) and troubleshooting docs.
4. Re-run the full gate + VM acceptance on the reconciled tree.
5. PR hygiene: the `docs/superpowers/` artifacts stay on the fork only —
   stripped from the upstream PR's file list (the #233 review questioned that
   folder's place in the repo; re-verify the thread when opening the PR) —
   and a distilled summary lands as a comment on #234, together with the VM
   evidence receipts (screenshots, logs) that the compatibility column's
   "verified" claims cite.

Coordination note: #234 carries the grid-side issue record; a comment there
points at this design when the PR opens.

## 11. Risks and mitigations

- **GitHub phantom `mergeable=CONFLICTING`** (observed on #233's push):
  verify with `git merge-tree` before assuming real conflicts.
- **Sticky gate vs. dev iteration**: developers toggling backends mid-session
  use `EASYSPEAK_KEY_BACKEND` + daemon restart; documented, not accidential.
- **ydotool `key` verb semantics** (dialect-dependent argv, chord ordering):
  the test oracle is each dialect's own `key --help` usage line or a captured
  fixture — never the synthesizer under test (self-certifying argv tests are
  green by construction) — plus one VM scenario on the legacy dialect the
  acceptance VM actually speaks; ordering bugs surface immediately as
  "nothing pasted".
- **Daemonless latency** (fresh uinput device + settle per invocation,
  measured at 100ms on COSMIC): owned by batching repeats into one argv
  (§5); the acceptance criterion carries a latency bound so a regression to
  per-repeat invocations is visible instead of merely sluggish.
- **Partial-repeat accounting** (pre-existing, amplified off GNOME): a
  keystroke failing mid-loop leaves `dictation_last_length` stale, so a later
  "scratch that" over-deletes. Batching shrinks the window — one invocation,
  one outcome — but the accounting stays repeat-level; noted, not redesigned
  here.
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
- [ ] Browser-mode "press enter" works on COSMIC; footnotes [^browser],
      [^dictation], [^volume] updated — no compatibility.md claim contradicts
      this PR's behavior
- [ ] Voice "volume up" on COSMIC triggers the COSMIC OSD; screenshot captured
- [ ] Keystroke commands ("backspace ten") land as one batched invocation
      within the measured latency bound on COSMIC
- [ ] GNOME host: dictated text lands end-to-end in a field and a volume key
      fires (routing log lines recorded as secondary evidence); behavior
      identical to pre-change
- [ ] No-backend environment degrades exactly per §6 (spoken fallbacks, no
      stranding); covered by unit tests
- [ ] `EASYSPEAK_KEY_BACKEND` override honored; unknown values warn + auto;
      documented in the usage.md env-var table
- [ ] Probe leniency: non-GNOME NO_FOCUS proceeds to clipboard path; GNOME
      unchanged
- [ ] deb/rpm deps include ydotool (wl-clipboard already shipped)
- [ ] Clean-VM install (Ubuntu 24.04 base, 0.1.8 daemonless): dictation works
      after the documented one-time uinput provisioning, with no other manual
      steps; on 1.0.x dialects the ydotoold step is documented
      (troubleshooting.md:85-96)
- [ ] compatibility.md COSMIC column reflects only verified results
- [ ] Full repo gates green (unit×5 pythons, integration, acceptance, types,
      REUSE, translations, docs strict, wheel/sdist)
