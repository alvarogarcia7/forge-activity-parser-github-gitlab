"""Shared test helpers (imported by the test modules; tests/ is on sys.path under pytest)."""

from __future__ import annotations

import itertools
import subprocess
from pathlib import Path

from rag.model import Achievement

_ids = itertools.count(1)


def rec(
    idea: str = "an idea",
    day: str = "2026-11-05",
    time: str = "10:00:00+0400",
    topics: tuple[str, ...] | list[str] = (),
    project: str | None = None,
    category: str | None = None,
    free: dict | None = None,
    source: dict | None = None,
    ident: str | None = None,
) -> Achievement:
    """A valid record with a deterministic id unless `ident` is given."""
    return Achievement(
        id=ident or f"{next(_ids):032x}",
        date=day,
        time=time,
        idea=idea,
        topics=list(topics),
        project=project,
        category=category,
        free=dict(free or {}),
        source=source,
    )


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-C",
            str(cwd),
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def make_repo(path: Path, remote: str | None = None, branch: str = "main") -> Path:
    """A git repository with one commit, and optionally an origin remote."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    git(path, "commit", "-q", "--allow-empty", "-m", "init")
    if remote is not None:
        git(path, "remote", "add", "origin", remote)
    return path
