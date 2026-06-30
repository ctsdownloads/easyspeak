"""Publish the latest MkDocs build to the gh-pages site root.

mike archives every release/dev build under its own ``/<version>/`` path and
maintains ``versions.json`` plus ``.nojekyll`` at the root. To serve the latest
docs at clean, version-less URLs (``/easyspeak/installation/`` rather than
``/easyspeak/latest/installation/``), this copies a freshly built site into the
gh-pages root, replacing the previous canonical files but leaving mike's version
directories and metadata untouched.

Usage:
    python sync-docs-root.py <built-site-dir> <gh-pages-checkout>
"""

import json
import shutil
import sys
from pathlib import Path

# Root entries mike owns; never delete these when refreshing the canonical docs.
MIKE_FILES = {".nojekyll", "versions.json"}

# GitHub Pages reads the custom domain from `CNAME` at the publishing-branch root
PAGES_FILES = {"CNAME"}


def preserved_names(gh_pages: Path) -> set[str]:
    """Names of root entries to keep: git internals, mike metadata, versions."""
    keep = {".git"} | MIKE_FILES | PAGES_FILES
    versions = gh_pages / "versions.json"
    if versions.is_file():
        keep |= {entry["version"] for entry in json.loads(versions.read_text())}
    return keep


def main(site: str, gh_pages: str) -> None:
    """Replace the canonical root docs with a freshly built site.

    Drops the previous canonical files (home page, per-page dirs, assets, the
    old ``latest`` alias/redirect) while keeping mike's version snapshots in
    place, then lays down the new build at the root.
    """
    site_dir, root = Path(site), Path(gh_pages)
    keep = preserved_names(root)

    for entry in root.iterdir():
        if entry.name in keep:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    for entry in site_dir.iterdir():
        target = root / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
