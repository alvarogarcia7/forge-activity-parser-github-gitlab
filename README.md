# perceval-docker

Incremental git activity collector (Perceval) → JSONL, with egress limited to an allowlist.

```
collector ──(internal network, no route out)──> egress-proxy (squid) ──> hosts in config/urls.txt
```

## Quick start

```bash
make build                       # creates buildx builder 'perceval-builder', builds both images with cache
$EDITOR config/repos.txt         # repos to collect
$EDITOR config/urls.txt          # allowed hosts (mounted read-only into the proxy)
make test-egress                 # github.com ALLOWED, example.com BLOCKED, direct BLOCKED
make collect                     # run it; repeat any time, only new commits are appended
```

Optional `.env` (git-ignored):

```
GITHUB_TOKEN=ghp_...             # private GitHub repos
GITLAB_TOKEN=glpat-...           # private GitLab repos
AUTHOR_REGEX=alvaro|alvarogarcia7  # also write data/mine.jsonl with just your commits
```

## Output

- `data/commits/<host>__<owner>__<repo>.jsonl`: one Perceval item per line. `.data.files[]` has
  `action` (A/M/D/R…), `file`, `added`, `removed`. Also `.data.Author`, `.data.AuthorDate`,
  `.data.commit`, `.data.message`, `.data.parents`, `.data.refs`.
- `data/mine.jsonl`: commits whose author matches `AUTHOR_REGEX` (rebuilt each run).

```bash
jq -r '[.data.AuthorDate, .origin, .data.commit[0:8], (.data.files|length)] | @tsv' data/mine.jsonl
```

## Caching

| Layer | Where |
|---|---|
| Image layers | `./.buildx-cache/<target>` (`mode=max`); `CACHE_BACKEND=gha` for GitHub Actions |
| pip / apt / apk downloads | BuildKit cache mounts (kept in the builder, not in the image) |
| Collected data | named volume `perceval_perceval-cache` holds the clones; `perceval --latest-items` emits only commits not yet in the clone |

`make clean-cache` drops the clones, so the next run re-emits full history. Delete `data/` first, or you'll get duplicates.

## Hardening

- Both containers run as non-root (`app` uid = your host uid so `./data` stays writable; `squid` in the proxy).
- `read_only` root fs, `cap_drop: ALL`, `no-new-privileges`, tmpfs for scratch.
- Collector is only on an `internal: true` network, so bypassing the proxy has no route.
- Proxy allows CONNECT to port 443 and plain HTTP to 80, only for allowlisted hosts.
  For HTTPS, the proxy sees only `host:port`. A URL path in `urls.txt` is reduced to its host.
