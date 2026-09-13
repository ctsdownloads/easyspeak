#!/usr/bin/env bash
# Build EasySpeak's data packages inside a clean container: the language packs
# (easyspeak-lang-<code>, noarch) and the speech model packs
# (easyspeak-stt-<code>). Unlike the application build, this needs no compiler
# and no CPython bundle — just uv, curl and nfpm — because a pack is nothing but
# downloaded speech models. Each pack is versioned from pins.toml, independent
# of the application release. Outputs to ./dist.
#
#   packaging/build-packs-in-docker.sh <kind> [<code> ...]   kind: lang | stt
#                                                            default: every pack of that kind
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Grep, not a TOML parser: this host side runs with nothing but docker + git.
IMAGE="${IMAGE:-$(grep -Po '^ubuntu_image = "\K[^"]+' "$REPO_ROOT/pins.toml")}"
KIND="${1:?usage: build-packs-in-docker.sh <lang|stt> [<code> ...]}"
shift
CODES="$*"
[ -n "$CODES" ] || CODES="$(grep -Po "^\[$KIND\.\K[^.\]]+(?=\]$)" "$REPO_ROOT/pins.toml" | tr '\n' ' ')"

command -v docker >/dev/null || { echo "error: docker is required" >&2; exit 1; }
mkdir -p "$REPO_ROOT/dist"

docker run --rm \
  -e KIND="$KIND" \
  -e CODES="$CODES" \
  -v "$REPO_ROOT:/src:ro" \
  -v "$REPO_ROOT/dist:/out" \
  "$IMAGE" bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl ca-certificates xz-utils >/dev/null
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    export PATH="$HOME/.local/bin:$PATH"

    # Install nfpm (static Go binary) at the version pinned in pins.toml.
    NFPM_VER=$(uv run --no-project python -c "import tomllib; print(tomllib.load(open(\"/src/pins.toml\", \"rb\"))[\"toolchain\"][\"nfpm\"])")
    curl -fsSL "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VER}/nfpm_${NFPM_VER}_linux_x86_64.tar.gz" \
      | tar -xz -C /usr/local/bin nfpm

    cp -r /src /build && cd /build

    # Each pack is stamped with its own pins.toml version, not the app release.
    for code in $CODES; do
      bash "packaging/stage-$KIND.sh" "$code"
      VERSION=$(uv run --no-project python -c "import tomllib; print(tomllib.load(open(\"pins.toml\", \"rb\"))[\"$KIND\"][\"$code\"][\"version\"])")
      export VERSION
      nfpm package -f "packaging/nfpm-$KIND-$code.yaml" -p deb -t /out
      nfpm package -f "packaging/nfpm-$KIND-$code.yaml" -p rpm -t /out
    done

    chmod a+rw /out/*-"$KIND"-*.deb /out/*-"$KIND"-*.rpm
  '

echo "built:"
ls -lh "$REPO_ROOT"/dist/*-"$KIND"-*.deb "$REPO_ROOT"/dist/*-"$KIND"-*.rpm
