#!/usr/bin/env bash
# Incrementally collect commits (with per-file A/M/D/R + line counts) for every
# repo listed in $REPOS_FILE, appending JSON Lines to $DATA_DIR/commits/<slug>.jsonl.
#
# Caching: clones live in $CACHE_DIR/repos (a named volume). Perceval's
# --latest-items fetches the remote and emits only commits not seen in the
# local clone, so re-running today/tomorrow only appends new commits.
# A fresh/missing clone emits the full history.
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"                     # repo, mounted read-only
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"           # secrets, read-only via the repo mount

# Load KEY=VALUE lines from .env without executing it (no `source`): secrets are
# never passed through compose `environment:`, so they don't show in `docker inspect`.
if [[ -r "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[2]}"; val="${BASH_REMATCH[3]}"
    val="${val%"${val##*[![:space:]]}"}"                          # rtrim
    if [[ "$val" =~ ^\"(.*)\"$ || "$val" =~ ^\'(.*)\'$ ]]; then
      val="${BASH_REMATCH[1]}"
    elif [[ "$val" =~ [[:space:]]# ]]; then
      echo "$ENV_FILE: '$key' has a trailing '# comment'; move the comment to the line above" >&2
      exit 2
    fi
    if [[ -z "${!key:-}" ]]; then export "$key=$val"; fi            # real env wins
  done <"$ENV_FILE"
fi

REPOS_FILE="${REPOS_FILE:-$APP_DIR/config/repos.txt}"
DATA_DIR="${DATA_DIR:-/data}"
CACHE_DIR="${CACHE_DIR:-/cache}"
AUTHOR_REGEX="${AUTHOR_REGEX:-}"   # e.g. 'alvaro|alvarogarcia7' -> also writes mine.jsonl

# Private repos: write the token rewrite rules to a private git config in $HOME.
# Perceval runs git with a minimal environment (GIT_CONFIG_* env vars would be dropped),
# but it does pass HOME through. $HOME is tmpfs in compose; the file is removed on exit,
# and the token never ends up in the "origin" field of the output.
if [[ -n "${GITHUB_TOKEN:-}" || -n "${GITLAB_TOKEN:-}" ]]; then
  umask 077
  GITCONF="${HOME:?HOME must be set}/.gitconfig"
  trap 'rm -f "$GITCONF"' EXIT
  : >"$GITCONF"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    printf '[url "https://x-access-token:%s@github.com/"]\n\tinsteadOf = https://github.com/\n' \
      "$GITHUB_TOKEN" >>"$GITCONF"
  fi
  if [[ -n "${GITLAB_TOKEN:-}" ]]; then
    printf '[url "https://oauth2:%s@gitlab.com/"]\n\tinsteadOf = https://gitlab.com/\n' \
      "$GITLAB_TOKEN" >>"$GITCONF"
  fi
fi
export GIT_TERMINAL_PROMPT=0

[[ -r "$REPOS_FILE" ]] || {
  echo "repos file not readable: $REPOS_FILE (cp config/repos.txt.example config/repos.txt)" >&2; exit 2; }
mkdir -p "$DATA_DIR/commits" "$CACHE_DIR/repos"

failed=0
while IFS= read -r line || [[ -n "$line" ]]; do
  url="${line%%#*}"; url="$(echo "$url" | xargs)"   # strip comments/whitespace
  [[ -z "$url" ]] && continue
  slug="$(echo "$url" | sed -E 's#^[a-z]+://##; s#\.git$##; s#[^A-Za-z0-9._-]+#__#g')"
  out="$DATA_DIR/commits/$slug.jsonl"
  tmp="$(mktemp "$DATA_DIR/commits/.$slug.XXXXXX")"
  echo ">> $url"
  if perceval git "$url" --json-line --latest-items --base-path "$CACHE_DIR/repos" >"$tmp"; then
    cat "$tmp" >>"$out"
    echo "   +$(wc -l <"$tmp") commits -> $out"
  else
    echo "   FAILED: $url" >&2; failed=$((failed+1))
  fi
  rm -f "$tmp"
done <"$REPOS_FILE"

if [[ -n "$AUTHOR_REGEX" ]]; then
  find "$DATA_DIR/commits" -name '*.jsonl' -print0 \
    | xargs -0 -r cat \
    | jq -c --arg re "$AUTHOR_REGEX" 'select(.data.Author | test($re; "i"))' \
    >"$DATA_DIR/mine.jsonl.tmp"
  mv "$DATA_DIR/mine.jsonl.tmp" "$DATA_DIR/mine.jsonl"
  echo "mine.jsonl: $(wc -l <"$DATA_DIR/mine.jsonl") commits matching /$AUTHOR_REGEX/i"
fi

exit $(( failed > 0 ))
