# Project development tasks
# Run 'just' or 'just --list' to see all available commands.

# Show this usage screen (default)
@help:
    just --list --unsorted

# Run codestyle and safety checks, tests, packaging, docs, and cleanup
[group('lifecycle')]
all: codestyle safety test gate check-docs clean

# Remove build artifacts and reports (use -v for verbose, -n for dry-run)
[group('lifecycle')]
clean *args:
    uvx pyclean . {{ args }} --debris all --erase .benchmarks result results.json 'site/**/*' site --yes

# Run all code style checks (format, lint, js, yaml)
[group('codestyle')]
codestyle: format lint lint-js lint-yaml

# Check Python code style (use -- to apply, --diff to preview)
[group('codestyle')]
format *args=('--check'):
    uvx ruff format {{ args }}

# Lint the Python code (use -- for details, --fix to autocorrect)
[group('codestyle')]
lint *args=('--statistics'):
    uvx ruff check {{ args }}

# Lint the GNOME Shell extension JS (use --fix to autocorrect)
[group('codestyle')]
lint-js *args:
    eslint src/extension.js src/extension-helpers.js {{ args }}

# Check YAML formatting: minimal indent, final newline (config in .yamllint.yaml)
[group('codestyle')]
lint-yaml *args:
    git ls-files '*.yml' '*.yaml' | xargs uvx yamllint -s {{ args }}

# Static type checking (use --pretty for error details)
[group('safety')]
types *args:
    uv run --extra=mypy mypy src {{ args }}

# Run all safety checks (types, requirements, audit)
[group('safety')]
safety: types requirements audit

# Check project dependencies for known vulnerabilities
[group('safety')]
audit *args:
    uv run --with=pip-audit pip-audit --progress-spinner=off --skip-editable {{ args }}

# Check project dependencies are up-to-date (uv.lock)
[group('safety')]
requirements:
    uv lock --upgrade
    git diff --color --exit-code uv.lock

# Run test suite and show coverage (unit tests, integration, acceptance)
[group('tests')]
test: test-js pytest coverage integration acceptance

# Unit-test the GNOME Shell extension's pure JS helpers (needs node >= 22.5)
[group('tests')]
test-js *args:
    node --experimental-test-coverage --test-coverage-include='src/**' \
        --test-coverage-lines=99 --test-coverage-branches=99 --test-coverage-functions=99 \
        --test tests/js/*.test.js {{ args }}

# Run test suite against all supported Python versions, show coverage
[group('tests')]
test-pythons *args:
    -UV_PYTHON=3.10 just pytest {{ args }}
    -UV_PYTHON=3.11 just pytest {{ args }}
    -UV_PYTHON=3.12 just pytest {{ args }}
    -UV_PYTHON=3.13 just pytest {{ args }}
    just coverage

# Run pytest (use -q for silent, -v for verbose, -s for debug, -x to stop on error)
[group('tests')]
pytest *args:
    uv run --extra=unittest coverage run -m pytest {{ args }}

# Display test coverage report
[group('tests')]
coverage:
    uvx coverage[toml] xml
    uvx coverage[toml] report

# Run integration tests (exercise external commands for real)
[group('tests')]
integration *args=('-v'):
    uv run --extra=integration pytest tests/integration {{ args }}

# Run acceptance tests (Gherkin scenarios via pytest-bdd)
[group('tests')]
acceptance *args=('-v'):
    uv run --extra=acceptance pytest tests/acceptance {{ args }}

# Run Whisper benchmarks (writes results.json for bencher.dev)
[group('tests')]
benchmark *args:
    uv run --extra=benchmark pytest tests/benchmarks/ \
        --benchmark-json=results.json {{ args }}

# Run all QA checks for the generated documentation (docstrings, markdown, links)
[group('docs')]
check-docs: lint-docstrings lint-md check-links

# Check built docs and README/CONTRIBUTING for dead external links (network)
[group('docs')]
check-links *args: docs
    # The README and CONTRIBUTING are GitHub-facing and link out to the live docs
    # site; render them to HTML so linkchecker validates those links too (it can't
    # parse Markdown). They live outside site/ so a docs deploy never picks them up.
    mkdir -p build/linkcheck
    uvx --from markdown markdown_py README.md > build/linkcheck/readme.html
    uvx --from markdown markdown_py CONTRIBUTING.md > build/linkcheck/contributing.html
    # --ignore-url drops material's 404-page root-absolute links (only valid once served under the Pages path);
    # --user-agent avoids linkchecker's "Mozilla" default, which freedesktop.org's WAF answers with 418.
    uvx linkchecker --check-extern --no-warnings --ignore-url '^file:///easyspeak/' --user-agent LinkChecker {{ args }} \
        site/index.html build/linkcheck/readme.html build/linkcheck/contributing.html

# Guard docstrings against reST markup (mkdocstrings renders Markdown, not reST)
[group('docs')]
lint-docstrings:
    #!/usr/bin/env sh
    bt=$(printf '\140')
    if git ls-files 'src/**/*.py' | xargs grep -nE ":(func|meth|class|mod|data|attr|ref|exc|obj):$bt|$bt$bt"; then
        echo "error: reST markup in docstrings — use Markdown: backtick-code and [text][full.path] links." >&2
        exit 1
    fi

