"""Phase 2: contributions and tasks from the commit JSON Lines that the collector writes.

Input: data/commits/*.jsonl, one Perceval git item per line; commit fields are under `data`.
A merge commit (two or more parents) stands for a merged MR/PR. Its subject or body says which one.
Output: JSON-ready dicts, one per group (contributions) or per merge (tasks).

"Me" is decided by AUTHOR_REGEX (case-insensitive) over `Name <email>`, as in the collector.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .gitctx import redact_url

GROUPS = ("project", "repo", "month")

_GITLAB_MR = re.compile(r"See merge request (?P<path>[^\s!]+)!(?P<iid>\d+)")
_GITHUB_PR = re.compile(r"^Merge pull request #(?P<iid>\d+)")
_MERGE = re.compile(r"^Merge ")
_SCP_REMOTE = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>.+)$")


class CommitDataError(ValueError):
    """A commit line is not in the expected shape. The message names the file and line."""


@dataclass(frozen=True)
class Commit:
    origin: str
    sha: str
    author: str
    day: date
    message: str
    parents: tuple[str, ...]

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def subject(self) -> str:
        return self.message.strip().splitlines()[0] if self.message.strip() else ""


def parse_author_date(text: str) -> date:
    """Day of a commit's author date. Accepts git's default form and ISO 8601."""
    normalised = " ".join(text.split())
    for fmt in ("%a %b %d %H:%M:%S %Y %z", "%a %b %d %H:%M:%S %Y"):
        try:
            return datetime.strptime(normalised, fmt).date()
        except ValueError:
            continue
    return datetime.fromisoformat(normalised).date()


def parse_item(item: dict[str, Any], where: str) -> Commit:
    try:
        data = item["data"]
        return Commit(
            origin=redact_url(str(item["origin"])),  # tokens in remotes never reach output
            sha=str(data["commit"]),
            author=str(data["Author"]),
            day=parse_author_date(str(data["AuthorDate"])),
            message=str(data.get("message") or ""),
            parents=tuple(str(p) for p in data["parents"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CommitDataError(f"{where}: not a commit item ({error})") from error


def load_commits(commits_dir: Path) -> list[Commit]:
    """Every commit in every *.jsonl file under `commits_dir`, de-duplicated by (origin, sha)."""
    if not commits_dir.is_dir():
        return []
    seen: set[tuple[str, str]] = set()
    commits: list[Commit] = []
    for path in sorted(commits_dir.glob("*.jsonl")):
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            where = f"{path}:{number}"
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as error:
                raise CommitDataError(f"{where}: not valid JSON ({error.msg})") from error
            if not isinstance(item, dict):
                raise CommitDataError(f"{where}: not a JSON object")
            if item.get("category", "commit") != "commit":
                continue
            commit = parse_item(item, where)
            key = (commit.origin, commit.sha)
            if key not in seen:
                seen.add(key)
                commits.append(commit)
    return commits


def mine(commits: Iterable[Commit], author_pattern: str) -> list[Commit]:
    """Commits whose `Name <email>` matches the regular expression (case-insensitive)."""
    pattern = re.compile(author_pattern, re.IGNORECASE)
    return [c for c in commits if pattern.search(c.author)]


def merge_reference(message: str) -> tuple[str, int | None]:
    """(kind, number) for a merge commit message. kind is 'mr', 'pr' or 'merge'."""
    if match := _GITLAB_MR.search(message):
        return "mr", int(match.group("iid"))
    if match := _GITHUB_PR.search(message):
        return "pr", int(match.group("iid"))
    return "merge", None


def project_of(origin: str) -> str:
    """The last path segment of the remote: https://host/group/project.git -> project."""
    return _path_of(origin).rsplit("/", 1)[-1] or origin


def _path_of(origin: str) -> str:
    """The repository path of a remote: https://host/a/b.git and git@host:a/b.git both give a/b."""
    if "://" in origin:
        rest = origin.split("://", 1)[1]
        path = rest.split("/", 1)[1] if "/" in rest else ""
    elif scp := _SCP_REMOTE.match(origin):
        path = scp.group("path")
    else:
        path = origin
    return path.rstrip("/").removesuffix(".git")


def web_base(origin: str) -> str | None:
    """The browsable https address of a remote, or None when it cannot be worked out."""
    path = _path_of(origin)
    if "://" in origin:
        scheme, rest = origin.split("://", 1)
        host = rest.split("/", 1)[0].rsplit("@", 1)[-1]
        if not host or not path:
            return None
        if scheme in ("http", "https"):
            return f"{scheme}://{host}/{path}"
        # ssh:// and git:// ports are git's, not the web's: drop them.
        return f"https://{host.split(':', 1)[0]}/{path}"
    scp = _SCP_REMOTE.match(origin)
    if scp is None or not path:
        return None
    return f"https://{scp.group('host')}/{path}"


def _group_key(commit: Commit, group_by: str) -> str:
    if group_by == "project":
        return project_of(commit.origin)
    if group_by == "repo":
        return commit.origin
    return f"{commit.day:%Y-%m}"


def contributions(commits: Iterable[Commit], group_by: str) -> list[dict[str, Any]]:
    """One row per group: commits authored, merges made, first and last day."""
    if group_by not in GROUPS:
        raise ValueError(f"group-by must be one of {', '.join(GROUPS)}")
    groups: dict[str, dict[str, Any]] = {}
    for commit in commits:
        row = groups.setdefault(
            _group_key(commit, group_by),
            {"group": None, "commits": 0, "merges": 0, "first": commit.day, "last": commit.day},
        )
        if commit.is_merge:
            row["merges"] += 1
        else:
            row["commits"] += 1
        row["first"] = min(row["first"], commit.day)
        row["last"] = max(row["last"], commit.day)
    rows = []
    for key in sorted(groups):
        row = groups[key]
        row["group"] = key
        row["first"] = row["first"].isoformat()
        row["last"] = row["last"].isoformat()
        rows.append(row)
    return rows


def tasks(commits: Iterable[Commit]) -> list[dict[str, Any]]:
    """One row per merge commit: the MR/PR it stands for, or a plain merge."""
    rows = []
    for commit in sorted(commits, key=lambda c: (c.day, c.sha), reverse=True):
        if not commit.is_merge:
            continue
        kind, number = merge_reference(commit.message)
        base = web_base(commit.origin)
        url = None
        if base and number is not None:
            url = f"{base}/pull/{number}" if kind == "pr" else f"{base}/-/merge_requests/{number}"
        rows.append(
            {
                "kind": kind,
                "repo": commit.origin,
                "number": number,
                "title": commit.subject,
                "url": url,
                "date": commit.day.isoformat(),
            }
        )
    return rows
