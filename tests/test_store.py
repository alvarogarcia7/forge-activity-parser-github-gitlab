import json
from pathlib import Path

import pytest

from helpers import rec
from rag.schema import SchemaRejected
from rag.store import Store


def test_missing_file_loads_as_empty(tmp_path: Path) -> None:
    assert Store(tmp_path, "achievements").load() == []


def test_append_creates_directory_and_round_trips(tmp_path: Path) -> None:
    store = Store(tmp_path / "nested", "work")
    first = rec("first", topics=["a"], free={"k": "v"})
    second = rec("second", project="p")
    store.append(first)
    store.append(second)
    assert store.path == tmp_path / "nested" / "work.jsonl"
    assert store.load() == [first, second]
    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["idea"] == "first"


def test_append_refuses_invalid_records(tmp_path: Path) -> None:
    store = Store(tmp_path, "achievements")
    with pytest.raises(SchemaRejected) as error:
        store.append(rec("  "))
    assert any("idea" in m for m in error.value.messages)
    assert not store.path.exists()


@pytest.mark.parametrize("name", ["", "Bad", "has space", "../escape", "-leading"])
def test_invalid_database_names_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="invalid database name"):
        Store(tmp_path, name)


def test_get_by_full_id_and_unique_prefix(tmp_path: Path) -> None:
    store = Store(tmp_path, "achievements")
    target = rec("target", ident="ab" + "0" * 30)
    store.append(target)
    store.append(rec("other", ident="cd" + "0" * 30))
    assert store.get(target.id) == target
    assert store.get("AB") == target  # case-insensitive, whitespace-trimmed
    assert store.get("  ab0  ") == target


def test_get_refuses_empty_missing_and_ambiguous_ids(tmp_path: Path) -> None:
    store = Store(tmp_path, "achievements")
    store.append(rec("one", ident="a" * 32))
    store.append(rec("two", ident="a" + "b" * 31))
    with pytest.raises(LookupError, match="required"):
        store.get("   ")
    with pytest.raises(LookupError, match="no achievement"):
        store.get("ffff")
    with pytest.raises(LookupError, match="matches 2"):
        store.get("a")


def test_blank_lines_in_a_database_are_skipped(tmp_path: Path) -> None:
    store = Store(tmp_path, "achievements")
    store.append(rec("one"))
    store.path.write_text(store.path.read_text(encoding="utf-8") + "\n   \n", encoding="utf-8")
    assert [a.idea for a in store.load()] == ["one"]
