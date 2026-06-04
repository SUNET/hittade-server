# Show the available recipes.
default:
    @just --list

# Run the test suite (pytest, in-memory sqlite via hittade.settings_test).
test *ARGS:
    uv run pytest {{ARGS}}

# Lint with ruff.
lint:
    uv run ruff check .

# Format with black.
fmt:
    uv run black .
