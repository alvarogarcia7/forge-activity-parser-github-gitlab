from pathlib import Path

import pytest

from helpers import git, make_repo
from rag.gitctx import capture_source, redact_url


def test_redact_url_removes_credentials_only_from_https() -> None:
    assert redact_url("https://user:secret@host.example/x.git") == "https://host.example/x.git"
    assert redact_url("https://token@host.example/x.git") == "https://host.example/x.git"
    assert redact_url("git@host.example:x/y.git") == "git@host.example:x/y.git"
    assert redact_url("https://host.example/x.git") == "https://host.example/x.git"


def test_capture_reads_remote_branch_and_commit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", remote="https://user:tok@github.com/o/r.git", branch="feature/x")
    source = capture_source(repo, path="src/app.py")
    head = git(repo, "rev-parse", "--short", "HEAD")
    assert source == {
        "remote": "https://github.com/o/r.git",
        "branch": "feature/x",
        "commit": head,
        "path": "src/app.py",
    }


def test_capture_without_origin_has_null_remote(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", remote=None)
    source = capture_source(repo)
    assert source is not None and source["remote"] is None and source["path"] is None


def test_detached_head_has_null_branch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", remote="git@host:o/r.git")
    git(repo, "checkout", "-q", "--detach")
    source = capture_source(repo)
    assert source is not None and source["branch"] is None and source["remote"] == "git@host:o/r.git"


def test_directory_outside_git_gives_none(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert capture_source(plain) is None


def test_missing_directory_gives_none(tmp_path: Path) -> None:
    assert capture_source(tmp_path / "does-not-exist") is None


def test_missing_git_executable_gives_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path / "repo")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert capture_source(repo) is None
