# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12

# ---------- builder: resolve and install Python deps into a venv ----------
FROM python:${PYTHON_VERSION}-slim AS builder
ARG PERCEVAL_VERSION=1.6.2
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# pip cache lives in a BuildKit cache mount: survives rebuilds, never lands in a layer
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install "perceval==${PERCEVAL_VERSION}"

# ---------- runtime ----------
FROM python:${PYTHON_VERSION}-slim AS runtime
ARG UID=10001
ARG GID=10001

# apt caches in cache mounts; disable the docker-clean hook so they are kept
RUN rm -f /etc/apt/apt.conf.d/docker-clean
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates jq

RUN groupadd --gid ${GID} app \
 && useradd --uid ${UID} --gid ${GID} --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /cache /data \
 && chown app:app /cache /data

COPY --from=builder /opt/venv /opt/venv
COPY --chmod=0755 collect.sh /usr/local/bin/collect

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app

USER app
WORKDIR /data
VOLUME ["/cache", "/data"]
ENTRYPOINT ["/usr/local/bin/collect"]
