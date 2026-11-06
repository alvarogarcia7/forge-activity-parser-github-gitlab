"""The achievement record: the one shape every other module works with (schema v1)."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

FIELDS = ("id", "date", "time", "idea", "topics", "project", "category", "free", "source")


def normalize_slug(text: str) -> str:
    """lower-and-dashes: 'Machine Learning_v2' -> 'machine-learning-v2'. Non-ASCII letters are dropped."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def unslugged(values: Iterable[str]) -> list[str]:
    """Input values that have no ASCII letters or digits, so normalisation would erase them."""
    return [v for v in values if v.strip() and not normalize_slug(v)]


def normalize_topics(values: Iterable[str]) -> list[str]:
    """Normalize each topic (tag), drop empties and duplicates, keep the order."""
    topics: list[str] = []
    for value in values:
        slug = normalize_slug(value)
        if slug and slug not in topics:
            topics.append(slug)
    return topics


def free_values(value: Any) -> list[str]:
    """The text of one free value: a list contributes each item."""
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def searchable_text(a: "Achievement") -> str:
    """Every text field of a record, one per line. Shared by substring and full-text search."""
    parts = [a.idea, *a.topics, a.project or "", a.category or ""]
    for value in a.free.values():
        parts.extend(free_values(value))
    return "\n".join(parts)


def parse_free(pairs: Iterable[str]) -> dict[str, str]:
    """Turn ['key=value', ...] into a dict with slug keys. Raises ValueError on a bad pair."""
    free: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        slug = normalize_slug(key)
        if not sep or not slug:
            raise ValueError(f"free field must look like KEY=VALUE, got {pair!r}")
        free[slug] = value.strip()
    return free


@dataclass
class Achievement:
    id: str
    date: str  # YYYY-MM-DD (local)
    time: str  # HH:MM:SS+ZZZZ (local, with UTC offset)
    idea: str
    topics: list[str] = field(default_factory=list)
    project: str | None = None
    category: str | None = None
    free: dict[str, Any] = field(default_factory=dict)
    source: dict[str, str | None] | None = None

    @property
    def day(self) -> dt.date:
        return dt.date.fromisoformat(self.date)

    @classmethod
    def create(
        cls,
        idea: str,
        topics: Iterable[str] = (),
        project: str | None = None,
        category: str | None = None,
        free: dict[str, Any] | None = None,
        source: dict[str, str | None] | None = None,
        now: dt.datetime | None = None,
    ) -> "Achievement":
        now = now or dt.datetime.now().astimezone()
        return cls(
            id=uuid.uuid4().hex,
            date=f"{now:%Y-%m-%d}",
            time=f"{now:%H:%M:%S%z}",
            idea=idea,
            topics=normalize_topics(topics),
            project=normalize_slug(project or "") or None,
            category=normalize_slug(category or "") or None,
            free=dict(free or {}),
            source=source,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Achievement":
        """Build from a record that already passed the schema check."""
        return cls(
            id=data["id"],
            date=data["date"],
            time=data["time"],
            idea=data["idea"],
            topics=list(data["topics"]),
            project=data["project"],
            category=data["category"],
            free=dict(data["free"]),
            source=data["source"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date,
            "time": self.time,
            "idea": self.idea,
            "topics": list(self.topics),
            "project": self.project,
            "category": self.category,
            "free": dict(self.free),
            "source": dict(self.source) if self.source is not None else None,
        }
