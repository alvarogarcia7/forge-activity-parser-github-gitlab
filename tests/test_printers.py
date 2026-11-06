import json

import pytest

from helpers import rec
from rag.printers import check_fields, detail, jsonl, line


def test_jsonl_has_every_field_and_is_one_line() -> None:
    a = rec("idea one", topics=["t"], project="p", category="c", free={"k": "v"},
            source={"remote": "r", "branch": "b", "commit": "c", "path": None})
    text = jsonl(a)
    assert "\n" not in text
    assert json.loads(text) == a.to_dict()


def test_jsonl_keeps_only_requested_fields_in_order() -> None:
    a = rec("idea", topics=["t"])
    assert json.loads(jsonl(a, ["idea", "topics"])) == {"idea": "idea", "topics": ["t"]}


def test_jsonl_keeps_non_ascii_text_readable() -> None:
    assert "Café" in jsonl(rec("Café"))


def test_line_contains_every_part() -> None:
    a = rec("did it", day="2026-11-05", time="09:13:02+0400", topics=["k8s", "helm"],
            project="infra", category="professional", free={"tier": "beta"})
    text = line(a)
    record_id, body = text.split("\t")
    assert record_id == a.id
    assert body == "2026-11-05 09:13 [professional] did it #k8s #helm (infra) tier=beta"


def test_line_for_a_bare_record() -> None:
    a = rec("bare", day="2026-11-05", time="09:13:02+0400")
    assert line(a).endswith("\t2026-11-05 09:13 bare")


def test_detail_shows_source_and_placeholders() -> None:
    a = rec("detail", topics=["x"], source={"remote": "https://h/r.git", "branch": None,
                                            "commit": "abc", "path": "src/a.py"})
    text = detail(a)
    assert "ID" in text and a.id in text
    assert "Remote    https://h/r.git" in text
    assert "Branch    -" in text
    assert "Commit    abc" in text
    assert "Path      src/a.py" in text
    assert "Free      -" in text


def test_detail_without_source_or_free_values() -> None:
    text = detail(rec("none", source=None))
    assert "Remote    -" in text and "Path      -" in text


@pytest.mark.parametrize(("names", "expected"), [(["idea", "topics"], []), (["idea", "nope"], ["nope"])])
def test_check_fields(names: list[str], expected: list[str]) -> None:
    assert check_fields(names) == expected
