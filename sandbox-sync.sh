#!/usr/bin/env bash
# LOCAL SANDBOX ONLY - do not commit.
# Copies the repo (config/, code, .env) into named volumes for docker-compose.sandbox.yml,
# for hosts where the Docker daemon cannot see bind-mounted paths. Re-run after edits.
set -euo pipefail
cd "$(dirname "$0")"

# `./sandbox-sync.sh export`: copy collected output (pv-data) back to ./data on the host
if [[ "${1:-}" == export ]]; then
  mkdir -p data
  docker rm -f sandbox-helper >/dev/null 2>&1 || true
  docker create --name sandbox-helper -v pv-data:/src --entrypoint true perceval-collector:local >/dev/null
  docker cp sandbox-helper:/src/. data/
  docker rm -f sandbox-helper >/dev/null
  echo "exported pv-data -> ./data ($(find data -name '*.jsonl' | wc -l) jsonl files)"
  exit 0
fi

for v in pv-config pv-app pv-data; do docker volume create "$v" >/dev/null; done

# copy_into <volume> <tar-args...>: stream host files as a tar into a helper container's volume
copy_into() {
  local vol="$1"; shift
  docker rm -f sandbox-helper >/dev/null 2>&1 || true
  docker create --name sandbox-helper -v "$vol":/dst --entrypoint true perceval-collector:local >/dev/null
  tar "$@" | docker cp - sandbox-helper:/dst
  docker rm -f sandbox-helper >/dev/null
}

# allowlist for the proxy (mounted at /config)
copy_into pv-config -C config -cf - urls.txt
# code + config + .env for the collector (mounted at /app); excludes git metadata and outputs
copy_into pv-app --exclude=./.git --exclude=./.buildx-cache --exclude=./data -cf - .
echo "synced: pv-config (allowlist), pv-app (code, config, .env)"
