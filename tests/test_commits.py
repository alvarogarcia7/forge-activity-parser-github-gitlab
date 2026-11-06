import json
from datetime import date
from pathlib import Path

import pytest

from rag.commits import (
    Commit,
    CommitDataError,
    contributions,
    load_commits,
    merge_reference,
    mine,
    parse_author_date,
    project_of,
    tasks,
    web_base,
)


def item(sha: str, author: str = "Alvaro Garcia <alvarogarcia7@users.noreply.github.com>",
         date_text: str = "Thu Nov 5 09:13:02 2026 +0400", message: str = "Work",
         parents: list[str] | None = None, origin: str = "https://gitlab.example.com/grp/proj.git",
         category: str = "commit") -> dict:
    return {
        "backend_name": "Git",
        "category": category,
        "origin": origin,
        "data": {
            "commit": sha,
            "Author": author,
            "AuthorDate": date_text,
            "message": message,
            "parents": parents if parents is not None else ["p" * 40],
        },
    }


def write(path: Path, *items: dict | str) -> None:
    lines = [i if isinstance(i, str) else json.dumps(i) for i in items]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def commit(**kw) -> Commit:
    values = dict(origin="https://h.example/g/p.git", sha="a" * 40, author="Me <me@x>",
                  day=date(2026, 11, 5), message="msg", parents=("p",))
    values.update(kw)
    return Commit(**values)


# --- parsing dates ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    ["Thu Nov 5 09:13:02 2026 +0400", "Thu Nov  5 09:13:02 2026 +0400", "Thu Nov 5 09:13:02 2026",
     "2026-11-05T09:13:02+04:00"],
)
def test_parse_author_date_accepts_git_and_iso_forms(text: str) -> None:
    assert parse_author_date(text) == date(2026, 11, 5)


def test_parse_author_date_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_author_date("not a date")


# --- loading ---------------------------------------------------------------------------

def test_load_commits_reads_every_file_and_skips_blank_and_non_commit_lines(tmp_path: Path) -> None:
    write(tmp_path / "a.jsonl", item("1" * 40), "", item("2" * 40, category="issue"))
    write(tmp_path / "b.jsonl", item("3" * 40, origin="https://h/x/y.git"))
    loaded = load_commits(tmp_path)
    assert [c.sha[0] for c in loaded] == ["1", "3"]
    assert loaded[0].day == date(2026, 11, 5)
    assert loaded[0].author.startswith("Alvaro")


def test_load_commits_removes_duplicates_by_origin_and_sha(tmp_path: Path) -> None:
    write(tmp_path / "a.jsonl", item("1" * 40))
    write(tmp_path / "b.jsonl", item("1" * 40))
    assert len(load_commits(tmp_path)) == 1


def test_load_commits_missing_directory_is_empty(tmp_path: Path) -> None:
    assert load_commits(tmp_path / "nope") == []


def test_load_commits_reports_invalid_json_with_location(tmp_path: Path) -> None:
    write(tmp_path / "a.jsonl", item("1" * 40), "{broken")
    with pytest.raises(CommitDataError, match=r"a\.jsonl:2: not valid JSON"):
        load_commits(tmp_path)


def test_load_commits_reports_missing_fields_with_location(tmp_path: Path) -> None:
    bad = item("1" * 40)
    del bad["data"]["Author"]
    write(tmp_path / "a.jsonl", bad)
    with pytest.raises(CommitDataError, match=r"a\.jsonl:1: not a commit item"):
        load_commits(tmp_path)




def test_load_commits_reports_bad_dates(tmp_path: Path) -> None:
    write(tmp_path / "a.jsonl", item("1" * 40, date_text="whenever"))
    with pytest.raises(CommitDataError, match="not a commit item"):
        load_commits(tmp_path)


# --- mine / merge references -----------------------------------------------------------

def test_mine_matches_author_regex_case_insensitively() -> None:
    commits = [commit(author="Alvaro <a@x>"), commit(author="Someone Else <s@x>")]
    assert [c.author for c in mine(commits, "ALVARO|alvarogarcia7")] == ["Alvaro <a@x>"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Merge branch 'feat' into 'main'\n\nSee merge request grp/proj!42", ("mr", 42)),
        ("Merge pull request #7 from me/feat", ("pr", 7)),
        ("Merge branch 'x' of github.com:o/r", ("merge", None)),
        ("Plain commit", ("merge", None)),
    ],
)
def test_merge_reference(message: str, expected: tuple[str, int | None]) -> None:
    assert merge_reference(message) == expected


