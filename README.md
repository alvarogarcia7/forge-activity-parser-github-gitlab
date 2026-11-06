# Forge (Github, Gitlab) Activity Parser

Incremental git activity collector: ([Perceval](https://github.com/chaoss/grimoirelab-perceval)) → JSONL,
running as non-root with egress limited to an allowlist.

```
collector ──(internal network, no route out)──> egress-proxy (squid) ──> hosts in config/urls.txt
```

## Quick start

```bash
make build              # buildx builder 'perceval-builder' + both images, cached
make config/repos.txt   # from config/repos.txt.example, then edit it
make .env               # from .env.example (mode 400), then add tokens if needed
make test-egress        # github.com ALLOWED, example.com BLOCKED, direct BLOCKED
make collect            # repeat any time: only new commits are appended
make help               # all targets
```

## Configuration

| File | Tracked | Purpose |
|---|---|---|
| `config/repos.txt.example` | yes | Template for the repo list |
| `config/repos.txt` | **no** | Your repo list (see format below) |
| `config/urls.txt` | yes | Egress allowlist, mounted read-only into the proxy |
| `.env.example` | yes | Template for secrets |
| `.env` | **no** | Tokens + options, read-only (mode 400 + read-only mount) |

### `config/repos.txt`

One https clone URL per line; `#` starts a comment and blank lines are ignored.

```
https://github.com/octocat/Hello-World.git
# private: needs GITHUB_TOKEN
https://github.com/<user>/<repo>.git
# private: needs GITLAB_TOKEN
https://gitlab.com/<group>/<project>.git
```

- Each URL's host must be allowed in `config/urls.txt`, or the clone fails with a proxy 403.
- Don't put tokens in URLs. Use `.env`; the tokens are injected via git config env vars, so they never end up in the output.
- Each repo produces `data/commits/<host>__<owner>__<repo>.jsonl`.
- Removing a line stops future collection for that repo; its existing JSONL and clone are kept.

### `.env`

Create it with `make .env`, which copies `.env.example` and sets mode 400. Every variable is optional;
with an empty `.env`, public repos still work.

| Variable | Used by | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | collect.sh | Private GitHub repos. Fine-grained token with *Contents: Read-only* on the listed repos (or classic `repo` scope) |
| `GITLAB_TOKEN` | collect.sh | Private gitlab.com repos. Scope `read_repository` |
| `AUTHOR_REGEX` | collect.sh | Case-insensitive regex on `Name <email>`. When set, also rebuilds `data/mine.jsonl` |
| `HOST_UID`, `HOST_GID` | compose / build | Override the non-root `app` user's uid/gid. Default: your host ids, never 0 |

Example:

```
# Fine-grained PAT, Contents: Read-only
GITHUB_TOKEN=github_pat_11AAAA...

# read_repository scope
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# My name or e-mail as it appears in commits
AUTHOR_REGEX=alvaro|alvarogarcia7
```

Format rules:

- One `KEY=VALUE` per line, with no spaces around `=`.
- **Comments go on their own line, above the value.** A trailing `# ...` would become part of the value, so
  `collect.sh` stops with an error naming the key.
- Quotes are optional. A variable already set in the environment wins over `.env`.

`collect.sh` parses `.env` without executing it, and the values are not passed through compose `environment:`,
so they don't show up in `docker inspect`. To edit: `chmod u+w .env`, edit, `chmod 400 .env`.

### `config/urls.txt`

`github.com` = exact host, `.github.com` = host + subdomains, `https://host/path` = host only.
After editing, run `docker compose restart egress-proxy`.

## Layout and mounts

| Collector path | Source | Mode |
|---|---|---|
| `/app` | the repo (code, `config/`, `.env`) | **read-only** |
| `/data` | `./data` | read-write (JSONL output) |
| `/cache` | named volume `perceval_perceval-cache` | read-write (git clones) |
| `/opt/venv` | baked into the image by `uv sync --frozen` | root-owned, read-only to `app` |

The code isn't baked into the image. Edit `app/collect.sh` and re-run, no rebuild needed. A rebuild is only
needed when `pyproject.toml` / `uv.lock` change (`uv lock`, then `make build`).

Local development: `make sync` (= `uv sync --frozen`) creates `.venv/`.

## Output

`data/commits/*.jsonl`: one Perceval item per line. `.data.files[]` has `action` (A/M/D/R…), `file`,
`added`, `removed`. Also `.data.Author`, `.data.AuthorDate`, `.data.commit`, `.data.message`,
`.data.parents`, `.data.refs`.

```bash
jq -r '[.data.AuthorDate, .origin, .data.commit[0:8], (.data.files|length)] | @tsv' data/mine.jsonl
```

## Caching

| Layer | Where |
|---|---|
| Image layers | `./.buildx-cache/<target>` (`mode=max`); `CACHE_BACKEND=gha` for GitHub Actions |
| uv / apt / apk downloads | BuildKit cache mounts (kept in the builder, not in the image) |
| Dependency layer | Depends only on `pyproject.toml`, `uv.lock`, `.python-version` |
| Collected data | Clones in the named volume; `perceval --latest-items` emits only commits not yet in the clone |

`make clean-cache` deletes the clones **and** everything in `./data`, so the next run starts from scratch
with no duplicates.

## Hardening

- Collector runs as `app`, whose uid/gid is your host uid/gid so `./data` stays writable. If you build as root, it falls back to 10001. The proxy runs as `squid`.
- `read_only` root fs, `cap_drop: ALL`, `no-new-privileges`, tmpfs for scratch.
- Collector is only on an `internal: true` network, so bypassing the proxy has no route.
- Proxy allows CONNECT to port 443 and plain HTTP to 80, only for allowlisted hosts.
