{
  description = "EasySpeak — voice control for Linux desktops (fully local, Wayland-native)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        python = pkgs.python314;

        # Dedicated interpreter for dictation's AT-SPI helper: it needs PyGObject
        # + the AT-SPI typelib, which uv can't put in a wheel venv (EASYSPEAK_ATSPI_PYTHON).
        atspiPython = python.withPackages (ps: [ ps.pygobject3 ]);

        # Typelibs the helper's `gi` imports resolve at runtime (GLib/GObject/Gio,
        # GIRepository, Atspi).
        giTypelibPath = with pkgs; lib.makeSearchPath "lib/girepository-1.0" [
          glib
          gobject-introspection
          at-spi2-core
        ];

        # .git is stripped from the flake source, so derive a PEP 440 "local
        # version" for setuptools_scm (clean rev > dirty rev > nothing).
        pretendVersion =
          if self ? rev then
            "0.0.0+g${builtins.substring 0 8 self.rev}"
          else if self ? dirtyRev then
            "0.0.0+g${builtins.substring 0 8 self.dirtyRev}.dirty"
          else
            "0.0.0+nix";

        # Shared libraries that Python wheels dlopen at runtime. nix-ld does NOT
        # cover these: the wheels are dlopen'd by a Nix-store Python, whose glibc
        # loader only searches LD_LIBRARY_PATH/rpath, not NIX_LD_LIBRARY_PATH.
        runtimeLibs = with pkgs; [
          portaudio # libportaudio.so for pyaudio
          stdenv.cc.cc.lib # libstdc++ for onnxruntime / faster-whisper
          zlib # libz.so.1
          # head-tracking extra: opencv-python's cv2.abi3.so links these.
          glib # libglib-2.0.so.0 + libgthread-2.0.so.0
          libGL # libGL.so.1
          libxcb # libxcb.so.1
          at-spi2-core # libatspi.so.0 for the dictation helper's gi import
        ];

        # Tools the app shells out to (paplay, ffplay, piper, etc).
        runtimeTools = with pkgs; [
          ffmpeg # ffplay for TTS playback (NOT -headless; that strips SDL)
          pulseaudio # paplay for the wake-word chime
          piper-tts # TTS engine
          qutebrowser # browser plugin + "open browser" / help page
          sound-theme-freedesktop # /usr/share/sounds/freedesktop/...
        ];

        # Native toolchain needed when uv compiles wheels from source
        # (pyaudio is the usual culprit).
        buildTools = with pkgs; [
          gcc
          pkg-config
          portaudio
        ];

        # The chime/error-bell default to the FHS sounds dir, absent on NixOS;
        # EASYSPEAK_SOUNDS_DIR (commonEnv) redirects to the Nix store one.
        soundsNixDir = "${pkgs.sound-theme-freedesktop}/share/sounds/freedesktop/stereo";

        # Piper voice (Amy, US English), fetched at build time. Piper wants the
        # .onnx and .onnx.json side by side, so linkFarm them and point
        # EASYSPEAK_PIPER_MODEL at the .onnx.
        piperVoice = pkgs.linkFarm "piper-voice-en-US-amy-medium" [
          {
            name = "en_US-amy-medium.onnx";
            path = pkgs.fetchurl {
              url = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx";
              sha256 = "063c43bbs0nb09f86l4avnf9mxah38b1h9ffl3kgpixqaxxy99mk";
            };
          }
          {
            name = "en_US-amy-medium.onnx.json";
            path = pkgs.fetchurl {
              url = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json";
              sha256 = "0xvxjxk59byydx9gj6rdvvydp5zm8mzsrf9vyy6x6299sjs3x8lm";
            };
          }
        ];
        piperModelPath = "${piperVoice}/en_US-amy-medium.onnx";

        # Env shared by the `nix run` wrapper and the dev shell, so `uv run
        # easyspeak` behaves identically in both; `:-`/`:+` defaulting lets a
        # value the user already exported win. SETUPTOOLS_SCM matters only when
        # .git is missing (e.g. a tarball checkout); the pyaudio build flags
        # compile it against the Nix-store portaudio (CPPFLAGS/LDFLAGS feed
        # distutils, C_INCLUDE_PATH/LIBRARY_PATH feed gcc).
        commonEnv = with pkgs; ''
          export UV_PYTHON='${python}/bin/python'
          export EASYSPEAK_PIPER_MODEL="''${EASYSPEAK_PIPER_MODEL:-${piperModelPath}}"
          export EASYSPEAK_SOUNDS_DIR="''${EASYSPEAK_SOUNDS_DIR:-${soundsNixDir}}"
          export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_EASYSPEAK_LINUX="''${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_EASYSPEAK_LINUX:-${pretendVersion}}"
          export CPPFLAGS="-I${portaudio}/include ''${CPPFLAGS:-}"
          export LDFLAGS="-L${portaudio}/lib -Wl,-rpath,${portaudio}/lib ''${LDFLAGS:-}"
          export C_INCLUDE_PATH="${portaudio}/include''${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
          export LIBRARY_PATH="${portaudio}/lib''${LIBRARY_PATH:+:$LIBRARY_PATH}"
          export LD_LIBRARY_PATH='${lib.makeLibraryPath runtimeLibs}'":''${LD_LIBRARY_PATH:-}"
          export EASYSPEAK_ATSPI_PYTHON='${atspiPython}/bin/python3'
          export GI_TYPELIB_PATH='${giTypelibPath}'":''${GI_TYPELIB_PATH:-}"
        '';

        easyspeak = pkgs.writeShellApplication {
          name = "easyspeak";
          runtimeInputs = with pkgs; [
            python
            uv
            coreutils
            gnused
          ]
          ++ runtimeTools
          ++ buildTools;
          text = ''
            set -euo pipefail

            # uv needs a writable project dir, but /nix/store is read-only, so
            # mirror the source under XDG_STATE_HOME.
            state_dir="''${XDG_STATE_HOME:-$HOME/.local/state}/easyspeak"
            src_dir="$state_dir/src"
            stamp="$src_dir/.nix-store-path"
            mkdir -p "$state_dir"

            if [ ! -f "$stamp" ] || [ "$(cat "$stamp" 2>/dev/null || true)" != "${./.}" ]; then
              rm -rf "$src_dir"
              cp -r --no-preserve=mode,ownership "${./.}" "$src_dir"
              echo "${./.}" > "$stamp"
            fi

            export UV_CACHE_DIR="''${XDG_CACHE_HOME:-$HOME/.cache}/easyspeak/uv"
            export UV_PROJECT_ENVIRONMENT="$state_dir/venv"
            ${commonEnv}
            cd "$src_dir"
            exec uv run easyspeak "$@"
          '';
        };
      in
      {
        packages = {
          default = easyspeak;
          easyspeak = easyspeak;
        };

        apps = {
          default = {
            type = "app";
            program = "${easyspeak}/bin/easyspeak";
          };
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python
            uv
            just
            eslint # JS linter for the GNOME Shell extension (see `just lint-js`)
            nodejs # `node --test` for the extension's JS helpers (see `just test-js`)
            desktop-file-utils # desktop-file-validate for the launcher (see `just gate`)
            glib.dev # glib-compile-schemas for the extension's GSettings schema (see `just compile-schemas`)
            dpkg # dpkg-deb to read .deb contents (see tests/packaging/test_deb.sh)
            rpm # rpm to read .rpm contents (see tests/packaging/test_rpm.sh)
            unzip # read .whl contents (see tests/packaging/test_python_wheel.sh)
          ]
          ++ runtimeTools
          ++ buildTools;
          shellHook = ''
            # mkShell's setup-hooks pile other apps' site-packages onto
            # PYTHONPATH; uv would inherit them into PEP 517 builds and produce
            # wheels with the wrong ABI. Strip both to keep uv pure.
            unset PYTHONPATH PYTHONHOME

            ${commonEnv}
            echo "EasySpeak dev shell — Python $(python --version 2>&1 | awk '{print $2}'), uv $(uv --version | awk '{print $2}')"
            echo "Run:  uv run [--extra head-tracking] easyspeak"
            echo "      just --list"
          '';
        };
      }
    );
}
