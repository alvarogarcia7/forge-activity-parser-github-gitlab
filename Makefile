BUILDER   ?= perceval-builder
export HOST_UID ?= $(shell id -u)
export HOST_GID ?= $(shell id -g)

.PHONY: builder build collect up down logs shell test-egress clean-cache

## Create (once) a docker-container buildx builder with its own BuildKit cache
builder:
	@docker buildx inspect $(BUILDER) >/dev/null 2>&1 \
	  || docker buildx create --name $(BUILDER) --driver docker-container --bootstrap
	@echo "builder: $(BUILDER)"

## Build both images with layer cache in ./.buildx-cache
build: builder
	docker buildx bake -f docker-bake.hcl --builder $(BUILDER)

## Run one incremental collection (proxy is started automatically)
collect:
	mkdir -p data
	docker compose run --rm collector

up:
	docker compose up -d egress-proxy

down:
	docker compose down

logs:
	docker compose logs -f egress-proxy

shell:
	docker compose run --rm --entrypoint bash collector

## Prove the allowlist works: example.com must fail, github.com must succeed
test-egress:
	@docker compose run --rm --entrypoint sh collector -c '\
	  for u in https://github.com https://example.com; do \
	    if python -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=10)" $$u >/dev/null 2>&1; \
	    then echo "ALLOWED  $$u"; else echo "BLOCKED  $$u"; fi; done; \
	  echo "direct (bypassing proxy):"; \
	  env -u HTTPS_PROXY -u https_proxy python -c "import urllib.request; urllib.request.urlopen(\"https://github.com\", timeout=5)" >/dev/null 2>&1 \
	    && echo "  LEAK: direct egress works" || echo "  BLOCKED (no route out)"'

## Drop cached clones (next run re-emits full history)
clean-cache:
	docker volume rm perceval_perceval-cache
