# Contributing

Contributions welcome. The [source code][gh:source] lives on GitHub — fork it,
clone it, and send a pull request. Please [open an issue][gh:issues] first to
discuss larger changes, or start a thread in [GitHub Discussions][gh:discuss].

Areas that need work:

- More application integrations

## Planned Enhancements

- Window controls (maximize, minimize)
- Dictation focus detection fix
- Further GNOME integration for desktop control
- Verbal help per section (say "help browser" for spoken commands)
- Auto-discover installed apps for launcher
- Clipboard commands (copy, paste)

## Development

This project sports a [Justfile](https://just.systems/man/en/) to simplify
all local development activities, and for running the same tasks in the CI
pipeline.

```console
just
```

```console
just all
```

```console
UV_PYTHON=3.14 just pytest -q -x
```

```console
just clean
```

The setup uses [uv](https://docs.astral.sh/uv/concepts/) under the hood,
which transparently manages virtual environments and package installation.
uv also allows you to install several Python versions on your computer in
parallel. We use this to test against all supported Python versions.

### Prerequisites

First install the system build dependencies (PortAudio, GCC, Python 3.10–3.14, …)
as described under [Install from source](installation.md#install-from-source)
in the Installation guide — without them the build and run steps below will
fail.

Then install `uv` and `just`, e.g.

```console
python3 -m pip install uv
```

```console
uv tool install rust-just
```

### NixOS

Enter a development shell with all dependencies installed, or run the
application directly:

```console
nix develop
```

```console
nix run
```

To run directly off GitHub, with no clone required:

```console
nix run github:ctsdownloads/easyspeak
```

## Packaging & Version Numbers

The packaging configuration is in `pyproject.toml`, supported by
`MANIFEST.in`. Version numbers are generated automatically by
[setuptools-scm](https://setuptools-scm.readthedocs.io/) based on the
latest Git tag and the distance from that tag in number of commits.

We create releases by drafting a new release from the
[GitHub Releases][gh:releases]:

1. Extend the [CHANGELOG](changelog.md) by a release entry (see steps
   3 through 6 below for the content).
2. Click on <kbd>Draft a new release</kbd>.
3. Pick or enter the next suitable semantic version number in the tag
   selector (target: `main`).
4. Enter a title, e.g. "`<version>` · `<a-catchy-phrase>` ·
   `<date>`" (in GitHub Releases, leave out the date).
5. Click on <kbd>Generate release notes</kbd>.
6. Write a concise summary of one or two paragraphs at most.
7. Commit the CHANGELOG, e.g. with a "Release `<version>`" commit
   message.
8. Finally, press <kbd>Publish Release</kbd> (release label "Latest").

Publishing a release builds the `easyspeak` application packages and attaches
them; the `easyspeak-lang-*` data packages release separately, on their own
cadence.

### Language packs

A language pack changes only when its models in `pins.toml` do, so it is
versioned and released independently of the application. Its `[lang.<code>]`
`version` reflects that pack's pinned content and is bumped by `just update-pins`
whenever the models change (review it in `git diff pins.toml`). To release the
pack, push a matching `lang-<code>-<version>` tag:

```console
git tag lang-en-1.0.0
git push origin lang-en-1.0.0
```

This runs `release-lang.yml`, which verifies the tag's version against
`pins.toml`, builds the pack, and publishes it to a `lang-en-1.0.0` release.

[gh:source]: https://github.com/ctsdownloads/easyspeak
[gh:releases]: https://github.com/ctsdownloads/easyspeak/releases
[gh:issues]: https://github.com/ctsdownloads/easyspeak/issues
[gh:discuss]: https://github.com/ctsdownloads/easyspeak/discussions
