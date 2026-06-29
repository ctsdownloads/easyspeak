"""Marks the GNOME Shell extension folder as the `easyspeak.gnome` package.

The extension's own sources (`extension.js`, `prefs.js`, `metadata.json`, the
`schemas/`) live here, in a top-level folder named after the extension's UUID so
newcomers find them without digging through the Python `src/` tree. Packaging maps
this folder to the `easyspeak.gnome` package (see `pyproject.toml`) so the files
ship in the wheel as package data; `core.gnome_extension.extension_source_dir`
resolves them by package name. This file is never copied into the installed
extension — only the assets in `EXTENSION_ASSETS` are.
"""
