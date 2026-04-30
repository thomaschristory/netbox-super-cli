default:
    @just --list

# Sync dependencies
sync:
    uv sync

# Run linters
lint:
    uv run ruff check nsc tests
    uv run ruff format --check nsc tests
    uv run mypy --strict nsc

# Auto-fix lint issues
fix:
    uv run ruff check --fix nsc tests
    uv run ruff format nsc tests

# Run all tests
test *args:
    uv run pytest {{args}}

# Run tests with coverage
test-cov:
    uv run pytest --cov=nsc --cov-report=term-missing

# Install pre-commit hooks
hooks:
    uv run pre-commit install

# Run all pre-commit hooks against all files
hooks-all:
    uv run pre-commit run --all-files

# Smoke-run the CLI
nsc *args:
    uv run nsc {{args}}

# Bump all pre-commit hook revs to latest
update:
    uv run pre-commit autoupdate
