"""Where an achievement lives: the git remote, branch and commit of the current repository."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_CREDENTIALS = re.compile(r"^(https?://)[^/@]+@")


def redact_url(url: str) -> str:
    """Drop user:password@ from an https URL, so tokens never reach the database."""
    return _CREDENTIALS.sub(r"\1", url)


def capture_source(cwd: Path, path: str | None = None) -> dict[str, str | None] | None:
    """The source of an achievement made in `cwd`, or None when `cwd` is not inside a git work tree."""

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", "-C", str(cwd), *args],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:  # git is not installed
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    if git("rev-parse", "--is-inside-work-tree") != "true":
        return None
    remote = git("remote", "get-url", "origin")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    commit = git("rev-parse", "--short", "HEAD")
    return {
        "remote": redact_url(remote) if remote else None,
        "branch": None if branch in (None, "HEAD") else branch,
        "commit": commit or None,
        "path": path,
    }
