"""GNOME Shell extension, packaged as `easyspeak.gnome` (via pyproject.toml).

Top-level folder named after the extension's UUID for easy spotting,
contains extension source files (JavaScript, JSON, and XML-based schemas).
Shipped as package data by the Python wheel;
`core.gnome_extension.extension_source_dir` resolves them by package name.
Only assets in `EXTENSION_ASSETS` are copied into the installed extension.
"""
