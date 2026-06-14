# flowmark dev recipes.
#
# Canonical entry point for `just`. The global pre-commit hook runs `just test`,
# so the real test suite must be reachable here. Recipes delegate to the
# Makefile, which remains the single source of truth for the underlying commands
# (see development.md). GitHub Actions call uv directly, not this file.

# Run the full test suite (pytest + golden tryscript tests).
test:
    @make test

# Run only the Python unit tests (fast inner loop).
test-unit:
    uv run pytest

# Run the golden CLI tests.
test-golden:
    @make test-golden

# Lint.
lint:
    @make lint

# Auto-format docs/markdown with flowmark.
format:
    @make format

# Build the distribution.
build:
    @make build
