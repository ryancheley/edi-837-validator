# syntax=docker/dockerfile:1

# --- Stage 1: build the Tailwind CSS with the standalone binary (no Node) --- #
FROM debian:bookworm-slim AS css
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ARG TAILWIND_VERSION=3.4.17
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in amd64) tw=x64 ;; arm64) tw=arm64 ;; *) echo "unsupported $arch" && exit 1 ;; esac \
    && curl -fsSL -o /usr/local/bin/tailwindcss \
       "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-${tw}" \
    && chmod +x /usr/local/bin/tailwindcss
COPY tailwind.config.js ./
COPY assets/ ./assets/
COPY validator/templates/ ./validator/templates/
RUN tailwindcss -c tailwind.config.js -i assets/input.css -o static/css/app.css --minify

# --- Stage 2: application image --- #
FROM python:3.15-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DJANGO_SETTINGS_MODULE=core.settings \
    PATH="/app/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
WORKDIR /app

# Install dependencies first for layer caching (project is non-packaged).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
COPY --from=css /app/static/css/app.css ./static/css/app.css

# Build manifest static files (needs DEBUG=False to use the manifest storage).
RUN SECRET_KEY=build-only DEBUG=False python manage.py collectstatic --noinput

# Media (companion-guide PDFs) lives in an app-owned dir mounted as a volume.
RUN useradd --create-home app && mkdir -p /app/media && chown -R app /app
USER app
EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120"]
