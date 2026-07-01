# Changelog

All notable changes to EasySpeak are documented here. This file is the
canonical, GitHub-independent record of releases. It is updated once per
release. The format loosely follows [Keep a Changelog](https://keepachangelog.com/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## 0.7.0 · Offline by Default · 2026-07-01

**A Strict Offline Switch, a Clean Abort When the Model Is Missing, and `--preview`**

A single `EASYSPEAK_OFFLINE` variable now governs whether EasySpeak may reach
the network, and it defaults to `strict` — nothing is fetched at runtime unless
you opt in, true to the fully-local ethos. The recognition model loads locally
first, so a bundled or previously-cached model needs no network at all. When it
is missing under the default, startup aborts cleanly: an actionable message
(set `EASYSPEAK_OFFLINE=relaxed` to download it, or install a language pack) and
a non-zero exit, mirroring the existing no-microphone handling. Set `relaxed` to
opt into the on-demand `base.en` download from Hugging Face, announced with a
warning.

A CLI-usability fix renames the one-shot `--show` desktop-integration option to
**`--preview`**, aligning the mental model of the two paired options: `--preview`
now prints exactly what `--configure` would install, so the two read as a single
preview-then-apply gesture rather than an odd `show`/`configure` mismatch. It also
takes exactly one item, since concatenating several files to stdout served no
purpose. Under the hood the data and extension folders move back under `src/`, the
packaging tests gain a README, and the GitHub Releases workflow is documented in
CONTRIBUTING.

### What's Changed

- Gate implicit Whisper downloads behind `EASYSPEAK_OFFLINE` by @bittner in [#114](https://github.com/ctsdownloads/easyspeak/pull/114)
- Rename `--show` CLI option to `--preview` by @bittner in [#113](https://github.com/ctsdownloads/easyspeak/pull/113)
- Move data and extension folders back to `src/` by @bittner in [#111](https://github.com/ctsdownloads/easyspeak/pull/111)
- Add README for the packaging tests by @bittner in [#112](https://github.com/ctsdownloads/easyspeak/pull/112)
- Document the GitHub Releases workflow in CONTRIBUTING by @bittner in [#110](https://github.com/ctsdownloads/easyspeak/pull/110)

**Full Changelog**: [`0.6.0...0.7.0`](https://github.com/ctsdownloads/easyspeak/compare/0.6.0...0.7.0)

## 0.6.0 · Made to Configure · 2026-06-30

**Configurable Chimes, a Single Hotkey Variable, and Versioned Docs**

`EASYSPEAK_*` environment variables now drive **cross-platform/distro configurability**:
rather than carrying platform-specific patches, EasySpeak exposes whatever
differs between systems as a variable you set — and documents every one of
them in the generated reference. The wake and sleep chimes, for one, stayed
silent under `uv run easyspeak` in the Nix dev shell (they only played under
`nix run`, which rewrote the freedesktop sound path that doesn't exist on
NixOS); instead of special-casing NixOS, the sound directory now lives behind
a new `EASYSPEAK_SOUNDS_DIR` variable. The two hotkey variables collapse into
one: `EASYSPEAK_HOTKEY` now holds the combo itself (default `ctrl+shift`; set
it empty or to `off`/`none` to disable), with a mistyped combo logging a
warning and disabling the listener instead of silently arming a dead key.

The documentation site moves to **mike's native versioning**, so the version
selector switches in place and always knows which version it is on. The
in-development docs from `main` now serve at `/latest/`, the most recent
release at `/stable/`, and every tagged release stays archived under its own
`/<version>/` path.

### What's Changed

- Make desktop sounds configurable, document env vars by @bittner in [#103](https://github.com/ctsdownloads/easyspeak/pull/103)
- Serve main docs at the root, redirect `/latest` to it by @bittner in [#104](https://github.com/ctsdownloads/easyspeak/pull/104)
- Tidy the docs deploy scripts and names by @bittner in [#106](https://github.com/ctsdownloads/easyspeak/pull/106)
- Consolidate the env-var reference in the Usage guide by @bittner in [#105](https://github.com/ctsdownloads/easyspeak/pull/105)
- Switch docs deploy to mike's convention by @bittner in [#107](https://github.com/ctsdownloads/easyspeak/pull/107)
- Merge the two HOTKEY env vars and validate the combo by @bittner in [#108](https://github.com/ctsdownloads/easyspeak/pull/108)

**Full Changelog**: [`0.5.0...0.6.0`](https://github.com/ctsdownloads/easyspeak/compare/0.5.0...0.6.0)

## 0.5.0 · New Domain, Modular Extension · 2026-06-30

**Quick Settings, the easyspeak.dev Domain, and a Modular Extension**

EasySpeak gains a GNOME **Quick Settings toggle** as an alternative to the panel
tray icon, and the extension's **Settings dialog** grows desktop-integration
controls and a Website link. Under the hood the wake-word engine is swapped to
**pyopen-wakeword** and the default Python moves to **3.14**, while spawned
desktop apps no longer inherit the dev shell's libraries — so the file manager
and friends launch against their own.

The project also settles into its own **easyspeak.dev** domain everywhere, and
the GNOME extension moves into a UUID folder (`gnome@easyspeak.dev`), splits from
a monolith into compositor-only **ES modules** behind a thin entrypoint, and now
derives its per-user autostart entry from the canonical desktop file instead of a
drifting copy. Rounding it out: CI is hardened with lint, link-checking, and
packaging verification; the distro-package checks are grouped behind a single
build; and the extension-refresh unit no longer fails when its `uv` interpreter
has vanished.

### What's Changed

- Swap wake-word backend to pyopen-wakeword and bump default Python to 3.14 by @bittner in [#93](https://github.com/ctsdownloads/easyspeak/pull/93)
- Add a Quick Settings toggle as an alternative to the tray icon by @bittner in [#96](https://github.com/ctsdownloads/easyspeak/pull/96)
- Add extension Settings dialog, desktop integration, and Website link by @bittner in [#91](https://github.com/ctsdownloads/easyspeak/pull/91)
- Stop leaking dev-shell libraries into spawned desktop apps by @bittner in [#95](https://github.com/ctsdownloads/easyspeak/pull/95)
- Use the newly acquired easyspeak.dev domain everywhere by @bittner in [#98](https://github.com/ctsdownloads/easyspeak/pull/98)
- Move GNOME extension to a UUID folder, rename to gnome@easyspeak.dev by @bittner in [#100](https://github.com/ctsdownloads/easyspeak/pull/100)
- Split GNOME extension into ES modules; consolidate autostart entry by @bittner in [#101](https://github.com/ctsdownloads/easyspeak/pull/101)
- Fix extension-refresh unit failing on a vanished uv interpreter by @bittner in [#89](https://github.com/ctsdownloads/easyspeak/pull/89)
- Harden CI: lint, link check, packaging verification, and release fold by @bittner in [#97](https://github.com/ctsdownloads/easyspeak/pull/97)
- Group the distro package checks; rename "native" → "distro" by @bittner in [#102](https://github.com/ctsdownloads/easyspeak/pull/102)
- Add a tray icon and menu screenshot, reduce file sizes by @bittner in [#94](https://github.com/ctsdownloads/easyspeak/pull/94)
- docs: Show the tray menu and Quick Settings side by side by @bittner in [#99](https://github.com/ctsdownloads/easyspeak/pull/99)

**Full Changelog**: [`0.4.0...0.5.0`](https://github.com/ctsdownloads/easyspeak/compare/0.4.0...0.5.0)

## 0.4.0 · Packaged and Polished · 2026-06-24

**Native Packages & a Docs Site**

EasySpeak now ships as native Debian (`.deb`) and Fedora (`.rpm`) packages, with
the language data split into separate packages so you install only the voices
you need. Dictation now actually works — backed by a proper AT-SPI backend that
reports failures honestly instead of silently doing nothing — and gains a silent,
keyboard hold-to-dictate activation for when you'd rather not speak the wake
word. The GNOME tray grows an About dialog and a Help entry, and the extension
is renamed simply "EasySpeak".

Under the hood, terminal output moved from `print()` to structured logging, the
codebase adopted Ruff's full "ALL" ruleset with curated exceptions, and a batch
of post-0.3.0 review findings were cleaned up; EasySpeak also fails gracefully
now when an audio device or gdbus is missing. Rounding it out is a hosted MkDocs
and Material documentation site on GitHub Pages — complete with screenshots and
Git-LFS-tracked media — while CI is streamlined onto `main` as the `dev` branch
is phased out.

### What's Changed

- feat(packaging): native `.deb`/`.rpm` with split language data by @bittner in [#77](https://github.com/ctsdownloads/easyspeak/pull/77)
- Make dictation work: provide the AT-SPI backend and report failures honestly by @bittner in [#69](https://github.com/ctsdownloads/easyspeak/pull/69)
- feat(core): silent (keyboard) hold-to-dictate activation by @bittner in [#70](https://github.com/ctsdownloads/easyspeak/pull/70)
- feat(tray): add About dialog and Help to the tray menu by @bittner in [#73](https://github.com/ctsdownloads/easyspeak/pull/73)
- refactor(extension): rename "EasySpeak Grid" to "EasySpeak" by @bittner in [#74](https://github.com/ctsdownloads/easyspeak/pull/74)
- Switch terminal output from `print()` to logging by @bittner in [#68](https://github.com/ctsdownloads/easyspeak/pull/68)
- Adopt Ruff "ALL" ruleset with curated exceptions by @bittner in [#65](https://github.com/ctsdownloads/easyspeak/pull/65)
- fix: address post-0.3.0 review findings (browser-launch trap, AT-SPI caret, hotkey shutdown) by @bittner in [#72](https://github.com/ctsdownloads/easyspeak/pull/72)
- Fail gracefully when audio device or gdbus is missing by @bittner in [#86](https://github.com/ctsdownloads/easyspeak/pull/86)
- docs: hosted MkDocs + Material + mkdocstrings site on GitHub Pages by @bittner in [#71](https://github.com/ctsdownloads/easyspeak/pull/71)
- Integrate screenshots in documentation by @bittner in [#85](https://github.com/ctsdownloads/easyspeak/pull/85)
- Serve latest docs at site root, check dead links in README by @bittner in [#84](https://github.com/ctsdownloads/easyspeak/pull/84)
- Track media files with Git-LFS, move images to docs/media by @bittner in [#83](https://github.com/ctsdownloads/easyspeak/pull/83)
- Fix docstring markup (reStructuredText ➜ MarkDown) by @bittner in [#81](https://github.com/ctsdownloads/easyspeak/pull/81)
- Trigger CI workflows on main only, phasing out dev by @bittner in [#87](https://github.com/ctsdownloads/easyspeak/pull/87)
- Fix broken docs screenshots, skip demo video in CI by @bittner in [#88](https://github.com/ctsdownloads/easyspeak/pull/88)

**Full Changelog**: [`0.3.0...0.4.0`](https://github.com/ctsdownloads/easyspeak/compare/0.3.0...0.4.0)

## 0.3.0 · Smoother and More Conversational · 2026-06-13

**Tray Icon & Instant Feedback**

This release puts EasySpeak in your GNOME tray — a status indicator with voice
deactivate — and makes it feel snappier by speaking feedback in parallel with
carrying out your command: the spoken reply now starts playing while the action
runs, instead of only after it has finished. It also adds native on-screen
displays and chimes for volume and brightness via media keys, and a persistent
Piper process that loads the voice model once for faster speech. EasySpeak now
owns the full GNOME-extension lifecycle — shipped as package data, staged so a
failed refresh can't corrupt an install, and time-bounded against hanging
system calls. The interaction model grew more conversational too: it keeps
listening between commands without repeating the wake word, handles "stop"
gracefully instead of quitting, and gives friendlier misunderstanding feedback
— backed by new integration/acceptance test tiers and a 99% coverage floor.

### What's Changed

- feat(apps): add more GNOME apps, handle default terminal by @bittner in [#57](https://github.com/ctsdownloads/easyspeak/pull/57)
- perf(tts): load the voice model once via a persistent piper process by @bittner in [#56](https://github.com/ctsdownloads/easyspeak/pull/56)
- refactor(core): new `speech` module, suppress ALSA error output by @bittner in [#58](https://github.com/ctsdownloads/easyspeak/pull/58)
- feat(system): native OSD for volume and brightness via media keys by @bittner in [#61](https://github.com/ctsdownloads/easyspeak/pull/61)
- feat(core): GNOME tray indicator with voice deactivate by @bittner in [#59](https://github.com/ctsdownloads/easyspeak/pull/59)
- test(extension): extract pure JS helpers and unit-test them by @bittner in [#60](https://github.com/ctsdownloads/easyspeak/pull/60)
- Improve voice interaction: friendlier feedback, parallel replies, richer commands, hands-free chaining by @bittner in [#63](https://github.com/ctsdownloads/easyspeak/pull/63)

**Full Changelog**: [`0.2.0...0.3.0`](https://github.com/ctsdownloads/easyspeak/compare/0.2.0...0.3.0)

## 0.2.0 · Broader Reach · 2026-06-07

**Runs in More Places**

EasySpeak broadens where and how it runs: installation now works on Python 3.13
(with dependencies pinned for 3.10), `pyaudio` ships as a dependency, and a new
Nix flake supports development and running on NixOS. This release also makes the
Piper TTS model path configurable, auto-installs the MouseGrid GNOME extension on
first run, and adds Whisper transcription-latency benchmarks. Config handling was
extracted into its own module and host-environment setup moved into the plugins,
tidying the codebase alongside steady dependency and security-workflow upkeep.

### What's Changed

- Allow installing on Python 3.13, pin deps for 3.10 by @bittner in [#33](https://github.com/ctsdownloads/easyspeak/pull/33)
- Add Python package version badge to README by @bittner in [#34](https://github.com/ctsdownloads/easyspeak/pull/34)
- Add pyaudio as a package dependency by @bittner in [#36](https://github.com/ctsdownloads/easyspeak/pull/36)
- Update outdated package dependencies (typer-slim ++) by @bittner in [#38](https://github.com/ctsdownloads/easyspeak/pull/38)
- Update outdated package dependencies by @bittner in [#39](https://github.com/ctsdownloads/easyspeak/pull/39)
- Run safety workflow also in PRs by @bittner in [#40](https://github.com/ctsdownloads/easyspeak/pull/40)
- Update outdated dependencies, restrict schedule for check by @bittner in [#41](https://github.com/ctsdownloads/easyspeak/pull/41)
- Update outdated package dependencies by @bittner in [#43](https://github.com/ctsdownloads/easyspeak/pull/43)
- Fix missing apt update for apt install by @bittner in [#44](https://github.com/ctsdownloads/easyspeak/pull/44)
- Update dependencies and actions by @bittner in [#45](https://github.com/ctsdownloads/easyspeak/pull/45)
- Update outdated package dependencies by @bittner in [#49](https://github.com/ctsdownloads/easyspeak/pull/49)
- Add Nix flake for development and running on NixOS by @bittner in [#51](https://github.com/ctsdownloads/easyspeak/pull/51)
- Make Piper TTS model path configurable via env var by @bittner in [#52](https://github.com/ctsdownloads/easyspeak/pull/52)
- Run performance benchmarks for Whisper transcribe latency by @bittner in [#53](https://github.com/ctsdownloads/easyspeak/pull/53)
- Extract config module and move host-env setup into plugins by @bittner in [#54](https://github.com/ctsdownloads/easyspeak/pull/54)
- Fix No plugins directory found error by @gband85 in [#47](https://github.com/ctsdownloads/easyspeak/pull/47)
- Fix mousegrid error caused by duplicate import by @wkarl in [#48](https://github.com/ctsdownloads/easyspeak/pull/48)

### New Contributors

- @gband85 made their first contribution in [#47](https://github.com/ctsdownloads/easyspeak/pull/47)
- @wkarl made their first contribution in [#48](https://github.com/ctsdownloads/easyspeak/pull/48)

**Full Changelog**: [`0.1.0...0.2.0`](https://github.com/ctsdownloads/easyspeak/compare/0.1.0...0.2.0)

## 0.1.0 · Foundation · 2026-02-08

**Hello, Jarvis**

The first release of EasySpeak, published to PyPI as `easyspeak-linux`: a fully
local, Wayland-native voice control for Linux desktops. Say "Hey Jarvis" to drive
GNOME hands-free with wake-word activation, a mouse grid, browser control,
dictation, and an app launcher — no cloud and no accounts. This release also laid
the project's engineering foundation: a clean `src` layout, a GHA CI pipeline for
linting, typing, tests, and an automated PyPI publish, and a first suite of unit
tests covering the core engine, CLI, and browser plugin.

### What's Changed

- chore(gitignore): change gitignore file to `.gitignore` and remove pre-compiled python assets by @tulilirockz in [#11](https://github.com/ctsdownloads/easyspeak/pull/11)
- Add a Justfile, draft packaging setup, contributing docs by @bittner in [#14](https://github.com/ctsdownloads/easyspeak/pull/14)
- Organize Python modules with src layout, add first tests by @bittner in [#15](https://github.com/ctsdownloads/easyspeak/pull/15)
- Add CI pipeline for linting and tests by @bittner in [#17](https://github.com/ctsdownloads/easyspeak/pull/17)
- Allow all CI jobs to finish, reformat codebase, fix linting by @bittner in [#18](https://github.com/ctsdownloads/easyspeak/pull/18)
- Fix type check config, make tests run and pass by @bittner in [#19](https://github.com/ctsdownloads/easyspeak/pull/19)
- Update dependencies (uv.lock) by @bittner in [#20](https://github.com/ctsdownloads/easyspeak/pull/20)
- Add unit tests for core module (mostly EasySpeak class) by @bittner in [#21](https://github.com/ctsdownloads/easyspeak/pull/21)
- Run software safety related jobs only once a day by @bittner in [#23](https://github.com/ctsdownloads/easyspeak/pull/23)
- Refactor application entrypoint (CLI), add tests by @bittner in [#22](https://github.com/ctsdownloads/easyspeak/pull/22)
- Add tests for browser plugin by @bittner in [#25](https://github.com/ctsdownloads/easyspeak/pull/25)
- Update outdated package dependencies by @bittner in [#26](https://github.com/ctsdownloads/easyspeak/pull/26)
- Add tests for dictation plugin by @bittner in [#27](https://github.com/ctsdownloads/easyspeak/pull/27)
- Add tests for apps plugin by @bittner in [#28](https://github.com/ctsdownloads/easyspeak/pull/28)
- Add remaining tests for 100% coverage by @bittner in [#29](https://github.com/ctsdownloads/easyspeak/pull/29)
- Update outdated package dependencies by @bittner in [#30](https://github.com/ctsdownloads/easyspeak/pull/30)
- Build Python package, configure automatic release by @bittner in [#32](https://github.com/ctsdownloads/easyspeak/pull/32)

### New Contributors

- @tulilirockz made their first contribution in [#11](https://github.com/ctsdownloads/easyspeak/pull/11)
- @bittner made their first contribution in [#14](https://github.com/ctsdownloads/easyspeak/pull/14)

**Full Changelog**: [`0.1.0`](https://github.com/ctsdownloads/easyspeak/commits/0.1.0)
