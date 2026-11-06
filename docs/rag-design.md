# Retrieval tool for a human operator: design

Status: implemented in phases 1–5 (see the phased plan below). Module map: `src/rag/`; tests: `tests/`.

## Goal

A small command-line tool a human runs to retrieve past work, in two ways:

1. **Inspiration.** Find matching entries (projects, achievements, commits) and print them as JSONL,
   so an AI assistant can read them and reuse previous implementations.
2. **Achievements.** Summarise contributions: merged MRs/PRs, commits per project, and tasks worked on.

The tool retrieves and does not generate. The human, or the AI they pipe the output into, does the
reasoning. This keeps the output deterministic and auditable.

## Inspiration from `achievements`

These patterns are borrowed. The `achievements` repo is a reference, not something we evaluate or depend on.

| Pattern | What we take |
|---|---|
| JSONL as the store | One record per line, append-friendly, `grep`/`jq`-able |
| JSON Schema on write | Reject bad records before they reach the file; keep the rejected input for a retry |
| Lower-and-dashes slugs | Tags, topics, projects normalised the same way on every path |
| Date spec parser | Short forms such as `y`, `w`, `m`, `-30d`, `2026-11`, `A..B` |
| fzf for browsing | Interactive picking on top of the non-interactive `select` |
| `.env` settings with env override | Choose the database file without flags |

## Data sources

| Source | Produced by | Shape |
|---|---|---|
| Achievements | the `add` command (new) | JSONL, schema-validated, one record per achievement |
| Commits | this repo's collector, `data/commits/*.jsonl` | Perceval items; commit data is under `.data` |
| Merged MRs/PRs, assigned issues | `rag fetch gitlab\|github`, written to `data/reviews/<host>.jsonl` | API calls with the token; the collector's egress allowlist applies |

The collector already stores commit history, so achievement harvesting can read from it instead of
calling the hosting APIs again.

## Achievement record (v1)

```json
{
  "id": "32 hex chars",
  "date": "2026-11-06",
  "time": "15:40:00+0400",
  "idea": "one sentence: what was achieved",
  "topics": ["kubernetes", "helm"],
  "project": "forge-collector",
  "category": "professional",
  "free": {"k1": "any value", "tier": "beta"},
  "source": {
    "remote": "https://gitlab.com/group/project.git",
    "branch": "feature/x",
    "commit": "a19d9d8",
    "path": "app/collect.sh"
  }
}
```

Decisions:

- **Pointers, not code.** `source` says where the implementation lives. The AI reads the code at that
  pointer. The store never holds the code.
- **`source` is captured at add time** from the current git repository (`git remote get-url origin`,
  `git rev-parse --abbrev-ref HEAD`, `git rev-parse --short HEAD`). Commits from the collector are not
  turned into achievement records; `contributions` and `tasks` read them directly.
- **`free` is an object of arbitrary keys.** The schema permits it explicitly, instead of the
  `additionalProperties: false` used by `achievements`. Values are strings, numbers, booleans, or
  arrays of those.
- **`topics` are tags.** `--topic kubernetes` filters on them.

## Commands

```text
rag add "idea text" [--topic a,b] [--project P] [--category C] [--free k=v ...]
           [--path P] [--no-source] [--db NAME]
rag select [--db NAME] [--date SPEC] [--topic T] [--any-topic] [--project P] [--category C]
           [--any=VALUE] [--text QUERY] [--ranked] [--format jsonl|line] [--fields ...]
rag browse [same filters]                 # fzf, preview = `rag view`
rag view ID [--db NAME]
rag index [--db NAME]                     # builds the ranked index used by --ranked
rag contributions [--author REGEX] [--since SPEC] [--group-by project|repo|month]
rag tasks [--author REGEX] [--since SPEC] # local merges plus fetched reviews
rag fetch gitlab|github                   # merged MRs/PRs and assigned issues, needs a token
rag validate FILE
rag retry FILE [--db NAME]
```

- **`select` output** is JSONL by default. Each line is the full record, with `source` included, so
  branch and remote are printed as well.