# --- remotes ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("origin", "project", "base"),
    [
        ("https://gitlab.example.com/grp/sub/proj.git", "proj", "https://gitlab.example.com/grp/sub/proj"),
        ("https://user:tok@github.com/o/r.git", "r", "https://github.com/o/r"),
        ("git@gitlab.example.com:grp/proj.git", "proj", "https://gitlab.example.com/grp/proj"),
        ("ssh://git@host.example/o/r/", "r", "https://host.example/o/r"),
        ("/srv/git/local.git", "local", None),
        ("https://host.example", "https://host.example", None),
    ],
)
def test_remote_parsing(origin: str, project: str, base: str | None) -> None:
    assert project_of(origin) == project
    assert web_base(origin) == base


# --- contributions and tasks -----------------------------------------------------------

COMMITS = [
    commit(origin="https://h/g/a.git", sha="1" * 40, day=date(2026, 10, 2)),
    commit(origin="https://h/g/a.git", sha="2" * 40, day=date(2026, 11, 3)),
    commit(origin="https://h/g/a.git", sha="3" * 40, day=date(2026, 11, 4),
           parents=("p1", "p2"), message="Merge branch 'f' into 'main'\n\nSee merge request g/a!9"),
    commit(origin="https://h/g/b.git", sha="4" * 40, day=date(2026, 11, 5)),
]


def test_contributions_by_project() -> None:
    rows = contributions(COMMITS, "project")
    assert rows == [
        {"group": "a", "commits": 2, "merges": 1, "first": "2026-10-02", "last": "2026-11-04"},
        {"group": "b", "commits": 1, "merges": 0, "first": "2026-11-05", "last": "2026-11-05"},
    ]


def test_contributions_by_repo_and_month() -> None:
    assert [r["group"] for r in contributions(COMMITS, "repo")] == ["https://h/g/a.git", "https://h/g/b.git"]
    assert [(r["group"], r["commits"]) for r in contributions(COMMITS, "month")] == [("2026-10", 1), ("2026-11", 2)]


def test_contributions_rejects_unknown_grouping() -> None:
    with pytest.raises(ValueError, match="group-by"):
        contributions(COMMITS, "colour")


def test_contributions_of_nothing_is_empty() -> None:
    assert contributions([], "project") == []


def test_tasks_lists_merges_with_urls() -> None:
    rows = tasks(COMMITS)
    assert rows == [
        {"kind": "mr", "repo": "https://h/g/a.git", "number": 9, "title": "Merge branch 'f' into 'main'",
         "url": "https://h/g/a/-/merge_requests/9", "date": "2026-11-04"},
    ]


def test_tasks_github_pull_request_url_and_plain_merge() -> None:
    commits = [
        commit(origin="https://github.com/o/r.git", sha="5" * 40, parents=("a", "b"),
               message="Merge pull request #12 from me/x"),
        commit(origin="/srv/local.git", sha="6" * 40, parents=("a", "b"), message="Merge work"),
    ]
    rows = tasks(commits)
    assert {r["kind"] for r in rows} == {"pr", "merge"}
    pr = next(r for r in rows if r["kind"] == "pr")
    assert pr["url"] == "https://github.com/o/r/pull/12"
    merge = next(r for r in rows if r["kind"] == "merge")
    assert merge["url"] is None and merge["number"] is None


def test_commit_subject_of_empty_message() -> None:
    assert commit(message="   ").subject == ""
    assert commit(message="first\nsecond").subject == "first"


def test_origin_credentials_are_redacted_at_load(tmp_path: Path) -> None:
    write(tmp_path / "a.jsonl", item("1" * 40, origin="https://user:SECRET@gitlab.example.com/g/p.git"))
    [loaded] = load_commits(tmp_path)
    assert "SECRET" not in loaded.origin and loaded.origin == "https://gitlab.example.com/g/p.git"


def test_missing_parents_is_an_error(tmp_path: Path) -> None:
    bad = item("1" * 40)
    del bad["data"]["parents"]
    write(tmp_path / "a.jsonl", bad)
    with pytest.raises(CommitDataError, match=r"a\.jsonl:1: not a commit item"):
        load_commits(tmp_path)


def test_non_object_line_is_an_error(tmp_path: Path) -> None:
    write(tmp_path / "a.jsonl", "[1, 2]")
    with pytest.raises(CommitDataError, match=r"a\.jsonl:1: not a JSON object"):
        load_commits(tmp_path)


def test_ssh_port_is_not_used_for_web_links() -> None:
    assert web_base("ssh://git@gitlab.example.com:2222/g/p.git") == "https://gitlab.example.com/g/p"
    assert web_base("https://gitlab.example.com:8443/g/p.git") == "https://gitlab.example.com:8443/g/p"
