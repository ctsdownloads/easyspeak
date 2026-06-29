# Project development tasks
# Run 'just' or 'just --list' to see all available commands.

# Show this usage screen (default)
@help:
    just --list --unsorted

# Run codestyle and safety checks, tests, packaging, docs, and cleanup
[group('lifecycle')]
all: codestyle safety test check-docs check-desktop-integration compile-schemas check-python-packages check-deb-package check-rpm-package clean

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
    eslint src/extension.js src/extension-helpers.js src/prefs.js {{ args }}

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
    -uvx coverage[toml] xml
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
    # Skip the 404 page (material renders its links absolute from site_url, so they
    # 404 on the filesystem) and bencher.dev (403s every bot); the non-default
    # user-agent dodges freedesktop's WAF (418 to "Mozilla").
    uvx linkchecker --check-extern --no-warnings \
        --ignore-url '/404\.html' \
        --ignore-url 'bencher\.dev' \
        --user-agent LinkChecker {{ args }} \
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

# Build the Debian package and verify its contents
[group('release')]
check-deb-package: (package-native)
    bash tests/packaging/test_deb.sh

# Build the RedHat package and verify its contents
[group('release')]
check-rpm-package: (package-native)
    bash tests/packaging/test_rpm.sh

# Build the wheel and sdist, then verify their contents
[group('release')]
check-python-packages: (package '--quiet')
    bash tests/packaging/test_python_wheel.sh
    bash tests/packaging/test_python_sdist.sh

# Build Python package and check its metadata renders for PyPI
[group('release')]
package *args:
    uv build {{ args }}
    uvx twine check dist/*.whl dist/*.tar.gz

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

# Check GNOME desktop integration files
[group('packaging')]
check-desktop-integration:
    desktop-file-validate data/easyspeak.desktop
    desktop-file-validate data/easyspeak-autostart.desktop

# Recompile the bundled GSettings schema after editing the .gschema.xml
[group('packaging')]
compile-schemas:
    glib-compile-schemas --strict src/schemas

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
