"""Intake: normalise, validate and save a record. Nothing is written if validation fails."""

from __future__ import annotations

from typing import Any

from .model import Achievement, normalize_slug
from .schema import SchemaRejected, schema_errors
from .store import Store


class RecordRejected(Exception):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


def normalize_record(data: dict[str, Any]) -> dict[str, Any]:
    """Apply lower-and-dashes to topics, project, category and free keys. Other problems go to the schema."""
    out = dict(data)
    if isinstance(out.get("topics"), list):
        topics: list[Any] = []
        for topic in out["topics"]:
            value = normalize_slug(topic) if isinstance(topic, str) else topic
            if value == "" or value in topics:
                continue
            topics.append(value)  # non-strings are kept, so the schema reports them
        out["topics"] = topics
    for key in ("project", "category"):
        if isinstance(out.get(key), str):
            out[key] = normalize_slug(out[key]) or None
    if isinstance(out.get("free"), dict):
        out["free"] = {
            (normalize_slug(k) if isinstance(k, str) else k): v for k, v in out["free"].items()
        }
    return out


def save_record(store: Store, data: dict[str, Any]) -> Achievement:
    """Normalise, validate, then append. Raises RecordRejected with the schema messages."""
    data = normalize_record(data)
    messages = schema_errors(data)
    if messages:
        raise RecordRejected(messages)
    achievement = Achievement.from_dict(data)
    try:
        store.append(achievement)
    except SchemaRejected as error:  # pragma: no cover - guarded by the check above
        raise RecordRejected(error.messages) from error
    return achievement
