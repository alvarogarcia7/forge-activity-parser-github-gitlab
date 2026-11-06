"""Validation of records against schemas/achievement.schema.json (JSON Schema, draft 2020-12)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "schemas" / "achievement.schema.json"

_validators: dict[Path, Draft202012Validator] = {}


def load_validator(schema_path: Path = SCHEMA_PATH) -> Draft202012Validator:
    """Load and check a schema once per path. Raises jsonschema.SchemaError if the schema is invalid."""
    key = schema_path.resolve()
    if key not in _validators:
        schema = json.loads(key.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _validators[key] = Draft202012Validator(schema, format_checker=FormatChecker())
    return _validators[key]


def _messages(validator: Draft202012Validator, data: Any) -> list[str]:
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or 'record'}: {error.message}"
        for error in errors
    ]


def schema_errors(data: Any, schema_path: Path = SCHEMA_PATH) -> list[str]:
    """Human-readable problems with `data`; an empty list means it is valid."""
    return _messages(load_validator(schema_path), data)


def validate_file(path: Path, schema_path: Path = SCHEMA_PATH) -> tuple[int, list[str]]:
    """Validate every JSON Lines record in `path`. Returns (records checked, problems).

    Each problem starts with `file:line:` so it can be found in the file.
    """
    validator = load_validator(schema_path)
    checked = 0
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        where = f"{path}:{number}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            problems.append(f"{where}: not valid JSON: {error.msg}")
            continue
        checked += 1
        problems.extend(f"{where}: {message}" for message in _messages(validator, data))
    return checked, problems


class SchemaRejected(ValueError):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages
