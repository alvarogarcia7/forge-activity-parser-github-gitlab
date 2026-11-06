"""Phase 5: GitLab and GitHub backends. HTTP is faked; no test touches the network."""

import io
import json
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from helpers import git, make_repo
from rag import backends
from rag.backends import FetchError, fetch_github, fetch_gitlab, load_reviews, write_reviews
from rag.cli import EXIT_INVALID, EXIT_NO_MATCH, EXIT_OK


class Api:
    """A fake JSON API: maps a path to a list of items, served page by page (100 per page)."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, headers: dict) -> object:
        self.calls.append((url, dict(headers)))
        parts = urlsplit(url)
        key = parts.path
        query = parse_qs(parts.query)
        if key in self.routes and not isinstance(self.routes[key], list):
            return self.routes[key]  # a single object, e.g. /user
        if key not in self.routes:
            raise FetchError(f"no route for {url}")
        items = self.routes[key]
        page = int(query.get("page", ["1"])[0])
        per = int(query.get("per_page", ["100"])[0])
        chunk = items[(page - 1) * per: page * per]
        if "q" in query:  # GitHub search returns an object with items
            return {"items": chunk}
        return chunk


def gl_mr(iid: int, merged: str = "2026-11-03T10:00:00Z") -> dict:
    return {"iid": iid, "title": f"MR {iid}", "web_url": f"https://gitlab.example.com/g/p/-/merge_requests/{iid}",
            "merged_at": merged}


def gl_issue(iid: int) -> dict:
    return {"iid": iid, "title": f"Issue {iid}", "web_url": f"https://gitlab.example.com/g/p/-/issues/{iid}",
            "created_at": "2026-10-01T00:00:00Z", "closed_at": None}


def test_fetch_gitlab_mrs_and_issues_with_token_header() -> None:
    api = Api({
        "/api/v4/merge_requests": [gl_mr(1), gl_mr(2)],
        "/api/v4/issues": [gl_issue(9)],
    })
    rows = fetch_gitlab(api, "https://gitlab.example.com/", "TOKEN")
    kinds = [(r["kind"], r["number"], r["repo"], r["date"]) for r in rows]
    assert kinds == [
        ("mr", 1, "https://gitlab.example.com/g/p", "2026-11-03"),
        ("mr", 2, "https://gitlab.example.com/g/p", "2026-11-03"),
        ("issue", 9, "https://gitlab.example.com/g/p", "2026-10-01"),
    ]
    assert all(headers == {"PRIVATE-TOKEN": "TOKEN"} for _, headers in api.calls)
    assert api.calls[0][0].startswith("https://gitlab.example.com/api/v4/merge_requests?scope=created_by_me&state=merged")


def test_fetch_gitlab_without_token_sends_no_auth_header() -> None:
    api = Api({"/api/v4/merge_requests": [], "/api/v4/issues": []})
    assert fetch_gitlab(api, "https://gitlab.example.com", None) == []
    assert all(headers == {} for _, headers in api.calls)


def test_fetch_gitlab_pages_until_a_short_page() -> None:
    api = Api({
        "/api/v4/merge_requests": [gl_mr(i) for i in range(1, 151)],
        "/api/v4/issues": [],
    })
    rows = fetch_gitlab(api, "https://gitlab.example.com", None)
    assert sum(1 for r in rows if r["kind"] == "mr") == 150
    mr_calls = [u for u, _ in api.calls if "merge_requests" in u]
    assert len(mr_calls) == 2  # a full page, then a short one


def test_fetch_github_prs_and_issues_use_the_login() -> None:
    api = Api({
        "/user": {"login": "alvaro"},
        "/search/issues": [
            {"number": 7, "title": "Add thing", "html_url": "https://github.com/o/r/pull/7",
             "closed_at": "2026-11-02T09:00:00Z"},
        ],
    })
    rows = fetch_github(api, "https://api.github.com", "GHTOKEN")
    assert rows[0] == {"kind": "pr", "host": "github", "repo": "https://github.com/o/r", "number": 7,
                       "title": "Add thing", "url": "https://github.com/o/r/pull/7", "date": "2026-11-02"}
    queries = [parse_qs(urlsplit(u).query)["q"][0] for u, _ in api.calls if "search" in u]
    assert queries[0] == "is:pr is:merged author:alvaro"
    assert queries[1] == "is:issue assignee:alvaro"
    assert api.calls[1][1] == {"Authorization": "Bearer GHTOKEN"}


def test_fetch_github_issue_row_uses_created_date_when_open() -> None:
    api = Api({
        "/user": {"login": "me"},
        "/search/issues": [],
    })
    assert fetch_github(api, "https://api.github.com", None) == []
    api2 = Api({"/user": {"login": "me"}, "/search/issues": [
        {"number": 3, "title": "open issue", "html_url": "https://github.com/o/r/issues/3",
         "closed_at": None, "created_at": "2026-09-30T00:00:00Z"},
    ]})
    rows = [r for r in fetch_github(api2, "https://api.github.com", None) if r["kind"] == "issue"]
    assert rows[0]["date"] == "2026-09-30" and rows[0]["repo"] == "https://github.com/o/r"


def test_a_full_last_page_at_the_cap_is_an_error_not_a_silent_cut(monkeypatch) -> None:
    monkeypatch.setattr(backends, "MAX_PAGES", 3)
    calls = []

    def endless(url, headers):
        calls.append(url)
        return [gl_mr(1)] * 100

    with pytest.raises(FetchError, match="narrow the query"):
        fetch_gitlab(endless, "https://gitlab.example.com", None)
    assert len(calls) == 3


def test_unexpected_shapes_are_fetch_errors() -> None:
    with pytest.raises(FetchError, match="expected a JSON list"):
        fetch_gitlab(lambda u, h: {"not": "a list"}, "https://gitlab.example.com", None)
    with pytest.raises(FetchError, match="items list"):
        fetch_github(lambda u, h: {"login": "x"} if u.endswith("/user") else {"nope": 1},
                     "https://api.github.com", None)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FakeOpener:
    """Stands in for the opener: `responder(request)` returns a response or raises."""

    def __init__(self, responder) -> None:
        self.responder = responder

    def open(self, request, timeout):
        assert timeout == 30
        return self.responder(request)


def use_opener(monkeypatch, responder) -> None:
    monkeypatch.setattr(backends.urllib.request, "build_opener", lambda *handlers: FakeOpener(responder))


def test_http_get_json_parses_and_sends_headers(monkeypatch) -> None:
    seen = {}

    def responder(request):
        seen["headers"] = dict(request.header_items())
        return FakeResponse(b'{"ok": true}')

    use_opener(monkeypatch, responder)
    assert backends.http_get_json("https://h.example/x", {"PRIVATE-TOKEN": "t"}) == {"ok": True}
    assert seen["headers"]["Private-token"] == "t"


def test_http_errors_are_reported_without_the_token(monkeypatch) -> None:
    def refused(request):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))

    use_opener(monkeypatch, refused)
    with pytest.raises(FetchError, match="HTTP 401") as error:
        backends.http_get_json("https://h.example/x", {"PRIVATE-TOKEN": "SECRET"})
    assert "SECRET" not in str(error.value)


def test_unreachable_hosts_are_reported_without_credentials(monkeypatch) -> None:
    def down(request):
        raise urllib.error.URLError("name resolution failed")

    use_opener(monkeypatch, down)
    with pytest.raises(FetchError, match="h.example unreachable: name resolution failed") as error:
        backends.http_get_json("https://alice:hunter2@h.example/x", {})
    assert "hunter2" not in str(error.value) and "alice" not in str(error.value)


def test_non_json_body_names_the_host(monkeypatch) -> None:
    use_opener(monkeypatch, lambda request: FakeResponse(b"<html>login</html>"))
    with pytest.raises(FetchError, match="h.example:8443 returned a body that is not JSON"):
        backends.http_get_json("https://h.example:8443/x", {})


def test_host_of_strips_credentials_and_keeps_port() -> None:
    assert backends.host_of("https://alice:pw@gitlab.example.com:8443/api") == "gitlab.example.com:8443"
    assert backends.host_of("https://gitlab.example.com/api") == "gitlab.example.com"
    assert backends.host_of("not a url") == "?"


def test_redirect_to_another_host_is_refused() -> None:
    handler = backends._SameHostRedirects(("https", "api.example.com"))
    with pytest.raises(FetchError, match="refusing to send credentials"):
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example.org/steal")


def test_redirect_that_downgrades_to_http_is_refused() -> None:
    handler = backends._SameHostRedirects(("https", "api.example.com"))
    with pytest.raises(FetchError, match="another host or scheme"):
        handler.redirect_request(None, None, 302, "Found", {}, "http://api.example.com/v2")


def test_redirect_within_the_same_host_is_delegated_to_the_stdlib(monkeypatch) -> None:
    seen = []

    def stdlib(self, req, fp, code, msg, headers, newurl):
        seen.append(newurl)
        return "followed"

    monkeypatch.setattr(urllib.request.HTTPRedirectHandler, "redirect_request", stdlib)
    handler = backends._SameHostRedirects(("https", "api.example.com"))
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://api.example.com/v2") == "followed"
    assert seen == ["https://api.example.com/v2"]


def test_write_reviews_dedupes_sorts_and_replaces(tmp_path: Path) -> None:
    rows = [
        {"kind": "mr", "url": "u1", "date": "2026-10-01"},
        {"kind": "mr", "url": "u2", "date": "2026-11-01"},
        {"kind": "mr", "url": "u1", "date": "2026-10-01"},
    ]
    path = write_reviews(tmp_path / "reviews", "gitlab", rows)
    assert [json.loads(l)["url"] for l in path.read_text().splitlines()] == ["u2", "u1"]
    write_reviews(tmp_path / "reviews", "gitlab", rows[:1])
    assert [json.loads(l)["url"] for l in path.read_text().splitlines()] == ["u1"]
    assert not (tmp_path / "reviews" / "gitlab.jsonl.tmp").exists()


def test_load_reviews_handles_missing_blank_and_corrupt(tmp_path: Path) -> None:
    assert load_reviews(tmp_path / "nope") == []
    folder = tmp_path / "reviews"
    folder.mkdir()
    (folder / "gitlab.jsonl").write_text('{"url": "a"}\n\n', encoding="utf-8")
    assert load_reviews(folder) == [{"url": "a"}]
    (folder / "github.jsonl").write_text("{oops\n", encoding="utf-8")
    with pytest.raises(FetchError, match=r"github\.jsonl:1: not valid JSON"):
        load_reviews(folder)


# --- CLI: fetch, and tasks merging reviews ---------------------------------------------

@pytest.fixture
def fake_http(monkeypatch):
    api = Api({
        "/api/v4/merge_requests": [gl_mr(4)],
        "/api/v4/issues": [gl_issue(2)],
        "/user": {"login": "alvaro"},
        "/search/issues": [],
    })
    monkeypatch.setattr(backends, "http_get_json", api)
    return api


def test_cli_fetch_gitlab_writes_the_reviews_file(run, data_dir, fake_http, monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "T")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    code, out, _ = run("fetch", "gitlab")
    assert code == EXIT_OK and "fetched 2 item(s)" in out
    assert (data_dir / "reviews" / "gitlab.jsonl").exists()
    assert all(h == {"PRIVATE-TOKEN": "T"} for _, h in fake_http.calls)


def test_cli_fetch_github_defaults_to_public_api(run, data_dir, fake_http, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code, out, _ = run("fetch", "github")
    assert code == EXIT_OK and "fetched 0 item(s)" in out
    assert any(u.startswith("https://api.github.com/user") for u, _ in fake_http.calls)


def test_cli_fetch_error_is_reported(run, data_dir, monkeypatch) -> None:
    def broken(url, headers):
        raise FetchError("gitlab.example.com returned HTTP 500")

    monkeypatch.setattr(backends, "http_get_json", broken)
    code, _, err = run("fetch", "gitlab")
    assert code == EXIT_INVALID and "HTTP 500" in err


def test_cli_tasks_merges_fetched_reviews_without_duplicates(run, data_dir, monkeypatch, tmp_path) -> None:
    # A local merge commit for MR 7 and the same MR fetched from the API: one row, the API's.
    folder = data_dir / "commits"
    folder.mkdir(parents=True)
    item = {
        "category": "commit",
        "origin": "https://gitlab.example.com/g/p.git",
        "data": {"commit": "c" * 40, "Author": "Alvaro <a@x>", "AuthorDate": "Thu Nov 5 09:00:00 2026 +0400",
                 "message": "Merge branch 'f' into 'main'\n\nSee merge request g/p!7",
                 "parents": ["a" * 40, "b" * 40]},
    }
    (folder / "p.jsonl").write_text(json.dumps(item) + "\n", encoding="utf-8")
    write_reviews(data_dir / "reviews", "gitlab", [
        {"kind": "mr", "host": "gitlab", "repo": "https://gitlab.example.com/g/p", "number": 7,
         "title": "Full MR title", "url": "https://gitlab.example.com/g/p/-/merge_requests/7", "date": "2026-11-05"},
        {"kind": "issue", "host": "gitlab", "repo": "https://gitlab.example.com/g/p", "number": 3,
         "title": "An issue", "url": "https://gitlab.example.com/g/p/-/issues/3", "date": "2026-11-01"},
    ])
    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    code, out, _ = run("tasks")
    assert code == EXIT_OK
    import json as _json
    rows = [_json.loads(l) for l in out.splitlines()]
    assert [(r["kind"], r["title"]) for r in rows] == [("mr", "Full MR title"), ("issue", "An issue")]


def test_cli_tasks_date_filter_applies_to_reviews(run, data_dir, monkeypatch) -> None:
    write_reviews(data_dir / "reviews", "github", [
        {"kind": "pr", "host": "github", "repo": "https://github.com/o/r", "number": 1, "title": "old",
         "url": "https://github.com/o/r/pull/1", "date": "2026-01-02"},
    ])
    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    assert run("tasks", "--since", "2026-11")[0] == EXIT_NO_MATCH
    code, out, _ = run("tasks", "--since", "2026")
    assert code == EXIT_OK and json.loads(out)["title"] == "old"


def test_cli_tasks_reports_a_corrupt_reviews_file(run, data_dir, monkeypatch) -> None:
    (data_dir / "reviews").mkdir(parents=True)
    (data_dir / "reviews" / "gitlab.jsonl").write_text("{bad\n", encoding="utf-8")
    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    code, _, err = run("tasks")
    assert code == EXIT_INVALID and "not valid JSON" in err


def test_cli_tasks_drops_reviews_without_a_date_when_filtering(run, data_dir, monkeypatch) -> None:
    write_reviews(data_dir / "reviews", "github", [
        {"kind": "pr", "host": "github", "repo": "https://github.com/o/r", "number": 2, "title": "undated",
         "url": "https://github.com/o/r/pull/2", "date": None},
        {"kind": "pr", "host": "github", "repo": "https://github.com/o/r", "number": 3, "title": "bad date",
         "url": "https://github.com/o/r/pull/3", "date": "not-a-date"},
    ])
    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    assert run("tasks", "--since", "2026")[0] == EXIT_NO_MATCH  # neither has a usable date
    code, out, _ = run("tasks")  # without a filter they are kept
    assert code == EXIT_OK and len(out.splitlines()) == 2


def test_malformed_api_item_is_a_fetch_error_not_a_traceback() -> None:
    with pytest.raises(FetchError, match="unexpected item in the API response"):
        fetch_gitlab(Api({"/api/v4/merge_requests": [{"iid": 1, "title": "no web_url"}],
                          "/api/v4/issues": []}), "https://gitlab.example.com", None)


def test_github_without_a_login_is_a_fetch_error() -> None:
    with pytest.raises(FetchError, match="did not return a login"):
        fetch_github(lambda url, headers: {"message": "Bad credentials"}, "https://api.github.com", None)


def test_write_reviews_reports_a_write_failure(tmp_path: Path) -> None:
    blocker = tmp_path / "reviews"
    blocker.write_text("i am a file, not a folder", encoding="utf-8")
    with pytest.raises(FetchError, match="cannot write"):
        write_reviews(blocker, "gitlab", [{"kind": "mr", "url": "u", "date": "2026-01-01"}])


def test_load_reviews_rejects_lines_that_are_not_objects(tmp_path: Path) -> None:
    folder = tmp_path / "reviews"
    folder.mkdir()
    (folder / "gitlab.jsonl").write_text("42\n", encoding="utf-8")
    with pytest.raises(FetchError, match=r"gitlab\.jsonl:1: not an object"):
        load_reviews(folder)


def test_cli_fetch_reports_a_write_failure(run, data_dir, fake_http, monkeypatch) -> None:
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    data_dir.write_text("a file where the data folder should be", encoding="utf-8")
    code, _, err = run("fetch", "gitlab")
    assert code == EXIT_INVALID and "cannot write" in err
