"""Phase 2 CLI: contributions and tasks over the collector's commit JSON Lines."""

import json
from pathlib import Path

import pytest

from rag.cli import EXIT_INVALID, EXIT_NO_MATCH, EXIT_OK


def commit_item(sha: str, author: str, day: str, parents: int = 1, message: str = "Work",
                origin: str = "https://gitlab.example.com/grp/proj.git") -> dict:
    return {
        "category": "commit",
        "origin": origin,
        "data": {
            "commit": sha * 40 if len(sha) == 1 else sha,
            "Author": author,
            "AuthorDate": f"{day}",
            "message": message,
            "parents": [f"{'p' * 39}{i}" for i in range(parents)],
        },
    }


ME = "Alvaro Garcia <alvarogarcia7@users.noreply.github.com>"
OTHER = "Someone <s@example.com>"


@pytest.fixture
def commits(data_dir: Path) -> Path:
    folder = data_dir / "commits"
    folder.mkdir(parents=True)
    lines = [
        commit_item("1", ME, "Thu Oct 1 09:00:00 2026 +0400"),
        commit_item("2", ME, "Wed Nov 4 09:00:00 2026 +0400"),
        commit_item("3", ME, "Thu Nov 5 09:00:00 2026 +0400", parents=2,
                    message="Merge branch 'feat' into 'main'\n\nSee merge request grp/proj!7"),
        commit_item("4", OTHER, "Thu Nov 5 10:00:00 2026 +0400"),
    ]
    (folder / "proj.jsonl").write_text("\n".join(json.dumps(i) for i in lines) + "\n", encoding="utf-8")
    other = commit_item("5", ME, "Fri Nov 6 09:00:00 2026 +0400", origin="https://github.com/o/tool.git")
    (folder / "tool.jsonl").write_text(json.dumps(other) + "\n", encoding="utf-8")
    return folder


def rows(out: str) -> list[dict]:
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_contributions_by_project_uses_author_regex_from_settings(run, commits, monkeypatch) -> None:
    monkeypatch.setenv("AUTHOR_REGEX", "alvarogarcia7")
    code, out, _ = run("contributions")
    assert code == EXIT_OK
    assert rows(out) == [
        {"group": "proj", "commits": 2, "merges": 1, "first": "2026-10-01", "last": "2026-11-05"},
        {"group": "tool", "commits": 1, "merges": 0, "first": "2026-11-06", "last": "2026-11-06"},
    ]


def test_contributions_by_month_and_repo(run, commits, monkeypatch) -> None:
    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    assert [r["group"] for r in rows(run("contributions", "--group-by", "month")[1])] == ["2026-10", "2026-11"]
    repo_rows = rows(run("contributions", "--group-by", "repo")[1])
    assert [r["group"] for r in repo_rows] == [
        "https://github.com/o/tool.git",
        "https://gitlab.example.com/grp/proj.git",
    ]


def test_author_flag_overrides_settings(run, commits, monkeypatch) -> None:
    monkeypatch.setenv("AUTHOR_REGEX", "nobody")
    code, out, _ = run("contributions", "--author", "someone", "--since", "2026-11")
    assert code == EXIT_OK
    assert rows(out) == [{"group": "proj", "commits": 1, "merges": 0, "first": "2026-11-05", "last": "2026-11-05"}]
    assert run("contributions", "--since", "2026-11")[0] == EXIT_NO_MATCH  # 'nobody' matches no one


def test_since_after_all_commits_is_no_match(run, commits) -> None:
    assert run("contributions", "--author", "alvaro", "--since", "2027")[0] == EXIT_NO_MATCH


def test_since_keeps_only_the_range(run, commits) -> None:
    code, out, _ = run("contributions", "--author", "alvaro", "--since", "2026-11-01..2026-11-05")
    assert code == EXIT_OK
    assert rows(out) == [
        {"group": "proj", "commits": 1, "merges": 1, "first": "2026-11-04", "last": "2026-11-05"},
    ]


