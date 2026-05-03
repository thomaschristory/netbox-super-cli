default:
    @just --list

# Sync dependencies
sync:
    uv sync

# Run linters
lint:
    uv run ruff check nsc tests scripts
    uv run ruff format --check nsc tests scripts
    uv run mypy --strict nsc scripts

# Auto-fix lint issues
fix:
    uv run ruff check --fix nsc tests scripts
    uv run ruff format nsc tests scripts

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

# Run startup-time benchmark (NSC_BENCH=1 gate)
bench:
    NSC_BENCH=1 uv run pytest tests/benchmarks/ -v -s

# Run live-NetBox e2e suite (requires Docker)
e2e:
    docker compose -f tests/e2e/docker-compose.yml up -d
    tests/e2e/wait_for_netbox.sh
    NSC_E2E=1 NSC_URL=http://127.0.0.1:8080 NSC_TOKEN=0123456789abcdef0123456789abcdef01234567 uv run pytest tests/e2e/ -v; \
        rc=$?; \
        docker compose -f tests/e2e/docker-compose.yml down -v; \
        exit $rc

# Serve the MkDocs site locally at http://127.0.0.1:8000
docs:
    uv run mkdocs serve

# Build the MkDocs site (strict mode — fails on broken links, missing nav targets, etc.)
docs-build:
    uv run mkdocs build --strict
