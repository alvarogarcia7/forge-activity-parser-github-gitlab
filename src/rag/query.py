"""Filtering of in-memory achievements. All filters are combined with AND."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from .model import Achievement, free_values, searchable_text


@dataclass(frozen=True)
class Filter:
    start: date | None = None  # None: no lower bound
    end: date | None = None  # None: no upper bound
    topics: tuple[str, ...] = ()
    any_topic: bool = False  # False: every topic must match; True: at least one
    project: str | None = None
    category: str | None = None
    any_values: tuple[str, ...] = ()  # each must equal some value of `free`
    text: str | None = None  # case-insensitive substring over the searchable text


def matches(a: Achievement, f: Filter) -> bool:
    if f.start is not None and a.day < f.start:
        return False
    if f.end is not None and a.day > f.end:
        return False
    if f.topics:
        hits = [topic in a.topics for topic in f.topics]
        if not (any(hits) if f.any_topic else all(hits)):
            return False
    if f.project is not None and a.project != f.project:
        return False
    if f.category is not None and a.category != f.category:
        return False
    for wanted in f.any_values:
        if not any(wanted in free_values(v) for v in a.free.values()):
            return False
    if f.text is not None and f.text.lower() not in searchable_text(a).lower():
        return False
    return True


def select(items: Iterable[Achievement], f: Filter) -> list[Achievement]:
    return [a for a in items if matches(a, f)]
