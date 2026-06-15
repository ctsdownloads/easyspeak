# Contributing

Contributions welcome. Please open an issue first to discuss changes.

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
UV_PYTHON=3.12 just pytest -q -x
```

```console
just clean
```

The setup uses [uv](https://docs.astral.sh/uv/concepts/) under the hood,
which transparently manages virtual environments and package installation.
uv also allows you to install several Python versions on your computer in
parallel. We use this to test against all supported Python versions.

### Prerequisites

First install the system build dependencies (PortAudio, GCC, Python 3.12, …)
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

To publish a new release, push a new Git tag (e.g. 2.1.0) to GitHub.
