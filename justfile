# EDI 837 Validator — task runner. Run `just` to see all recipes.

# Don't leak .env into local recipes: `just serve`/`just test` use the SQLite
# fallback, while the docker recipes read .env through docker compose itself.
set dotenv-load := false

# Path to the Tailwind standalone binary (override: `just tailwind=/path css`).
tailwind := "tailwindcss"

# --------------------------------------------------
# Utilities
# --------------------------------------------------

# Show available recipes when `just` is run with no arguments
[group('utils')]
@_default:
    just --list

# Format this justfile
[group('utils')]
@fmt:
    just --fmt --unstable

# --------------------------------------------------
# Setup & Environment
# --------------------------------------------------

# Install/sync all dependencies (incl. dev)
[group('setup')]
@install *ARGS:
    uv sync {{ ARGS }}

# Resolve and lock dependencies
[group('setup')]
@lock *ARGS:
    uv lock {{ ARGS }}

# Upgrade locked dependencies to their latest allowed versions
[group('setup')]
@upgrade:
    just lock --upgrade

# First-time setup: create .env, sync deps, migrate
[group('setup')]
bootstrap:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f ".env" ]; then
        cp .env.example .env
        echo ".env created from .env.example — fill in your secrets"
    fi
    uv sync
    just migrate

# --------------------------------------------------
# Django (local, via uv)
# --------------------------------------------------

# Run the development server (SQLite unless POSTGRES_DB is set)
[group('django')]
@serve *ARGS:
    uv run python manage.py runserver {{ ARGS }}

# Apply database migrations
[group('django')]
@migrate *ARGS:
    uv run python manage.py migrate {{ ARGS }}

# Create new migrations from model changes
[group('django')]
@makemigrations *ARGS:
    uv run python manage.py makemigrations {{ ARGS }}

# Run an arbitrary manage.py command, e.g. `just manage showmigrations`
[group('django')]
@manage *ARGS:
    uv run python manage.py {{ ARGS }}

# Create an admin user
[group('django')]
@superuser:
    uv run python manage.py createsuperuser

# Open a Django shell
[group('django')]
@shell *ARGS:
    uv run python manage.py shell {{ ARGS }}

# Collect static files (production/manifest build)
[group('django')]
@collectstatic *ARGS="--no-input":
    DEBUG=False uv run python manage.py collectstatic {{ ARGS }}

# --------------------------------------------------
# Assets
# --------------------------------------------------

# Rebuild the Tailwind CSS from templates
[group('assets')]
@css *ARGS:
    {{ tailwind }} -c tailwind.config.js -i assets/input.css -o static/css/app.css --minify {{ ARGS }}

# --------------------------------------------------
# Testing & Code Quality
# --------------------------------------------------

# Run the test suite
[group('quality')]
@test *ARGS:
    uv run pytest {{ ARGS }}

# Lint with ruff
[group('quality')]
@lint *ARGS:
    uv run ruff check {{ ARGS }} .

# Auto-fix lint issues
[group('quality')]
@fix:
    uv run ruff check --fix .

# Format code with ruff
[group('quality')]
@format *ARGS:
    uv run ruff format {{ ARGS }} .

# Type-check with ty
[group('quality')]
@types:
    uv run ty check

# The full pre-push gate: lint, types, tests
[group('quality')]
check: lint types test

# --------------------------------------------------
# Docker / Coolify stack
# --------------------------------------------------

# Build the images
[group('docker')]
@build *ARGS:
    docker compose build {{ ARGS }}

# Start the full stack (web + Postgres 18); `just up --build` to rebuild
[group('docker')]
@up *ARGS:
    docker compose up {{ ARGS }}

# Stop the stack (keep volumes)
[group('docker')]
@down *ARGS:
    docker compose down {{ ARGS }}

# View container logs
[group('docker')]
@logs *ARGS="--follow":
    docker compose logs {{ ARGS }}

# Show status of running containers
[group('docker')]
@ps:
    docker compose ps

# Restart services
[group('docker')]
@restart *ARGS:
    docker compose restart {{ ARGS }}

# Open a shell in the web container
[group('docker')]
console:
    #!/usr/bin/env bash
    if [ -n "$(docker compose ps --quiet web)" ]; then
        exec docker compose exec web /bin/bash
    else
        exec docker compose run --rm web /bin/bash
    fi

# Stop the stack and DELETE its volumes (wipes local DB + media)
[confirm("This deletes the local database and media volumes. Continue?")]
[group('docker')]
@reset:
    docker compose down -v
