BUILDER ?= perceval-builder

# Container user = your host uid (so ./data stays writable), but never root.
_UID := $(shell id -u)
_GID := $(shell id -g)
export HOST_UID ?= $(if $(filter 0,$(_UID)),10001,$(_UID))
export HOST_GID ?= $(if $(filter 0,$(_GID)),10001,$(_GID))

.PHONY: help sync builder build collect up down logs shell test-egress clean-cache

## Show targets
help:
	@awk '/^## /{d=substr($$0,4); next} /^[a-zA-Z.\/_-]+:/{if(d){split($$1,t,":"); printf "  %-18s %s\n", t[1], d}; d=""}' Makefile

## Create a local .venv with uv (for running/debugging outside docker)
sync:
	uv sync --frozen

## Copy config/repos.txt.example -> config/repos.txt
config/repos.txt:
	cp config/repos.txt.example $@
	@echo "created $@, edit it to list your repositories"

## Copy .env.example -> .env (owner read-only)
.env:
	cp .env.example $@
	chmod 400 $@
	@echo "created $@ (mode 400). To edit: chmod u+w .env; edit; chmod 400 .env"

data:
	mkdir -p $@

## Create (once) a docker-container buildx builder with its own BuildKit cache
builder:
	@docker buildx inspect $(BUILDER) >/dev/null 2>&1 \
	  || docker buildx create --name $(BUILDER) --driver docker-container --bootstrap
	@echo "builder: $(BUILDER)"

## Build both images with layer cache in ./.buildx-cache
build: builder
	docker buildx bake -f docker-bake.hcl --builder $(BUILDER)

## Run one incremental collection (proxy is started automatically)
collect: config/repos.txt data
	docker compose run --rm collector

## Start the proxy in the background
up:
	docker compose up -d egress-proxy

## Stop everything
down:
	docker compose down

## Follow proxy access log (allowed/denied requests)
logs:
	docker compose logs -f egress-proxy

## Shell inside the collector (non-root, same network restrictions)
shell: data
	docker compose run --rm --entrypoint bash collector

## Prove the allowlist: github.com allowed, example.com and direct egress blocked
test-egress: data
	@docker compose run --rm --entrypoint sh collector -c '\
	  echo "user: $$(id -un) ($$(id -u))"; \
	  for u in https://github.com https://example.com; do \
	    if python -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=10)" $$u >/dev/null 2>&1; \
	    then echo "ALLOWED  $$u"; else echo "BLOCKED  $$u"; fi; done; \
	  printf "direct (bypassing proxy): "; \
	  env -u HTTPS_PROXY -u https_proxy python -c "import urllib.request; urllib.request.urlopen(\"https://github.com\", timeout=5)" >/dev/null 2>&1 \
	    && echo "LEAK: direct egress works" || echo "BLOCKED (no route out)"'

## Delete cached clones AND collected data (next run starts from scratch)
clean-cache:
	docker compose rm -fsv collector >/dev/null 2>&1 || true
	docker volume rm -f perceval_perceval-cache
	@if [ -d data ]; then find data -mindepth 1 -delete; echo "emptied ./data"; fi
