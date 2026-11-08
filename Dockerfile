# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12

# ---------- Stage 1: build the virtualenv with Poetry ----------
FROM python:${PYTHON_VERSION}-slim AS builder

ARG POETRY_VERSION=2.1.3
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/tmp/poetry-cache \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /app

# Dependency files first: this layer is rebuilt only when dependencies change,
# not on every code edit.
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,target=/tmp/poetry-cache \
    poetry install --only main --no-root


# ---------- Stage 2: small runtime image ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    WEB_CONCURRENCY=2

# Run as a non-root user
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

# Poetry itself is NOT copied; only the finished virtualenv.
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

# The only writable location: uploads and generated reports
RUN mkdir -p /app/data/uploads /app/data/reports \
 && chown -R app:app /app/data

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status == 200 else 1)"

# Shell form so ${WEB_CONCURRENCY} expands; `exec` keeps uvicorn as PID 1 for clean shutdown.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]