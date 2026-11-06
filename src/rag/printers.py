"""Presentation: turn achievements into text. No file or terminal access here."""

from __future__ import annotations

import json
import re

from .model import FIELDS, Achievement


def jsonl(a: Achievement, fields: list[str] | None = None) -> str:
    """One JSON object per record, all fields unless `fields` narrows them."""
    data = a.to_dict()
    if fields:
        data = {name: data[name] for name in fields}
    return json.dumps(data, ensure_ascii=False)


_CONTROL = re.compile(r"[\t\r\n]+")


def _one_line(text: object) -> str:
    """Tabs and newlines would split a row (fzf reads one record per line, the id before the first tab)."""
    return _CONTROL.sub(" ", str(text))


def line(a: Achievement) -> str:
    """One human-readable line: '<id><TAB><date time> [category] idea #topics (project) key=value'."""
    parts = [f"{a.date} {a.time[:5]}"]
    if a.category:
        parts.append(f"[{a.category}]")
    parts.append(_one_line(a.idea))
    if a.topics:
        parts.append(" ".join(f"#{t}" for t in a.topics))
    if a.project:
        parts.append(f"({a.project})")
    for key, value in a.free.items():
        parts.append(_one_line(f"{key}={value}"))
    return f"{a.id}\t{' '.join(parts)}"


def detail(a: Achievement) -> str:
    """Labelled, multi-line view of one achievement."""
    free = ", ".join(f"{k}={v}" for k, v in a.free.items())
    source = a.source or {}
    rows = [
        ("ID", a.id),
        ("Date", a.date),
        ("Time", a.time),
        ("Idea", a.idea),
        ("Category", a.category),
        ("Project", a.project),
        ("Topics", ", ".join(a.topics)),
        ("Free", free),
        ("Remote", source.get("remote")),
        ("Branch", source.get("branch")),
        ("Commit", source.get("commit")),
        ("Path", source.get("path")),
    ]
    return "\n".join(f"{label:<10}{value or '-'}" for label, value in rows)


def check_fields(names: list[str]) -> list[str]:
    """Names that are not record fields. Empty list means all are valid."""
    return [name for name in names if name not in FIELDS]
