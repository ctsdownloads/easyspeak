#!/usr/bin/env bash
# Mirror the freshly built "latest" docs onto the version-less gh-pages root
# and rebuild the /latest redirects. Run after `just docs` (builds ./site)
# and the mike deploy that publishes "latest".
set -euo pipefail

trap 'git worktree remove --force gh-pages-root 2>/dev/null || true' EXIT
git worktree remove --force gh-pages-root 2>/dev/null || true
git fetch origin gh-pages
git worktree add gh-pages-root origin/gh-pages
python packaging/docs-sync-root.py site gh-pages-root
python packaging/docs-redirect-latest.py site gh-pages-root/latest
git -C gh-pages-root add -A
if git -C gh-pages-root diff --cached --quiet; then
    echo "Site root already up to date."
else
    git -C gh-pages-root commit -m "Mirror main docs to root; redirect /latest"
    git -C gh-pages-root push origin HEAD:gh-pages
fi
