# EDI 837 Validator

[![CI](https://github.com/ryancheley/edi-837-validator/actions/workflows/ci.yml/badge.svg)](https://github.com/ryancheley/edi-837-validator/actions/workflows/ci.yml)

A web tool that validates whether an X12 **837P** (professional,
`005010X222A1`/`A2`) or **837I** (institutional, `005010X223A2`) health-care
claim file is constructed correctly, and — optionally — against a specific
payer/plan's **companion guide**. Companion guides are free-form PDFs, so the
app uses an LLM (Anthropic / Claude) to draft a structured rule set from the
PDF that a human reviews and activates before it's used in validation.

Django 6 + htmx + Tailwind, Postgres 18, containerized for deployment to
[Coolify](https://coolify.io/).

---

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Quick start (local)](#quick-start-local)
- [Using the app](#using-the-app)
- [Companion-guide extraction](#companion-guide-extraction)
- [`just` recipes](#just-recipes)
- [Tests, lint, and types](#tests-lint-and-types)
- [Docker](#docker)
- [Deploying to Coolify](#deploying-to-coolify)
- [Configuration](#configuration)
- [Validation findings](#validation-findings)
- [Project layout](#project-layout)
- [Data & privacy (PHI)](#data--privacy-phi)
- [Extending the spec](#extending-the-spec)
- [License](#license)

---

## Features

- **Structural + content validation** of 837P/837I: envelope and control-number
  balance (ISA↔IEA, GS↔GE, ST↔SE), loop structure, segment usage/order, element
  usage, data types, and code-value checks.
- **Full TR3 837P loop tree** with an **any-order sub-loop matcher** — real
  claims order sibling sub-loops freely (e.g. `2430` before `2410`), so the
  matcher keeps segments ordered but matches sibling loops in any order.
- **Companion-guide overlays** — a plan's PDF is extracted into a reviewable
  rule set that tightens Situational→Required and restricts code subsets on top
  of the base TR3 rules.
- **Human-in-the-loop** — LLM output is a *draft*; nothing affects validation
  until a reviewer activates it.
- **PHI-aware** — uploaded claim files are validated in memory and never stored.
- **Lean stack** — server-rendered Django + htmx + Tailwind (no Node, no SPA
  build), few dependencies.

## How it works

- **X12 engine** (`validator/x12/`) — pure Python, no Django imports, so it's
  unit-testable without the ORM. `parser.py` reads the self-describing
  delimiters from the fixed-width ISA header and splits into segments;
  `engine.py` walks the segments against a declarative **TR3 spec** (`specs/*.json`)
  and emits structured findings. "Full TR3 coverage" is a spec-data authoring
  effort — the engine is generic and complete; the JSON describes the loops,
  segments, elements, and code sets.
- **Companion guides** (`validator/guides/`) — `extract.py` sends the PDF to
  Claude as a document block and receives a schema-constrained rule set
  (`schema.py`). A reviewer edits/activates it; the active rule set is applied
  as an overlay via `schema.to_overlay()`.
- **Models** — `Plan`, `CompanionGuide` (uploaded PDF + extraction status),
  `RuleSet` (extracted rules + active flag), and `ValidationRun` (audit record;
  **no raw claim content**).

## Requirements

- **Python 3.15** and [**uv**](https://docs.astral.sh/uv/) (dependency and venv
  management).
- Optional: [**just**](https://just.systems/) for the task runner, **Docker** +
  Docker Compose for the full stack, and the standalone
  [**Tailwind CLI**](https://tailwindcss.com/blog/standalone-cli) if you edit
  templates/styles (no Node required).
- An **Anthropic API key** only if you want companion-guide extraction; core
  claim validation works without it.

## Quick start (local)

Local runs use **SQLite** automatically (no Postgres needed) because
`POSTGRES_DB` is unset.

With `just`:

```sh
just bootstrap     # copies .env.example -> .env, `uv sync`, migrate
just superuser     # create a login
just serve         # http://127.0.0.1:8000
```

Without `just`:

```sh
uv sync
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Then open http://127.0.0.1:8000 and log in. Try a validation immediately with
the bundled example claim at `samples/837P-all-fields.edi`.

> **Note:** `.env` is only consumed by Docker Compose. For bare `just serve` /
> `runserver`, config comes from your shell environment — the defaults are fine
> for local use, and you only need to export `ANTHROPIC_API_KEY`
> (+ `ANTHROPIC_WORKSPACE_ID` for user-scoped keys) to try extraction.

## Using the app

1. **Validate a claim** — on the home page, upload an 837P/837I file and
   (optionally) pick a plan to validate against. Results are grouped by loop
   with a severity-tagged finding per issue.
2. **Create a plan** — *Plans → New plan* (name + payer id).
3. **Upload a companion guide** — on the plan page, upload the payer's PDF.
   Extraction runs in the background; the status chip polls via htmx
   (`pending → extracting → needs review`).
4. **Review & activate** — open the draft rule set, edit the JSON if needed,
   tick *Activate*, and save. The active rule set now applies whenever that plan
   is selected during validation.

## Companion-guide extraction

Extraction calls the Anthropic API, so set a key:

```sh
export ANTHROPIC_API_KEY=sk-ant-...
# User-scoped keys (sk-ant-usr-…) also need the workspace they belong to:
export ANTHROPIC_WORKSPACE_ID=wrkspc_...
```

Workspace-scoped keys (`sk-ant-api03-…`) do not need `ANTHROPIC_WORKSPACE_ID`.
The model defaults to `claude-opus-4-8` (override with `ANTHROPIC_MODEL`).

## `just` recipes

Run `just` with no arguments to list everything. Common ones:

| Recipe | What it does |
|--------|--------------|
| `just serve` | Run the dev server (SQLite) |
| `just migrate` / `just makemigrations` | Database migrations |
| `just manage <cmd>` | Any `manage.py` command |
| `just superuser` | Create an admin user |
| `just css` | Rebuild Tailwind CSS from templates |
| `just test` | Run the test suite |
| `just lint` / `just format` / `just types` | ruff check / ruff format / ty |
| `just check` | The pre-push gate: lint + types + test |
| `just up` / `just down` | Start / stop the Docker stack |
| `just reset` | Stop stack and delete volumes (confirm-guarded) |
| `just console` | Shell into the web container |

## Tests, lint, and types

```sh
just check         # or: uv run pytest && uv run ruff check . && uv run ty check
```

Tests use **real objects, no mocks**: the engine is exercised with known-good
and deliberately-mutated 837P/837I fixtures (asserting specific finding IDs), a
real-world "all fields" 837P fixture, the companion-guide schema/overlay, and
view-level flows via the Django test client. CI runs the same gate on every PR.

## Docker

The multi-stage image builds the Tailwind CSS in a dedicated stage, installs
dependencies with `uv`, runs `collectstatic` (WhiteNoise serves the static
files), and launches gunicorn after applying migrations.

```sh
cp .env.example .env     # fill in SECRET_KEY, Postgres creds, ANTHROPIC_API_KEY
just up --build          # or: docker compose up --build
```

The stack is `web` (this app) + `db` (`postgres:18`) with named volumes
`pgdata` and `media`. A `/healthz/` endpoint backs the container health check.

## Deploying to Coolify

1. Point Coolify at this repo (it builds from the `Dockerfile`).
2. Set the environment variables from [`.env.example`](.env.example).
3. Mark the `pgdata` and `media` volumes **persistent**.
4. Expose the web port and set the health check to `/healthz/`.
5. Set `DEBUG=False`, a strong `SECRET_KEY`, and the real `ALLOWED_HOSTS` /
   `CSRF_TRUSTED_ORIGINS` for your domain.

## Configuration

All configuration is environment-driven.

| Variable | Purpose | Default |
|----------|---------|---------|
| `SECRET_KEY` | Django secret key | insecure dev key |
| `DEBUG` | Debug mode | `True` |
| `ALLOWED_HOSTS` | Comma-separated hostnames | `*` when `DEBUG`, else empty |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated origins | empty |
| `POSTGRES_DB` / `_USER` / `_PASSWORD` / `_HOST` / `_PORT` | Postgres 18 connection | SQLite fallback if `POSTGRES_DB` unset |
| `ANTHROPIC_API_KEY` | Enables companion-guide extraction | empty (extraction disabled) |
| `ANTHROPIC_WORKSPACE_ID` | Required for user-scoped (`sk-ant-usr-…`) keys | empty |
| `ANTHROPIC_MODEL` | Extraction model | `claude-opus-4-8` |
| `MAX_837_BYTES` | Max size of an uploaded 837 claim file | `10485760` (10 MB) |
| `MAX_UPLOAD_BYTES` | Django request-body cap (`DATA_UPLOAD_MAX_MEMORY_SIZE`); excludes file fields, so it does not limit uploaded 837/PDF files | `31457280` (30 MB) |
| `MEDIA_ROOT` | Where companion-guide PDFs are stored | `BASE_DIR/media` |

## Validation findings

Each finding carries a stable `rule_id`, a severity, and loop/segment/element
context:

| Prefix | Meaning |
|--------|---------|
| `ENV.*` | Envelope / control-number problems (missing ISA/GS/ST/SE, count or control-number mismatch) |
| `TXN.UNKNOWN` | Could not identify an 837P/837I transaction |
| `STRUCT.SEG.MISSING` | A required segment is absent |
| `STRUCT.LOOP.MISSING` | A required loop is absent |
| `STRUCT.UNEXPECTED` | A segment that doesn't fit the spec at that position |
| `ELEM.REQUIRED` | A required element/component is empty |
| `ELEM.MINLEN` / `ELEM.MAXLEN` | Element length out of range |
| `ELEM.TYPE` | Wrong data type (numeric/decimal/date/time) |
| `ELEM.CODE` | Value not in the allowed code set (base spec or plan overlay) |
| `PARSE.FATAL` | File could not be parsed as X12 |

## Project layout

```
core/                       Django project (settings, urls, wsgi/asgi)
validator/
  x12/                      pure-Python EDI engine (no Django)
    parser.py               raw X12 -> segments (ISA-driven delimiters)
    spec.py                 TR3 spec dataclasses + JSON loader
    engine.py               validation + any-order sub-loop matcher
    errors.py               ValidationError / ValidationResult
    specs/                  837P.json, 837I.json, codesets/
    tests/                  engine + all-fields fixture tests
  guides/                   companion-guide extraction
    extract.py              Anthropic PDF -> RuleSet
    schema.py               RuleSet schema + overlay conversion
  models.py                 Plan, CompanionGuide, RuleSet, ValidationRun
  views.py urls.py forms.py admin.py
  templates/                base, validate, plans, review, login
samples/                    example EDI files (837P-all-fields.edi)
assets/input.css            Tailwind source
static/                     vendored htmx + built app.css
Dockerfile  docker-compose.yml  justfile  .env.example
```

## Data & privacy (PHI)

X12 837 files contain protected health information. The app validates uploaded
claim files **in memory and does not persist them** — only structured results
and metadata are stored in `ValidationRun`. Companion-guide PDFs (not PHI) are
stored under `MEDIA_ROOT`. The app is login-gated; run it behind HTTPS with a
real `SECRET_KEY` and restricted `ALLOWED_HOSTS` in production. Companion-guide
extraction sends the PDF to the Anthropic API — review your agreements before
sending anything sensitive.

## Extending the spec

TR3 coverage lives in data, not code. To add or refine rules, edit the JSON
under `validator/x12/specs/` — add loops/segments, mark element `usage`
(`R`/`S`/`N`), set `data_type`, and reference shared code sets in
`specs/codesets/`. Add a fixture under `validator/x12/tests/fixtures/` and a
test asserting the expected finding IDs, then run `just check`.

## License

No license has been chosen yet; add one before distributing.
