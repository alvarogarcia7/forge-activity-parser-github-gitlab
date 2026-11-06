#!/usr/bin/env bash
# Incrementally collect commits (with per-file A/M/D/R + line counts) for every
# repo listed in $REPOS_FILE, appending JSON Lines to $DATA_DIR/commits/<slug>.jsonl.
#
# Caching: clones live in $CACHE_DIR/repos (a named volume). Perceval's
# --latest-items fetches the remote and emits only commits not seen in the
# local clone, so re-running today/tomorrow only appends new commits.
# A fresh/missing clone emits the full history.
set -euo pipefail

REPOS_FILE="${REPOS_FILE:-/config/repos.txt}"
DATA_DIR="${DATA_DIR:-/data}"
CACHE_DIR="${CACHE_DIR:-/cache}"
AUTHOR_REGEX="${AUTHOR_REGEX:-}"   # e.g. 'alvaro|alvarogarcia7' -> also writes mine.jsonl

# Private repos: inject tokens via git's env-based config (nothing written to disk,
# and the token never ends up in the "origin" field of the output).
n=0
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  export "GIT_CONFIG_KEY_$n=url.https://x-access-token:${GITHUB_TOKEN}@github.com/.insteadOf"
  export "GIT_CONFIG_VALUE_$n=https://github.com/"; n=$((n+1))
fi
if [[ -n "${GITLAB_TOKEN:-}" ]]; then
  export "GIT_CONFIG_KEY_$n=url.https://oauth2:${GITLAB_TOKEN}@gitlab.com/.insteadOf"
  export "GIT_CONFIG_VALUE_$n=https://gitlab.com/"; n=$((n+1))
fi
export GIT_CONFIG_COUNT=$n GIT_TERMINAL_PROMPT=0

[[ -r "$REPOS_FILE" ]] || { echo "repos file not readable: $REPOS_FILE" >&2; exit 2; }
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
