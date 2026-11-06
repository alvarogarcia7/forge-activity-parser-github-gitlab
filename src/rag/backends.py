"""Phase 5: merged MRs/PRs and assigned issues from the GitLab and GitHub APIs.

Each host writes data/reviews/<host>.jsonl (rewritten on each fetch, so re-running is idempotent).
Tokens come from GITLAB_TOKEN / GITHUB_TOKEN and are only sent in the Authorization header, and
never to another host: a redirect to a different host is refused. Error messages name the host
and port only, never credentials. GITLAB_URL and GITHUB_API_URL select self-hosted instances.
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

PER_PAGE = 100
MAX_PAGES = 50  # a hard stop; reaching it with a full last page is an error, not a silent cut

# (url, headers) -> parsed JSON body
JsonGet = Callable[[str, Mapping[str, str]], Any]


class FetchError(RuntimeError):
    pass


def origin_of(url: str) -> tuple[str, str]:
    """(scheme, host[:port]) of a URL: a redirect must keep both, so a token never goes in cleartext."""
    return urllib.parse.urlsplit(url).scheme.lower(), host_of(url)


def host_of(url: str) -> str:
    """host[:port] of a URL, without any user:password@ part."""
    parts = urllib.parse.urlsplit(url)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.hostname or '?'}{port}"


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only within the original host, so the token is never sent elsewhere."""

    def __init__(self, origin: tuple[str, str]) -> None:
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if origin_of(newurl) != self.origin:
            raise FetchError(f"{self.origin[1]} redirected to another host or scheme; refusing to send credentials there")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get_json(url: str, headers: Mapping[str, str]) -> Any:
    host = host_of(url)
    request = urllib.request.Request(url, headers={"Accept": "application/json", **headers})
    opener = urllib.request.build_opener(_SameHostRedirects(origin_of(url)))
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raise FetchError(f"{host} returned HTTP {error.code}") from None
    except urllib.error.URLError as error:
        raise FetchError(f"{host} unreachable: {error.reason}") from None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise FetchError(f"{host} returned a body that is not JSON (is the URL an API endpoint?)") from None


def _pages(get: JsonGet, url: str, headers: Mapping[str, str], items_of: Callable[[Any], list]) -> list:
    """Collect every page. Stops at a short page; a full page at MAX_PAGES is an error."""
    collected: list = []
    for page in range(1, MAX_PAGES + 1):
        joiner = "&" if "?" in url else "?"
        batch = items_of(get(f"{url}{joiner}per_page={PER_PAGE}&page={page}", headers))
        collected.extend(batch)
        if len(batch) < PER_PAGE:
            return collected
    raise FetchError(f"more than {MAX_PAGES * PER_PAGE} items; narrow the query")


def _rows(items: list, make: Callable[[Any], dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        try:
            out.append(make(item))
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise FetchError(f"unexpected item in the API response ({error})") from None
    return out


def _date(text: str | None) -> str | None:
    return text[:10] if text else None


# --- GitLab ----------------------------------------------------------------------------

def _gitlab_mr(item: Any) -> dict[str, Any]:
    web = str(item["web_url"])
    return {
        "kind": "mr",
        "host": "gitlab",
        "repo": web.split("/-/", 1)[0],
        "number": int(item["iid"]),
        "title": item["title"],
        "url": web,
        "date": _date(item.get("merged_at")),
    }


def _gitlab_issue(item: Any) -> dict[str, Any]:
    web = str(item["web_url"])
    return {
        "kind": "issue",
        "host": "gitlab",
        "repo": web.rsplit("/issues/", 1)[0].removesuffix("/-"),
        "number": int(item["iid"]),
        "title": item["title"],
        "url": web,
        "date": _date(item.get("closed_at") or item.get("created_at")),
    }


def fetch_gitlab(get: JsonGet, base: str, token: str | None) -> list[dict[str, Any]]:
    """Merged merge requests I created, and issues assigned to me."""
    headers = {"PRIVATE-TOKEN": token} if token else {}
    api = f"{base.rstrip('/')}/api/v4"
    mrs = _pages(get, f"{api}/merge_requests?scope=created_by_me&state=merged", headers, _as_list)
    issues = _pages(get, f"{api}/issues?scope=assigned_to_me", headers, _as_list)
    return [*_rows(mrs, _gitlab_mr), *_rows(issues, _gitlab_issue)]


# --- GitHub ----------------------------------------------------------------------------

def _github_pr(item: Any) -> dict[str, Any]:
    html = str(item["html_url"])
    return {
        "kind": "pr",
        "host": "github",
        "repo": html.rsplit("/pull/", 1)[0],
        "number": int(item["number"]),
        "title": item["title"],
        "url": html,
        "date": _date(item.get("closed_at")),
    }


def _github_issue(item: Any) -> dict[str, Any]:
    html = str(item["html_url"])
    return {
        "kind": "issue",
        "host": "github",
        "repo": html.rsplit("/issues/", 1)[0],
        "number": int(item["number"]),
        "title": item["title"],
        "url": html,
        "date": _date(item.get("closed_at") or item.get("created_at")),
    }


def fetch_github(get: JsonGet, base: str, token: str | None) -> list[dict[str, Any]]:
    """Merged pull requests I authored, and issues assigned to me."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    api = base.rstrip("/")
    try:
        login = str(get(f"{api}/user", headers)["login"])
    except (KeyError, TypeError) as error:
        raise FetchError("the API did not return a login for the token's user") from error
    prs = _pages(get, f"{api}/search/issues?q={urllib.parse.quote(f'is:pr is:merged author:{login}', safe=':')}",
                 headers, _items)
    issues = _pages(get, f"{api}/search/issues?q={urllib.parse.quote(f'is:issue assignee:{login}', safe=':')}",
                    headers, _items)
    return [*_rows(prs, _github_pr), *_rows(issues, _github_issue)]


def _as_list(body: Any) -> list:
    if not isinstance(body, list):
        raise FetchError("expected a JSON list from the API")
    return body


def _items(body: Any) -> list:
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise FetchError("expected a search result with an items list")
    return body["items"]


# --- storage ---------------------------------------------------------------------------

def write_reviews(reviews_dir: Path, host: str, rows: list[dict[str, Any]]) -> Path:
    """Rewrite data/reviews/<host>.jsonl with rows de-duplicated by url, newest first."""
    seen: set[str] = set()
    unique = []
    for row in sorted(rows, key=lambda r: (r.get("date") or "", r["url"]), reverse=True):
        if row["url"] not in seen:
            seen.add(row["url"])
            unique.append(row)
    path = reviews_dir / f"{host}.jsonl"
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in unique)
    tmp = path.with_name(path.name + ".tmp")
    try:
        reviews_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as error:
        with contextlib.suppress(OSError):  # cleanup is best effort; the write error is what matters
            tmp.unlink(missing_ok=True)
        raise FetchError(f"cannot write {path}: {error.strerror or error}") from None
    return path


def load_reviews(reviews_dir: Path) -> list[dict[str, Any]]:
    """Every fetched row from every host file. A missing folder is empty."""
    if not reviews_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(reviews_dir.glob("*.jsonl")):
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as error:
                raise FetchError(f"{path}:{number}: not valid JSON ({error.msg})") from error
            if not isinstance(row, dict):
                raise FetchError(f"{path}:{number}: not an object")
            rows.append(row)
    return rows
