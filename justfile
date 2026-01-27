# Project development tasks
# Run 'just' or 'just --list' to see all available commands.

# Show this usage screen (default)
@help:
    just --list

# Run codestyle and safety checks, tests, packaging and cleanup
[group('lifecycle')]
all: codestyle safety test package clean

# Remove build artifacts and reports (use -v for verbose, -n for dry-run)
[group('lifecycle')]
clean *args:
    uvx pyclean . {{ args }} --debris all --erase tests/junit-report.xml --yes

# Run all code style checks (format, lint)
[group('codestyle')]
codestyle:
    -just format
    -just lint

# Consistent code style (use -- to apply, --diff to preview)
[group('codestyle')]
format *args=('--check'):
    uvx ruff format {{ args }}

# Ultra-fast linting (use -- for details, --fix to autocorrect)
[group('codestyle')]
lint *args=('--statistics'):
    uvx ruff check {{ args }}

# Static type checking (use --pretty for error details)
[group('safety')]
types *args:
    uv run --extra=mypy mypy src {{ args }}

# Run all safety checks (types, requirements, audit)
[group('safety')]
safety:
    -just types
    -just requirements
    -just audit

# Check project dependencies for known vulnerabilities
[group('safety')]
audit *args:
    uv run --with=pip-audit pip-audit --progress-spinner=off --skip-editable {{ args }}

# Check project dependencies are up-to-date (uv.lock)
[group('safety')]
requirements:
    uv lock --upgrade
    git diff --color --exit-code uv.lock

# Run test suite against all supported Python versions, show coverage
[group('tests')]
test *args:
    -UV_PYTHON=3.10 just pytest {{ args }}
    -UV_PYTHON=3.11 just pytest {{ args }}
    -UV_PYTHON=3.12 just pytest {{ args }}
    just coverage

# Run pytest (use -q for silent, -v for verbose, -s for debug, -x to stop on error)
[group('tests')]
pytest *args:
    uv run --with=coverage[toml] --with=pytest coverage run -m pytest {{ args }}

# Display test coverage report
[group('tests')]
coverage:
    uvx coverage[toml] xml
    uvx coverage[toml] report

# Run functional tests on a built package
[group('tests')]
functional: (clean '--quiet') (package '--quiet')
    # Python package should not contain tests (MANIFEST.in)
    ! unzip -l dist/easyspeak-*-py3-none-any.whl | grep tests
    ! tar tfz dist/easyspeak-*.tar.gz | grep tests
    # Python package should contain Core module
    tar tfz dist/easyspeak-*.tar.gz | grep -q core
    unzip -l dist/easyspeak-*-py3-none-any.whl | grep -q core

# Build package and check metadata
[group('release')]
package *args:
    uv build {{ args }}

# Verify package version is same as Git tag
[group('release')]
ensure_version_matches tag:
    python -c '\
    from importlib.metadata import version ;\
    ver = version("easyspeak") ;\
    tag = "{{ tag }}" ;\
    error = f"`{ver}` != `{tag}`" ;\
    abort = f"Package version does not match the Git tag ({error}). ABORTING." ;\
    raise SystemExit(0 if ver and tag and ver == tag else abort)'

# Build and upload package to personal package index (UV_PUBLISH_URL)
[group('release')]
publish: package
    just ensure_version_matches ${GIT_TAG}
    uv publish
