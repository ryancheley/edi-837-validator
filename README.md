# EDI 837 Validator

Validates that an X12 **837I** (institutional, 005010X223A2) or **837P**
(professional, 005010X222A1) claim file is constructed correctly, and optionally
against a specific payer/plan's **companion guide** requirements. Companion
guides are free-form PDFs; an LLM (Anthropic / Claude) drafts a structured rule
set from the PDF that a human reviews before it is used in validation.

Django 6 + htmx + Tailwind, Postgres 18, deployed to Coolify via Docker.

## How it works

- **X12 engine** (`validator/x12/`) — pure Python, no Django. Parses the
  interchange (delimiters are self-describing in the fixed-width ISA header),
  then walks it against a declarative TR3 spec (`specs/*.json`): envelope/control
  balance, loop structure, segment usage/order, element usage, data types, and
  code values. "Full TR3 coverage" is a spec-data authoring effort — the engine
  is complete; the JSON specs are seeded for the envelope + core loops and
  extended over time.
- **Companion guides** (`validator/guides/`) — `extract.py` sends the PDF to
  Claude and gets back a RuleSet matching `schema.py` (structured outputs).
  A reviewer edits/activates it; the active RuleSet is applied as an overlay
  (tighten Situational→Required, restrict code subsets).
- **PHI** — uploaded 837 files are validated in memory and **never stored**;
  only structured results/metadata are persisted (`ValidationRun`).

## Local development

```sh
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Rebuild the CSS after editing templates (standalone Tailwind binary, no Node):

```sh
tailwindcss -c tailwind.config.js -i assets/input.css -o static/css/app.css --minify
```

Without `POSTGRES_DB` set, the app uses SQLite — convenient for local runs and
tests. Set `ANTHROPIC_API_KEY` to enable companion-guide extraction.

## Tests, lint, types

```sh
uv run pytest        # engine, schema, and view tests (real objects, no mocks)
uv run ruff check .
uv run ty check
```

## Docker / Coolify

```sh
cp .env.example .env   # fill in secrets; Postgres creds; ANTHROPIC_API_KEY
docker compose up --build
```

The image builds the Tailwind CSS in a dedicated stage, installs deps with `uv`,
runs `collectstatic` (WhiteNoise serves static), and starts gunicorn after
applying migrations. On **Coolify**: set the env vars from `.env.example`, mark
the `pgdata` and `media` volumes persistent, expose the web port, and point the
health check at `/healthz/`.

## Configuration (environment)

| Var | Purpose |
|-----|---------|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Django core |
| `POSTGRES_DB` / `_USER` / `_PASSWORD` / `_HOST` / `_PORT` | Postgres 18 (SQLite fallback if `POSTGRES_DB` unset) |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Companion-guide extraction (default `claude-opus-4-8`) |
| `MAX_UPLOAD_BYTES` | Upload size cap |