# Lint Markdown structure in all tracked *.md (lenient on style; config in pyproject.toml)
[group('docs')]
lint-md *args:
    git ls-files '*.md' | xargs uvx --from pymarkdownlnt pymarkdown {{ args }} scan

# Build the docs (use `serve` to serve at http://127.0.0.1:8000 with live-reload)
[group('docs')]
docs *args=('build --strict'):
    uv run --extra=docs mkdocs {{ args }}

# Publish versioned docs via mike (CI; e.g. `just docs-publish deploy --push dev`)
[group('docs')]
docs-publish *args:
    uv run --extra=docs mike {{ args }}

# Build package and check metadata
[group('release')]
package *args:
    uv build {{ args }}

# Runs plausibility checks against freshly built packages
[group('release')]
gate: (clean '--quiet') (package '--quiet')
    # Desktop launcher to be shipped in the .deb/.rpm must be valid.
    desktop-file-validate data/easyspeak.desktop
    # Python package must not contain markdown, tests and dev tooling configuration
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep C.*\.md
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep docs
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep package.json
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep tests
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep .lock
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep .mjs
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep .nix
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep .yaml
    ! unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep .yml
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep C.*\.md
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep docs
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep package.json
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep tests
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep .lock
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep .mjs
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep .nix
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep .yaml
    ! tar tfz dist/easyspeak_linux-*.tar.gz | grep .yml
    # Python package should contain Core module and plugins
    tar tfz dist/easyspeak_linux-*.tar.gz | grep -q core
    tar tfz dist/easyspeak_linux-*.tar.gz | grep -q plugins
    unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep -q core
    unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep -q plugins
    # Python package should bundle launcher and Shell extension assets.
    tar tfz dist/easyspeak_linux-*.tar.gz | grep -q easyspeak.desktop
    tar tfz dist/easyspeak_linux-*.tar.gz | grep -q easyspeak-extension-refresh.service.in
    tar tfz dist/easyspeak_linux-*.tar.gz | grep -q extension.js
    tar tfz dist/easyspeak_linux-*.tar.gz | grep -q extension-helpers.js
    tar tfz dist/easyspeak_linux-*.tar.gz | grep -q metadata.json
    unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep -q easyspeak.desktop
    unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep -q easyspeak-extension-refresh.service.in
    unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep -q extension.js
    unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep -q extension-helpers.js
    unzip -l dist/easyspeak_linux-*-py3-none-any.whl | grep -q metadata.json
    @echo "✔  Python packaging looks good."

# Verify package version is same as Git tag
[group('release')]
ensure_version_matches tag:
    python -c '\
    from importlib.metadata import version ;\
    ver = version("easyspeak-linux") ;\
    tag = "{{ tag }}" ;\
    error = f"`{ver}` != `{tag}`" ;\
    abort = f"Package version does not match the Git tag ({error}). ABORTING." ;\
    raise SystemExit(0 if ver and tag and ver == tag else abort)'

# Build and upload package to personal package index (UV_PUBLISH_URL)
[group('release')]
publish: package
    just ensure_version_matches ${GIT_TAG}
    uv publish

# Build the /opt/easyspeak app bundle (CI/container only, not the host)
[group('packaging')]
stage-bundle:
    bash packaging/stage-bundle.sh

# Stage a language pack's speech models, e.g. `just stage-lang en`
[group('packaging')]
stage-lang code:
    bash packaging/stage-lang.sh {{ code }}

# Build .deb and .rpm locally in a clean ubuntu container -> ./dist
[group('packaging')]
package-native version='0.0.0':
    bash packaging/build-in-docker.sh {{ version }}
