#!/usr/bin/env bash
# Runs the staged bundle's own interpreter, so it runs where the bundle is built
# (see packaging/stage-bundle.sh), not on any host.
set -euo pipefail

prefix="${1:-/opt/easyspeak}"

echo "The bundle leaves out Tcl/Tk, IDLE and pip"
stdlib=$("$prefix/python/bin/python3" -I -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')
for path in "$stdlib"/{tkinter,idlelib,turtledemo,ensurepip,turtle.py} \
    "$stdlib"/lib-dynload/_tkinter.* "$stdlib"/site-packages/pip \
    "$prefix"/python/lib/{libtcl,libtk}* "$prefix"/python/bin/{idle,pip}*; do
    [ ! -e "$path" ] || { echo "  PRESENT: $path" >&2; exit 1; }
done

echo "The bundle copies the interpreter once, not once per name"
[ -L "$prefix/python/bin/python3" ] || { echo "  NOT A LINK: python/bin/python3" >&2; exit 1; }

echo "EasySpeak and every library it installed load without them"
"$prefix/venv/bin/python" -I - <<'PY'
import importlib
import importlib.metadata
import pkgutil
import sys

import easyspeak

# Run by the system's Python, which has the GTK bindings the bundle doesn't.
SYSTEM_PYTHON = {"easyspeak.core.about", "easyspeak.plugins.dictation._atspi_insert"}

modules = [
    module.name
    for module in pkgutil.walk_packages(easyspeak.__path__, "easyspeak.")
    if module.name not in SYSTEM_PYTHON
]
modules += sorted(
    name
    for name in importlib.metadata.packages_distributions()
    if not name.startswith("_") and name != "easyspeak"
)
failed = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as exc:
        failed.append(f"  {name}: {exc!r}")
print(f"  imported {len(modules) - len(failed)} of {len(modules)} modules")
if failed:
    sys.exit("\n".join(["  FAILED:", *failed]))
PY

echo "The piper speech engine starts"
"$prefix/venv/bin/piper" --help >/dev/null

echo "✔  Bundle runs without Tcl/Tk, IDLE and pip."
