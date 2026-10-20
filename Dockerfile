# Image for the answer scorer API.
# Built only on GitHub Actions runners (ci.yml builds it, deploy.yml builds and pushes it).
# Nothing here needs a secret, and no build argument carries a value.

# uv comes from its official image, pinned to an exact version.
FROM ghcr.io/astral-sh/uv:0.13.3 AS uv

FROM python:3.12.15-slim-trixie

# uv settings for the build: compile bytecode once, copy files instead of linking,
# keep no cache in the image, and never download another Python.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never

# A fixed, unprivileged account: the app never runs as root.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first: it is rebuilt only when the lock file changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the application itself. README.md is part of the package metadata.
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Fail the build, not the deploy, if the package or the server is missing.
RUN /app/.venv/bin/python -c "import importlib.util as u, sys; missing = [m for m in ('scorer', 'uvicorn') if u.find_spec(m) is None]; sys.exit('not installed: ' + ', '.join(missing) if missing else 0)"

# Files the app reads at run time, relative to SCORER_ROOT.
COPY rubrics ./rubrics
COPY prompts ./prompts
COPY config ./config

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SCORER_ROOT=/app

USER 10001:10001

EXPOSE 8000

# No HEALTHCHECK on purpose: Container Apps probes /healthz and /readyz itself.
CMD ["uvicorn", "scorer.api:app", "--host", "0.0.0.0", "--port", "8000"]
