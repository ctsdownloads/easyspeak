# Acceptance evidence — compositor-agnostic key injection (spec §12)

Fork-only receipts for the compatibility-column acceptance run of 2026-10-17.

- **Code under test:** worktree `easyspeak.WT.compositor-agnostic-typing-for-easyspeak`
  at `9d22b75`. Guest checkout `~/easyspeak` updated to the same commit via
  `git fetch origin compositor-agnostic-typing-for-easyspeak && git restore
  --source=FETCH_HEAD --staged --worktree -- src pyproject.toml` (the
  checkout's pre-existing doc-only local edits were left untouched); drivers
  ran under `~/easyspeak/.venv/bin/python`.
- **VM:** `easyspeak-cosmic` (Pop!_OS 24.04 / COSMIC 1.x, ydotool
  `0.1.8-3build1` = the **legacy daemonless dialect**), 192.168.122.173.
  The VM sat at `cosmic-greeter` the whole run (no autologin this boot;
  screenshot: `docs/superpowers/plans/media/acceptance-2026-10-17/vm-greeter.png`
  — untracked host artifact), so all guest drivers ran over SSH with
  `XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`
  and no focused GUI field (per the runbook the greeter was not fought).
- **Dev host:** Pop!_OS 22.04, GNOME 42 on Wayland
  (`XDG_CURRENT_DESKTOP=pop:GNOME`, `pop-wayland`), worktree `.venv`
  (python3.14).

## Verdict table

| # | Scenario (spec §12) | Verdict | Evidence |
|---|---------------------|---------|----------|
| 1 | COSMIC VM: dictation pastes into a focused field, no manual paste | **PENDING-HUMAN** | Provisioning gap below; probe-leniency half verified: `insert_text` on non-GNOME proceeded past the NO_FOCUS probe into the clipboard branch and only the missing `wl-clipboard` diverted it to AT-SPI (`insert_text -> no_focus elapsed 0.162s`) |
| 2 | COSMIC VM: "press enter" keystroke lands | **PENDING-HUMAN** | Same gap; argv + graceful-failure transcript captured (`ydotool key enter`, single invocation) |
| 3 | COSMIC VM: volume replay pops COSMIC's OSD | **FAIL on 0.1.8 — code finding F1** (+ same provisioning gap) | `core.tap_key(115) -> False` with "no legacy combo name for evdev code 115"; falls back silently to `wpctl`, no OSD possible on this dialect. Works on 1.0.x (modern argv sends raw codes) |
| 4 | COSMIC VM: "backspace ten" = ONE batched invocation within the latency bound | **PARTIAL: single-invocation proven; ten deletions PENDING-HUMAN** | argv `('ydotool', 'key', '--repeat', '10', 'backspace')` — one client invocation; failure path 1.087s ≤ `key_timeout(10)` = 2.5s. Calibration of the provisional `KEY_PER_REPEAT_BUDGET` (0.05s) needs a successful batch — blocked by the same gap |
| 5 | `EASYSPEAK_KEY_BACKEND` override honored; unknown warns + auto | **PASS** (3 of 4 arms fully; `uinput`-succeeds arm pending the provisioning gap, its failure arm fully exercised) | Transcripts below |
| 6 | GNOME host: dictated text lands end-to-end; volume key fires; routing log says `remote-desktop` | **PASS** | Buffer read via AT-SPI: LEN 0 → 26, `'easyspeak host paste 0.1.8'` after one `ctrl+v` chord (0.008s); volume 28% → changed, restored to the exact raw 18352; log line `key injection backend: remote-desktop` on both |
| 7 | Clean-VM package check (0.1.8 daemonless) | **PARTIAL: contents verified; live install PENDING-HUMAN** | `just check-deb-package` PASS; `Depends:` includes `ydotool` and `wl-clipboard`; deb ships `mediakeys.py` + `ydotool.py`; provisioning docs verified exact |

## Blocking gap on the VM (why 1–4 are not green yet)

The VM's uinput provisioning is **half applied**: `/etc/udev/rules.d/60-easyspeak-uinput.rules`
(`KERNEL=="uinput", MODE="0660", GROUP="input"`, mtime 2026-10-15) is installed,
but user `pop-os` is not in `input` (`getent group input` → `input:x:995:`,
no members; `id` → `adm sudo lpadmin`). `/dev/uinput` is `crw-rw---- root input`,
so every ydotool invocation dies with `failed to open uinput device` before emitting.

Every legitimate non-root route was probed and closed:

- `sudo -n` → `sudo: a password is required`; `sudo -S` with an empty password
  fails (`passwd -S` → `pop-os P`, a password is set). `pkexec` → `Error
  executing command as another user: No authentication agent found`.
- `newgrp input` / `sg input` → `Password: Invalid password.` (no joinable
  group password).
- Passwordless root SSH inside the guest → `Permission denied (publickey,password)`.
- The rule carries no `TAG+="uaccess"`, so a logind seat session would not
  grant an ACL either.

**One human command** completes provisioning (plus the package install for the
clean-VM half):

```sh
sudo usermod -aG input pop-os        # then log out/in (or reboot)
sudo apt install ./easyspeak_0.0.0_amd64.deb   # brings wl-clipboard too
```

After that, scenarios 1–4 and the `uinput`-works arm of 5 rerun with the exact
transcripts in this file (drivers are still at `/tmp/acc_*.py` on the guest).

## Exact argv lines the drivers logged (scenario 4 discriminator)

Single-invocation proof — each press/repeat batch is ONE client invocation,
one process, regardless of dialect:

```text
# legacy 0.1.8 (VM driver output)
ARGV backspace x10: ('ydotool', 'key', '--repeat', '10', 'backspace')
ARGV press enter:   ('ydotool', 'key', 'enter')
# modern 1.0.x (argv built with the dialect forced; repeats are ten
# consecutive down/up cycles, still one invocation)
modern backspace x10: ('ydotool', 'key', '14:1', '14:0', '14:1', '14:0', … '14:1', '14:0')  # 40 tokens
modern volume tap:    ('ydotool', 'key', '115:1', '115:0')
```

## VM transcripts (guest, COSMIC, no GUI session)

### Auto gate + "backspace ten" (scenarios 4, 5-auto)

```text
INFO easyspeak.core.mediakeys key injection backend: uinput
WARNING easyspeak.core.ydotool ydotool refused: ydotool: notice: ydotoold backend unavailable (may have latency+delay issues)
terminate called after throwing an instance of 'std::runtime_error'
  what():  failed to open uinput device
WARNING easyspeak.core.ydotool injection outcome: errored
WARNING easyspeak.core.mediakeys uinput injection errored: ydotool key --repeat 10 backspace
WARNING easyspeak.core.mediakeys Keystrokes could not be injected: injection errored: ydotool key --repeat 10 backspace — check ydotool is installed, /dev/uinput access (udev rule or input group), and ydotoold on 1.0.x
key_timeout(10): 2.5
press_key -> False elapsed 1.087s
```

The gate routed COSMIC → uinput (the whole feature's discriminator), the batch
is one argv, and the failure names the remedy (fail-closed, spoken-refusal
ladder intact — `press_key` returned False, no crash).

### "Press enter" (scenario 2)

```text
INFO easyspeak.core.mediakeys key injection backend: uinput
WARNING easyspeak.core.mediakeys uinput injection errored: ydotool key enter
WARNING easyspeak.core.mediakeys Keystrokes could not be injected: injection errored: ydotool key enter — check ydotool is installed, ...
ARGV press enter: ('ydotool', 'key', 'enter')
press enter -> False elapsed 1.091s
```

### Backend override arms (scenario 5)

Forced `remote-desktop` on COSMIC (Mutter absent) — fails gracefully, no crash:

```text
INFO easyspeak.core.mediakeys key injection backend: remote-desktop
WARNING easyspeak.core.mediakeys Keystrokes could not be injected: The name is not activatable
press_key -> False elapsed 0.001s
process alive after outcome: no crash
```

Unknown value — warns and falls back to auto:

```text
WARNING easyspeak.core.mediakeys Ignoring EASYSPEAK_KEY_BACKEND='not-a-thing': unknown backend. Known: remote-desktop, uinput, auto.
INFO easyspeak.core.mediakeys key injection backend: uinput
```

Forced `uinput` — exercised in the volume probe below (backend selected, then
the F1 `ValueError`; with a table-covered key it reproduces the backspace-ten
failure transcript verbatim).

### Code findings surfaced by the VM run (0.1.8 legacy dialect only)

- **F1 — volume/media-key replay cannot work on 0.1.8.** The legacy `key`
  verb takes NAMES (`KEY_LEGACY_NAMES`, `src/core/ydotool.py:481-498`) and the
  table has no volume keys, so `tap_key(115)` raises
  `ValueError: no legacy combo name for evdev code 115: the 0.1.8 key verb
  takes names, not codes` (`src/core/ydotool.py:593-600`) before any process.
  `core.tap_key`'s `except Exception` (`src/core/main.py:190-199`) catches it —
  exactly per design — so the volume still changes via the `wpctl` fallback
  (`core.tap_key(115) -> False`, warning
  `media-key injection failed; using the direct fallback: no legacy combo name
  for evdev code 115…`) but the COSMIC OSD can never appear on this dialect.
  On 1.0.x (modern) `key_argv` sends raw codes and volume replay works.
- **F2 — `ValueError` escapes `press_key`'s graceful contract.** `press_key`
  catches only `(RuntimeError, OSError)` (`src/core/mediakeys.py:402`), so for
  any keycode outside the legacy table it raises instead of returning False.
  Reproduced with a spoken-vocabulary key:
  `page_up press_key RAISED ValueError: … evdev code 104 …`. `page up` (104)
  and `page down` (109) are in `mediakeys.KEYS` and in dictation's
  `BARE_KEYS` (`src/plugins/dictation/__init__.py:666`) but MISSING from
  `KEY_LEGACY_NAMES`, so spoken "press page up" on a 0.1.8 system lands in
  `route_command`'s apology handler (`src/core/main.py:288-300`) instead of
  the intended "Dictation isn't set up on this system." refusal. Bounded: no
  crash (dispatch guard), legacy dialect only.

### Dictation probe leniency (scenario 1's off-GNOME half)

```text
WARNING easyspeak.plugins.dictation wl-clipboard is not installed, so dictation is falling back to AT-SPI, ...
INFO easyspeak.plugins.dictation ⌨️  inserting 16 chars via AT-SPI (python3)
insert_text -> no_focus elapsed 0.162s
```

Non-GNOME: the NO_FOCUS probe is doubted and the clipboard branch is entered,
exactly per spec §12's "non-GNOME NO_FOCUS proceeds to clipboard path".

## Host transcripts (dev host, GNOME 42 / Wayland, unlocked)

### Volume replay (scenario 6)

```text
BEFORE: Volume: front-left: 18352 /  28% / -33.17 dB …
INFO easyspeak.core.mediakeys key injection backend: remote-desktop
tap_key(115) elapsed 0.020s
AFTER:  Volume: front-left: 45876 /  70% / -9.29 dB …
RESTORED: Volume: front-left: 18352 /  28% / -33.17 dB   (exact raw restore)
```

Routing log says `remote-desktop`; the injected keycode fired. Note: while the
screen was LOCKED the same call failed with Mutter's own
`InjectionUnavailableError: Session creation inhibited` — GNOME inhibits
RemoteDesktop while locked (expected security behavior, worth knowing when
reading remote acceptance logs).

### Paste regression (scenario 6) — disposable gedit

Driven as `wl-copy` + `mediakeys.tap_chord((29, 47))` (the dictation paste
path's exact chord); the AT-SPI buffer read replaces the screenshot as visual
proof (host screenshot was impossible: `gnome-screenshot` absent, Shell
Screenshot D-Bus → `AccessDenied: Screenshot is not allowed`, `import` → no X
server on the Wayland session — the documented fallback, applied honestly).

```text
===BEFORE=== APP='gedit' FOCUSED=True LEN=0 TEXT=''
INFO easyspeak.core.mediakeys key injection backend: remote-desktop
tap_chord ctrl+v elapsed 0.008s
===AFTER===  APP='gedit' FOCUSED=True LEN=26 TEXT='easyspeak host paste 0.1.8'
```

Behavior identical to pre-change (paste into the focused field, clipboard
save/restore contract untouched — `insert_text` itself is pre-existing code).

## Scenario 7: clean-VM package check

`just check-deb-package` (builds in an ubuntu container, ~4 min) — **PASS**:

```text
created package: /out/easyspeak_0.0.0_amd64.deb
The .deb installs the launcher, autostart entry and refresh unit
The .deb bundles the GNOME extension, schema included
The .deb ships the license and the tray helper for other desktops
The .deb only suggests GNOME's parts and kdialog, so other desktops stay lean
✔  Debian package looks good.
```

Artifact: `dist/easyspeak_0.0.0_amd64.deb` (238M; version `0.0.0` is the check
recipe's build-check default, not a release version).

- **Deps:** `Depends:` = `…, wl-clipboard, ydotool` — the injection and paste
  tools are hard dependencies (spec: "deb/rpm deps include ydotool"); GNOME's
  parts stay in `Suggests:`.
- **Ships the new code:** `dpkg-deb -c` shows
  `./opt/easyspeak/venv/lib/python3.14/site-packages/easyspeak/core/mediakeys.py`
  and `…/core/ydotool.py`.
- **Provisioning docs verified exact** (`docs/troubleshooting.md:64-78`): the
  udev rule text matches the VM's installed rule character-for-character, and
  the steps are the complete set (`udevadm control --reload-rules`,
  `udevadm trigger`, `usermod -aG input`, re-login, plus the ydotoold-restart
  caveat). The code's failure message names the same remedy, so a clean-VM
  user is guided correctly. The VM's provisioning skipped only the
  `usermod -aG input` step — see the blocking gap.
- **Live install** requires the guest sudo password → PENDING-HUMAN; nothing
  was faked.

## Timings

| Event | Measured |
|---|---|
| backspace-ten, failure path, VM | 1.087s (bound: `key_timeout(10)` = 2.5s) |
| press-enter, failure path, VM | 1.091s |
| forced remote-desktop refusal, VM (Mutter absent) | 0.001s |
| dictation `insert_text` NO_FOCUS probe path, VM | 0.162s |
| host `tap_key(115)` via remote-desktop | 0.020s |
| host `tap_chord(ctrl+v)` → text in gedit | 0.008s |

## Screenshots

- `vm-greeter.png` — VM state at test time (cosmic-greeter, no user session):
  `docs/superpowers/plans/media/acceptance-2026-10-17/vm-greeter.png`
  (untracked host artifact).
- Host paste: no screenshot possible with available tools (see above); the
  AT-SPI buffer read (LEN 0 → 26 with the exact dictated string) is the
  recorded proof.
- COSMIC OSD (scenario 3): not capturable — blocked by F1 + provisioning.

## What a human reruns after provisioning the VM

```sh
ssh -i ~/.ssh/id_ed25519 pop-os@192.168.122.173   # with the session env exported
~/easyspeak/.venv/bin/python /tmp/acc_auto.py      # scenarios 4 + 5-auto (deletions + OSD-free path)
~/easyspeak/.venv/bin/python /tmp/acc_enter.py     # scenario 2
EASYSPEAK_KEY_BACKEND=uinput ~/easyspeak/.venv/bin/python /tmp/acc_generic.py  # scenario 5 uinput arm
# scenario 1/3 need a focused GUI session (autologin) + wl-clipboard from the deb
```

`KEY_PER_REPEAT_BUDGET` (`src/core/ydotool.py:460`, `PROVISIONAL — Task 7
calibrates it on the VM`) stays provisional: calibration needs a successful
batch, i.e. the provisioning step above.
