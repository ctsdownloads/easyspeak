"""Replace the gh-pages ``/latest/`` tree with redirect stubs to the site root.

The site root serves the current ``main`` docs at clean, version-less URLs (see
sync-docs-root.py). ``/latest/`` is kept only as a stable, addressable alias for
that same content: every page under it redirects to its root counterpart, with a
``rel=canonical`` pointing at the root so search engines treat the root as the
single canonical copy. GitHub Pages can't issue a real HTTP 301, so each stub is
a meta-refresh + canonical (the same technique mike's redirect aliases use) and
carries any URL fragment (e.g. ``#core.config``) across the hop.

Usage:
    python make-latest-redirects.py <built-site-dir> <latest-dir> [base-url]
"""

import shutil
import sys
from pathlib import Path

STUB = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Redirecting…</title>
    <link rel="canonical" href="{base}{target}">
    <meta name="robots" content="noindex">
    <meta http-equiv="refresh" content="0; url={target}">
    <script>location.replace("{target}" + location.hash + location.search)</script>
  </head>
  <body>Redirecting to <a href="{target}">{target}</a>…</body>
</html>
"""


def main(site: str, latest_dir: str, base: str = "https://easyspeak.dev") -> None:
    """Mirror every built page's path under `latest_dir` as a redirect to root."""
    site_dir, latest, base = Path(site), Path(latest_dir), base.rstrip("/")
    if latest.exists():
        shutil.rmtree(latest)
    for index in site_dir.rglob("index.html"):
        rel = index.parent.relative_to(site_dir).as_posix()
        target = "/" if rel == "." else f"/{rel}/"
        out = latest / "index.html" if rel == "." else latest / rel / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(STUB.format(base=base, target=target), encoding="utf-8")


if __name__ == "__main__":
    if not 3 <= len(sys.argv) <= 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
