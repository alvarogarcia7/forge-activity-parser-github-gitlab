# syntax=docker/dockerfile:1.7
# Collector image: only the runtime (git, jq, Python venv built by `uv sync`).
# The application code and config come from the repo, bind-mounted read-only at /app.
ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.32

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------- builder: uv sync into /opt/venv from the lockfile ----------
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# Only the lockfile inputs are bind-mounted, so code changes never invalidate this
# layer; the uv download cache lives in a BuildKit cache mount.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv sync --frozen --no-dev --no-install-project

# ---------- runtime ----------
FROM python:${PYTHON_VERSION}-slim AS runtime
ARG UID=10001
ARG GID=10001

RUN rm -f /etc/apt/apt.conf.d/docker-clean
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates jq

RUN groupadd --gid ${GID} app \
 && useradd --uid ${UID} --gid ${GID} --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /cache /data \
 && chown app:app /cache /data

# venv stays root-owned: the non-root app user can run it but not modify it
COPY --from=builder /opt/venv /opt/venv

ENV PATH=/opt/venv/bin:$PATH \
    VIRTUAL_ENV=/opt/venv \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app

USER app
WORKDIR /data
ENTRYPOINT ["bash", "/app/app/collect.sh"]
