# Packaging tests

Content checks for all distributable artifacts the project provides. The
tests don't install anything or run the code — each one builds the package,
lists its contents, and asserts that the right files are *present* and that
the wrong files are *absent* (no markdown, docs, tests, or dev-tooling
config to leak into a release).

Unlike the rest of `tests/`, these are plain **bash scripts**, not pytest —
they reach for `dpkg-deb`, `rpm`, `tar`, and `unzip` rather than importing
`easyspeak`.

## How they run

Each script needs its artifact built first, so they're driven through `just`
recipes that build, then verify. The distro packages build in a clean Ubuntu
container (Docker required); the Python packages build with `uv`:

```sh
just check-deb-package        # build-in-docker, then test_deb.sh
just check-rpm-package        # build-in-docker, then test_rpm.sh
just check-distro-packages    # both of the above, sharing one container build
just check-python-packages    # uv build, then test_python_wheel.sh + test_python_sdist.sh
```

Each script picks the newest matching artifact out of `dist/` and exits
non-zero on the first missing (or forbidden) path.

## Layout

```sh
test_deb.sh            # dpkg-deb --contents: launcher, units, extension + schema present
test_rpm.sh            # rpm --query --list: same contract for the .rpm
test_python_wheel.sh   # unzip -Z1: core + plugins + extension present, docs/tests absent
test_python_sdist.sh   # tar tzf: same contract for the source tarball
```
