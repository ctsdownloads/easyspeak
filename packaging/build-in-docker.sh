#!/usr/bin/env bash
# Build the EasySpeak .deb and .rpm locally inside a clean ubuntu:24.04 container
# (mirrors the GitHub `release.yml` runner). Handy on NixOS, where the bundle's
# standalone CPython/manylinux wheels can't run on the host. Outputs to ./dist.
#
#   packaging/build-in-docker.sh [VERSION]   (default VERSION: 0.0.0)
set -euo pipefail

VERSION="${1:-0.0.0}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Grep, not a TOML parser: this host side runs with nothing but docker + git
# (the CI packages job has no uv), and the key is unique in pins.toml.
IMAGE="${IMAGE:-$(grep -Po '^ubuntu_image = "\K[^"]+' "$REPO_ROOT/pins.toml")}"

command -v docker >/dev/null || { echo "error: docker is required" >&2; exit 1; }
mkdir -p "$REPO_ROOT/dist"

docker run --rm \
  -e VERSION="$VERSION" \
  -e SETUPTOOLS_SCM_PRETEND_VERSION_FOR_EASYSPEAK_LINUX="$VERSION" \
  -v "$REPO_ROOT:/src:ro" \
  -v "$REPO_ROOT/dist:/out" \
  "$IMAGE" bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq build-essential portaudio19-dev curl ca-certificates xz-utils >/dev/null
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    export PATH="$HOME/.local/bin:$PATH"

    # Install nfpm (static Go binary) at the version pinned in pins.toml.
    NFPM_VER=$(uv run --no-project python -c "import tomllib; print(tomllib.load(open(\"/src/pins.toml\", \"rb\"))[\"toolchain\"][\"nfpm\"])")
    curl -fsSL "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VER}/nfpm_${NFPM_VER}_linux_x86_64.tar.gz" \
      | tar -xz -C /usr/local/bin nfpm

    cp -r /src /build && cd /build

    # Application package (amd64).
    PREFIX=/opt/easyspeak bash packaging/stage-bundle.sh
    nfpm package -f packaging/nfpm.yaml -p deb -t /out
    nfpm package -f packaging/nfpm.yaml -p rpm -t /out

    # Language data packages (noarch). Add more languages here as they appear.
    for lang in en; do
      bash packaging/stage-lang.sh "$lang"
      nfpm package -f "packaging/nfpm-lang-$lang.yaml" -p deb -t /out
      nfpm package -f "packaging/nfpm-lang-$lang.yaml" -p rpm -t /out
    done

    chmod a+rw /out/*.deb /out/*.rpm
  '

echo "built:"
ls -lh "$REPO_ROOT"/dist/*.deb "$REPO_ROOT"/dist/*.rpm
