#!/usr/bin/env bash
# Build the EasySpeak application bundle that the `easyspeak` .deb/.rpm ship at
# /opt/easyspeak. This is APP LOGIC ONLY — speech models live in separate
# `easyspeak-lang-*` packages (see packaging/stage-lang.sh).
#
# Runs in a clean glibc build environment (CI ubuntu-latest, or a container — see
# `just package-distro`), NOT on the host directly. It materialises a standalone
# CPython + venv at PREFIX; PREFIX must equal the final install path so the venv's
# absolute paths (shebangs, interpreter symlinks) stay valid on the target machine.
set -euo pipefail

PREFIX="${PREFIX:-/opt/easyspeak}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

command -v uv >/dev/null || { echo "error: uv is required (https://astral.sh/uv)" >&2; exit 1; }

# The bundled CPython version is pinned in pins.toml at the repo root.
PY_VERSION="${PY_VERSION:-$(uv run --no-project python - "$REPO_ROOT/pins.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as f:
    print(tomllib.load(f)["python"]["bundle"])
PY
)}"

echo ">> building wheel"
( cd "$REPO_ROOT" && uv build --wheel --out-dir "$REPO_ROOT/dist" )
WHEEL=$(ls -t "$REPO_ROOT"/dist/easyspeak_linux-*.whl | head -1)
echo "   $WHEEL"

echo ">> materialising standalone CPython $PY_VERSION at $PREFIX/python"
uv python install "$PY_VERSION"
SRC_PY=$(dirname "$(dirname "$(uv python find "$PY_VERSION")")")
rm -rf "$PREFIX"
mkdir -p "$PREFIX/python"
# -L dereferences symlinks so the REAL interpreter + libs land under $PREFIX.
# (plain cp -r keeps symlinks pointing back into uv's cache, breaking relocation.)
cp -rL "$SRC_PY"/. "$PREFIX/python/"

echo ">> creating venv from the bundled interpreter"
"$PREFIX/python/bin/python3" -m venv "$PREFIX/venv"

echo ">> installing app + runtime extras into the venv"
# piper-tts: provides the `piper` binary inside the venv (no system piper packaged).
uv pip install --python "$PREFIX/venv/bin/python" "$WHEEL" piper-tts

echo ">> rendering the GNOME-extension refresh unit for the bundled interpreter"
# `--preview service` prints the unit the bundled interpreter would install, so the
# packaged file is byte-identical to the runtime-generated one — baked with the
# bundle's stable interpreter and module paths (PREFIX is the final install path,
# so they're valid on the target). nfpm ships this to /usr/lib/systemd/user.
"$PREFIX/venv/bin/easyspeak" --preview service \
  > "$REPO_ROOT/dist/easyspeak-extension-refresh.service"

# Where language packages drop their models; config.py discovers them here.
mkdir -p "$PREFIX/models"

echo ">> trimming byte-compiled caches"
find "$PREFIX" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$PREFIX" -type f -name '*.pyc' -delete 2>/dev/null || true

# Fail loudly if anything in the bundle still points outside PREFIX — that would
# break on the user's machine where uv's cache does not exist.
echo ">> checking the bundle is self-contained"
ESCAPES=$(find "$PREFIX" -type l -exec readlink -f {} \; 2>/dev/null | grep -v "^$PREFIX" | sort -u || true)
if [ -n "$ESCAPES" ]; then
  echo "error: bundle has symlinks escaping $PREFIX:" >&2
  echo "$ESCAPES" | sed 's/^/  /' >&2
  exit 1
fi

echo ">> app bundle ready at $PREFIX ($(du -sh "$PREFIX" | cut -f1))"
