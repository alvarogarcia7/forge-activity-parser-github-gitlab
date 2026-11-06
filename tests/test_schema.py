import json
from pathlib import Path

import pytest
from jsonschema import SchemaError

from helpers import rec
from rag.model import Achievement
from rag.schema import SCHEMA_PATH, load_validator, schema_errors, validate_file

GOOD_SOURCE = {"remote": "https://h/x.git", "branch": "main", "commit": "abc1234", "path": None}


def good() -> dict:
    return Achievement.create("valid idea", topics=["k8s"], project="p", category="c",
                              free={"tier": "beta", "tags": ["a", "b"], "n": 3, "ok": True},
                              source=dict(GOOD_SOURCE)).to_dict()


def test_valid_record_has_no_errors() -> None:
    assert schema_errors(good()) == []


def test_null_project_category_and_source_are_valid() -> None:
    data = good()
    data.update(project=None, category=None, source=None, free={}, topics=[])
    assert schema_errors(data) == []


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"id": "short"}, "id"),
        ({"id": "G" * 32}, "id"),
        ({"date": "2026/11/06"}, "date"),
        ({"time": "10:00:00"}, "time"),
        ({"time": "10:00:00+04:00"}, "time"),
        ({"idea": "   "}, "idea"),
        ({"topics": ["a", "a"]}, "topics"),
        ({"topics": ["Bad Slug"]}, "topics"),
        ({"project": "Bad Slug"}, "project"),
        ({"category": "Bad Slug"}, "category"),
        ({"free": {"Bad Key": "v"}}, "free"),
        ({"free": {"nested": {"a": 1}}}, "free"),
        ({"free": {"list": [{"a": 1}]}}, "free"),
        ({"free": ["not", "an", "object"]}, "free"),
        ({"source": {"remote": None, "branch": None, "commit": None, "path": None, "extra": 1}}, "source"),
        ({"source": {"remote": None}}, "source"),
        ({"source": "a string"}, "source"),
        ({"unexpected": 1}, "unexpected"),
    ],
)
def test_schema_rejects_bad_fields(change: dict, fragment: str) -> None:
    data = good()
    data.update(change)
    errors = schema_errors(data)
    assert errors, f"expected a schema error for {change}"
    assert any(fragment in message for message in errors)


def test_missing_required_field_is_reported() -> None:
    data = good()
    del data["topics"]
    assert any("topics" in m for m in schema_errors(data))


def test_non_object_record_is_reported_at_root() -> None:
    errors = schema_errors([1, 2])
    assert errors and errors[0].startswith("record:")


def test_validator_is_cached_per_path() -> None:
    assert load_validator(SCHEMA_PATH) is load_validator(SCHEMA_PATH)


def test_invalid_schema_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.schema.json"
    bad.write_text(json.dumps({"type": 5}), encoding="utf-8")
    with pytest.raises(SchemaError):
        load_validator(bad)


def test_validate_file_reports_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "db.jsonl"
    invalid = good()
    invalid["idea"] = " "
    lines = [
        json.dumps(good()),
        "",
        "{not json",
        json.dumps(invalid),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    checked, problems = validate_file(path, SCHEMA_PATH)
    assert checked == 2  # the broken JSON line is not counted as a record
    assert len(problems) == 2
    assert problems[0].startswith(f"{path}:3: not valid JSON")
    assert problems[1].startswith(f"{path}:4: idea:")


def test_validate_file_accepts_a_good_file(tmp_path: Path) -> None:
    path = tmp_path / "ok.jsonl"
    path.write_text(json.dumps(rec(topics=["x"]).to_dict()) + "\n", encoding="utf-8")
    assert validate_file(path) == (1, [])