def test_since_with_a_relative_range_uses_today(run, commits) -> None:
    from datetime import date

    # -3d.. is 2026-11-03 through today: proj's 11-04 commit and 11-05 merge, and tool's 11-06 commit.
    code, out, _ = run("contributions", "--author", "alvaro", "--since=-3d..", today=date(2026, 11, 6))
    assert code == EXIT_OK
    assert rows(out) == [
        {"group": "proj", "commits": 1, "merges": 1, "first": "2026-11-04", "last": "2026-11-05"},
        {"group": "tool", "commits": 1, "merges": 0, "first": "2026-11-06", "last": "2026-11-06"},
    ]


def test_tasks_lists_my_merge_commits(run, commits) -> None:
    code, out, _ = run("tasks", "--author", "alvaro")
    assert code == EXIT_OK
    assert rows(out) == [
        {
            "kind": "mr",
            "repo": "https://gitlab.example.com/grp/proj.git",
            "number": 7,
            "title": "Merge branch 'feat' into 'main'",
            "url": "https://gitlab.example.com/grp/proj/-/merge_requests/7",
            "date": "2026-11-05",
        }
    ]


def test_no_author_pattern_is_an_error(run, commits) -> None:
    code, _, err = run("tasks")
    assert code == EXIT_INVALID and "AUTHOR_REGEX" in err


def test_invalid_author_pattern_is_an_error(run, commits) -> None:
    code, _, err = run("contributions", "--author", "(unclosed")
    assert code == EXIT_INVALID and "invalid author pattern" in err


def test_invalid_since_is_an_error(run, commits) -> None:
    code, _, err = run("tasks", "--author", "alvaro", "--since", "2026-13")
    assert code == EXIT_INVALID and "invalid date" in err


def test_no_commit_data_gives_no_match(run, data_dir: Path) -> None:
    assert run("contributions", "--author", "alvaro")[0] == EXIT_NO_MATCH
    assert run("tasks", "--author", "alvaro")[0] == EXIT_NO_MATCH


def test_corrupt_commit_file_is_reported_with_location(run, commits) -> None:
    (commits / "proj.jsonl").write_text("{broken\n", encoding="utf-8")
    code, _, err = run("tasks", "--author", "alvaro")
    assert code == EXIT_INVALID and "proj.jsonl:1: not valid JSON" in err


def test_empty_author_flag_is_an_error_not_a_fallback(run, commits, monkeypatch) -> None:
    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    code, _, err = run("tasks", "--author", "")
    assert code == EXIT_INVALID and "no author pattern" in err


def test_contributions_never_print_credentials(run, data_dir: Path, monkeypatch) -> None:
    folder = data_dir / "commits"
    folder.mkdir(parents=True)
    item = commit_item("1", ME, "Thu Nov 5 09:00:00 2026 +0400",
                       origin="https://user:TOPSECRET@gitlab.example.com/g/p.git")
    (folder / "p.jsonl").write_text(json.dumps(item) + "\n", encoding="utf-8")
    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    code, out, err = run("contributions", "--group-by", "repo")
    assert code == EXIT_OK and "TOPSECRET" not in out + err


def test_since_accepts_a_negative_spec_as_a_separate_argument(run, commits, monkeypatch) -> None:
    from datetime import date

    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    code, out, _ = run("contributions", "--since", "-3d..", today=date(2026, 11, 6))
    assert code == EXIT_OK
    assert [r["group"] for r in rows(out)] == ["proj", "tool"]


def test_select_accepts_a_negative_date_as_a_separate_argument(run, data_dir: Path) -> None:
    from datetime import date

    from helpers import rec
    from rag.store import Store

    Store(data_dir, "achievements").append(rec("recent", day="2026-11-05", ident="1" * 32))
    code, out, _ = run("select", "--date", "-1m..", today=date(2026, 11, 6))
    assert code == EXIT_OK and "recent" in out


def test_tasks_project_filter_keeps_one_repository(run, commits, monkeypatch) -> None:
    monkeypatch.setenv("AUTHOR_REGEX", "alvaro")
    code, out, _ = run("tasks", "--project", "PROJ")
    assert code == EXIT_OK
    assert [r["repo"] for r in rows(out)] == ["https://gitlab.example.com/grp/proj.git"]
    assert run("tasks", "--project", "tool")[0] == EXIT_NO_MATCH  # tool has no merge commits
