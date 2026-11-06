"""Data access: the only module that reads or writes a database file (data/<db>.jsonl)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .model import FIELDS, Achievement
from .schema import SchemaRejected, schema_errors

DB_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")


class CorruptDatabase(ValueError):
    """A line of a database file is not a valid record. The message names the file and line."""


class Store:
    def __init__(self, data_dir: Path | str, db: str) -> None:
        if not DB_NAME.fullmatch(db):
            raise ValueError(f"invalid database name {db!r}: use lowercase letters, digits, - and _")
        self.data_dir = Path(data_dir)
        self.db = db

    @property
    def path(self) -> Path:
        return self.data_dir / f"{self.db}.jsonl"

    def load(self) -> list[Achievement]:
        if not self.path.exists():
            return []
        records = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            where = f"{self.path}:{number}"
            try:
                data = json.loads(line)
            except json.JSONDecodeError as error:
                raise CorruptDatabase(f"{where}: not valid JSON ({error.msg})") from error
            if not isinstance(data, dict) or set(data) != set(FIELDS):
                raise CorruptDatabase(f"{where}: not an achievement record (expected fields {', '.join(FIELDS)})")
            records.append(Achievement.from_dict(data))
        return records

    def append(self, achievement: Achievement) -> None:
        """Write one record at the end of the file. Nothing is written if the schema rejects it."""
        messages = schema_errors(achievement.to_dict())
        if messages:
            raise SchemaRejected(messages)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(achievement.to_dict(), ensure_ascii=False) + "\n")

    def get(self, ident: str) -> Achievement:
        """Find one record by full id or by a unique id prefix."""
        ident = ident.strip().lower()
        if not ident:
            raise LookupError("an id is required")
        matches = [a for a in self.load() if a.id.startswith(ident)]
        if not matches:
            raise LookupError(f"no achievement with id {ident!r}")
        if len(matches) > 1:
            raise LookupError(
                f"id prefix {ident!r} matches {len(matches)} achievements; use more characters"
            )
        return matches[0]