- **Filters combine with AND.** Multiple `--topic` values are AND by default, with `--any-topic` for OR.
- **`--db NAME`** resolves to `data/<NAME>.jsonl`. This matches the one-file-per-database layout of
  `achievements`, and the same `.env` mechanism selects a default.
- **`--any=VALUE`** matches a record when any of its `free` values equals VALUE. It is a value match
  across all keys, not a key lookup.

## Date specs (extensions)

Add to the `achievements` set:

- `-Nm` (N months back) and `-Ny`.
- Open-ended ranges: `-1m..` means one month ago through today. `..2026-10` means everything up to
  October.
- Example: `rag select --date -1m.. --topic kubernetes --format jsonl`.

## Retrieval

Three layers, each one added only when the previous is not enough:

1. **Filters** (above). Exact, deterministic, no index needed.
2. **Text match** for `--text`. Case-insensitive substring over `idea`, `topics`, `project`, `category`
   and `free` values.
   Sufficient at small scale.
3. **Ranked text search.** A SQLite FTS5 index built from the JSONL, with BM25 ranking. It is derived
   from the JSONL and can be deleted and rebuilt. Used by `select --ranked`. The index stores a SHA-256 of
   the data file and is refused when it no longer matches. Punctuated words (`c++`) also have to match
   literally, because the tokenizer splits them.

Embeddings are a later option. If used, embed `idea` + `topics` + `project`, use a local model, and
document it explicitly, because the content is personal.

## Achievements from git

`rag contributions` and `rag tasks` work from:

- `data/commits/*.jsonl`, filtered by author using `AUTHOR_REGEX` from `.env` (or `--author`). The
  collector already has this setting.
- Merge commits, which identify merged MRs and PRs locally. Their subjects follow the hosting
  convention (for example `Merge branch 'x' into 'main'`, or `Merge pull request #N`).
- The GitLab/GitHub API, through `rag fetch`, for MR/PR titles, links, and task (issue)
  references. This needs the existing tokens, and the egress allowlist must include the API hosts.

Contribution output is a summary per project or repo: commit count, merged-MR count, first and last
date. `rag tasks` lists the individual MR or issue titles, with links once the API backend exists.

Harvested items are candidates. They go through the same schema check and `retry` review as manual
entries, and nothing is written silently.

## Output contract

- `select`, `contributions`, `tasks` print JSONL on stdout, with one record per line.
- Human-readable output (`--format line`, the fzf list) goes to a separate code path. stdout stays clean
  for piping.
- Exit codes: 0 found, 1 nothing matched, 2 invalid input.

## Privacy and storage

- All data stays in `data/`, which is git-ignored, as in the current `.gitignore`.
- Nothing is sent to an external service by default. An embedding or LLM call would send record
  content, so it needs an explicit flag.

## Phased plan

1. **Phase 1:** `add`, `select` with filters and JSONL output, date-spec extensions, schema v1 with
   `free` and `source`. Tests modelled on the `achievements` test layout.
2. **Phase 2:** `contributions` and `tasks` from the local commit JSONL and merge commits.
3. **Phase 3:** `browse` with fzf.
4. **Phase 4:** FTS5 index (`rag index`, `select --ranked`).
5. **Phase 5:** GitLab/GitHub MR and issue fetch (`rag fetch`), merged into `tasks`.

## Decisions

- Merges count for the person who made them. `contributions` lists commits by the author and merges
  by the merger. An MR is credited to its author only through the API backend (`rag fetch`), which
  lists MRs created by the token's user.
- A date spec may follow its option with a space: `rag select --date -1m..` works. Internally the CLI
  rewrites it to `--date=-1m..`.
- `tasks` combines local merge commits with fetched reviews (`data/reviews/<host>.jsonl`) and drops
  the local row when a fetched row has the same URL.

- `topic` is a tag. `--topic` filters on `topics`.
- `--any=VALUE` matches any value in `free`. It replaces the earlier `--free` argument.
- `--db NAME` selects one JSONL file per database (`data/<NAME>.jsonl`).
- "Me" for contributions is whatever `AUTHOR_REGEX` in `.env` matches. No separate identity list.
