# docker buildx bake            -> build both images into the local docker store
# docker buildx bake --print    -> show resolved config
#
# Cache: BuildKit layer cache is exported to ./.buildx-cache (mode=max = every
# stage, incl. the builder venv), plus pip/apt/apk cache mounts in the Dockerfiles.
# On CI, set CACHE_BACKEND=gha (GitHub Actions) or use a registry ref instead.

variable "HOST_UID"      { default = "10001" }
variable "HOST_GID"      { default = "10001" }
variable "CACHE_BACKEND" { default = "local" }   # local | gha
variable "CACHE_DIR"     { default = ".buildx-cache" }

function "cache_from" {
  params = [name]
  result = CACHE_BACKEND == "gha" ? ["type=gha,scope=${name}"] : ["type=local,src=${CACHE_DIR}/${name}"]
}
function "cache_to" {
  params = [name]
  result = CACHE_BACKEND == "gha" ? ["type=gha,scope=${name},mode=max"] : ["type=local,dest=${CACHE_DIR}/${name},mode=max"]
}

group "default" {
  targets = ["collector", "egress-proxy"]
}

target "collector" {
  context    = "."
  dockerfile = "Dockerfile"
  target     = "runtime"
  tags       = ["perceval-collector:local"]
  args = {
    UID = HOST_UID
    GID = HOST_GID
  }
  cache-from = cache_from("collector")
  cache-to   = cache_to("collector")
  output     = ["type=docker"]
}

target "egress-proxy" {
  context    = "./proxy"
  tags       = ["perceval-egress-proxy:local"]
  cache-from = cache_from("egress-proxy")
  cache-to   = cache_to("egress-proxy")
  output     = ["type=docker"]
}
