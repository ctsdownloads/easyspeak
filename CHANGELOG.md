# Changelog

All notable changes to EasySpeak are documented here. This file is the
canonical, GitHub-independent record of releases. It is updated once per
release. The format loosely follows [Keep a Changelog](https://keepachangelog.com/),
and the project adheres to [Semantic Versioning](https://semver.org/).

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
