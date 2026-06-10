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

        # openwakeword pulls speexdsp-ns which has no wheels for >=3.13,
        # so the project is currently pinned to 3.12.
        python = pkgs.python312;

        # .git is stripped from the flake source, so setuptools_scm can't
        # infer a version. Derive a PEP 440 "local version" from whatever
        # the flake knows (clean rev > dirty rev > nothing).
        pretendVersion =
          if self ? rev then
            "0.0.0+g${builtins.substring 0 8 self.rev}"
          else if self ? dirtyRev then
            "0.0.0+g${builtins.substring 0 8 self.dirtyRev}.dirty"
          else
            "0.0.0+nix";

        # Shared libraries that Python wheels dlopen at runtime.
        # NOTE: nix-ld (programs.nix-ld) does NOT cover these — it only injects
        # NIX_LD_LIBRARY_PATH for foreign executables that run through its loader
        # stub. These wheels are dlopen'd by a Nix-store Python, which uses the
        # normal glibc loader and only searches LD_LIBRARY_PATH/rpath.
        runtimeLibs = with pkgs; [
          portaudio # libportaudio.so for pyaudio
          stdenv.cc.cc.lib # libstdc++ for onnxruntime / faster-whisper
          zlib # libz.so.1
          # head-tracking extra: opencv-python's cv2.abi3.so links these.
          glib # libglib-2.0.so.0 + libgthread-2.0.so.0
          libGL # libGL.so.1
          libxcb # libxcb.so.1
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

        # FHS-style path baked into src/core/main.py for the wake chime;
        # doesn't exist on NixOS, so we sed-replace it during the sync step.
        chimeFhsPath = "/usr/share/sounds/freedesktop/stereo/message.oga";
        chimeNixPath = "${pkgs.sound-theme-freedesktop}/share/sounds/freedesktop/stereo/message.oga";

        # Piper voice model (Amy, US English) — fetched at build time so the
        # README's manual wget step isn't needed on NixOS. Piper expects the
        # .onnx and .onnx.json to live in the same directory, so we linkFarm
        # them together and point EASYSPEAK_PIPER_MODEL at the .onnx.
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

        easyspeak = pkgs.writeShellApplication {
          name = "easyspeak";
          runtimeInputs = [
            python
            pkgs.uv
            pkgs.coreutils
            pkgs.gnused
          ]
          ++ runtimeTools
          ++ buildTools;
          text = ''
            set -euo pipefail

            # uv needs a writable project directory; the flake source in
            # /nix/store is read-only, so mirror it under XDG_STATE_HOME.
            state_dir="''${XDG_STATE_HOME:-$HOME/.local/state}/easyspeak"
            src_dir="$state_dir/src"
            stamp="$src_dir/.nix-store-path"
            mkdir -p "$state_dir"

            if [ ! -f "$stamp" ] || [ "$(cat "$stamp" 2>/dev/null || true)" != "${./.}" ]; then
              rm -rf "$src_dir"
              cp -r --no-preserve=mode,ownership "${./.}" "$src_dir"
              sed -i 's|${chimeFhsPath}|${chimeNixPath}|g' "$src_dir/src/core/main.py"
              echo "${./.}" > "$stamp"
            fi

            export UV_PYTHON='${python}/bin/python'
            export UV_CACHE_DIR="''${XDG_CACHE_HOME:-$HOME/.cache}/easyspeak/uv"
            export UV_PROJECT_ENVIRONMENT="$state_dir/venv"
            export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_EASYSPEAK_LINUX='${pretendVersion}'
            export EASYSPEAK_PIPER_MODEL='${piperModelPath}'
            # pyaudio's setup.py hard-codes /usr/include and won't find
            # headers from the Nix store. CPPFLAGS/LDFLAGS are picked up by
            # distutils; C_INCLUDE_PATH/LIBRARY_PATH are read by gcc itself,
            # bypassing any Nix cc-wrapper variable-name quirks.
            export CPPFLAGS="-I${pkgs.portaudio}/include ''${CPPFLAGS:-}"
            export LDFLAGS="-L${pkgs.portaudio}/lib -Wl,-rpath,${pkgs.portaudio}/lib ''${LDFLAGS:-}"
            export C_INCLUDE_PATH="${pkgs.portaudio}/include''${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
            export LIBRARY_PATH="${pkgs.portaudio}/lib''${LIBRARY_PATH:+:$LIBRARY_PATH}"
            export LD_LIBRARY_PATH='${pkgs.lib.makeLibraryPath runtimeLibs}'":''${LD_LIBRARY_PATH:-}"

            cd "$src_dir"
            # --with openwakeword: pyproject.toml leaves it commented out
            # (see the note there about speexdsp-ns wheels), but main.py
            # imports it, so it must be present at runtime.
            exec uv run --with openwakeword easyspeak "$@"
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
          packages = [
            python
            pkgs.uv
            pkgs.just
            pkgs.eslint # JS linter for the GNOME Shell extension (see `just lint-js`)
            pkgs.nodejs # `node --test` for the extension's JS helpers (see `just test-js`)
          ]
          ++ runtimeTools
          ++ buildTools;
          shellHook = ''
            # mkShell's setup-hooks pile every Python app's (qutebrowser,
            # piper-tts, onnxruntime, ...) Python 3.13 site-packages onto
            # PYTHONPATH. uv inherits that into PEP 517 build subprocesses,
            # which then mix 3.13 setuptools into a 3.12 build and produce
            # wheels tagged with the wrong ABI. Strip both to keep uv pure.
            unset PYTHONPATH PYTHONHOME

            export LD_LIBRARY_PATH='${pkgs.lib.makeLibraryPath runtimeLibs}'":''${LD_LIBRARY_PATH:-}"
            export CPPFLAGS="-I${pkgs.portaudio}/include ''${CPPFLAGS:-}"
            export LDFLAGS="-L${pkgs.portaudio}/lib -Wl,-rpath,${pkgs.portaudio}/lib ''${LDFLAGS:-}"
            export C_INCLUDE_PATH="${pkgs.portaudio}/include''${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
            export LIBRARY_PATH="${pkgs.portaudio}/lib''${LIBRARY_PATH:+:$LIBRARY_PATH}"
            export UV_PYTHON='${python}/bin/python'
            export EASYSPEAK_PIPER_MODEL="''${EASYSPEAK_PIPER_MODEL:-${piperModelPath}}"
            # Only used when .git is missing (e.g. tarball checkout); a real
            # git tree lets setuptools_scm derive the proper version.
            export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_EASYSPEAK_LINUX="''${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_EASYSPEAK_LINUX:-${pretendVersion}}"
            echo "EasySpeak dev shell — Python $(python --version 2>&1 | awk '{print $2}'), uv $(uv --version | awk '{print $2}')"
            echo "Run:  uv run [--extra head-tracking] --with openwakeword easyspeak"
            echo "      just --list"
          '';
        };
      }
    );
}
