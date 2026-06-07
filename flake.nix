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
        runtimeLibs = with pkgs; [
          portaudio # libportaudio.so for pyaudio
          stdenv.cc.cc.lib # libstdc++ for onnxruntime / faster-whisper
          zlib
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
        # GNOME Shell extension installer. Symlinks rather than copies so
        # uninstall is a clean rm and updates track the flake source.
        extUuid = "easyspeak-grid@local";
        installExtension = pkgs.writeShellApplication {
          name = "easyspeak-install-extension";
          runtimeInputs = [ pkgs.coreutils ];
          text = ''
            set -euo pipefail
            ext_dir="$HOME/.local/share/gnome-shell/extensions/${extUuid}"
            mkdir -p "$ext_dir"
            ln -sfn '${./extension.js}'  "$ext_dir/extension.js"
            ln -sfn '${./metadata.json}' "$ext_dir/metadata.json"
            echo "Installed (symlinked) extension at $ext_dir"

            if command -v gnome-extensions >/dev/null 2>&1; then
              if gnome-extensions enable '${extUuid}' 2>/dev/null; then
                echo "Enabled: ${extUuid}"
              else
                echo
                echo "GNOME Shell hasn't loaded the extension yet."
                echo "On Wayland you must LOG OUT and back in, then run:"
                echo "  gnome-extensions enable ${extUuid}"
              fi
            else
              echo "gnome-extensions CLI not on PATH; enable manually after re-login."
            fi
          '';
        };

        uninstallExtension = pkgs.writeShellApplication {
          name = "easyspeak-uninstall-extension";
          runtimeInputs = [ pkgs.coreutils ];
          text = ''
            set -euo pipefail
            ext_dir="$HOME/.local/share/gnome-shell/extensions/${extUuid}"
            if command -v gnome-extensions >/dev/null 2>&1; then
              gnome-extensions disable '${extUuid}' 2>/dev/null || true
            fi
            rm -rf "$ext_dir"
            echo "Removed $ext_dir"
            echo "Log out and back in to fully unload GNOME Shell extension."
          '';
        };

      in
      {
        packages = {
          default = easyspeak;
          easyspeak = easyspeak;
          install-extension = installExtension;
          uninstall-extension = uninstallExtension;
        };

        apps = {
          default = {
            type = "app";
            program = "${easyspeak}/bin/easyspeak";
          };
          install-extension = {
            type = "app";
            program = "${installExtension}/bin/easyspeak-install-extension";
          };
          uninstall-extension = {
            type = "app";
            program = "${uninstallExtension}/bin/easyspeak-uninstall-extension";
          };
        };

        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.uv
            pkgs.just
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
            echo "Run:  uv run --with openwakeword easyspeak"
            echo "      just --list"
          '';
        };
      }
    );
}
