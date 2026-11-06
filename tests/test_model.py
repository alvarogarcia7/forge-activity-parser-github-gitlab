import datetime as dt
import re

import pytest

from rag.model import Achievement, normalize_slug, normalize_topics, parse_free


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Machine Learning_v2", "machine-learning-v2"),
        ("Café Au Lait", "cafe-au-lait"),
        ("  --Kubernetes--  ", "kubernetes"),
        ("你好", ""),
        ("", ""),
    ],
)
def test_normalize_slug(text: str, expected: str) -> None:
    assert normalize_slug(text) == expected


def test_normalize_topics_drops_empties_and_duplicates_and_keeps_order() -> None:
    assert normalize_topics(["Kubernetes", "kubernetes", "", "B b", "!!"]) == ["kubernetes", "b-b"]


def test_parse_free_builds_slug_keys() -> None:
    assert parse_free(["Tier=beta", "k1=x=y"]) == {"tier": "beta", "k1": "x=y"}


@pytest.mark.parametrize("pair", ["novalue", "=value", "!!=value"])
def test_parse_free_rejects_bad_pairs(pair: str) -> None:
    with pytest.raises(ValueError, match="KEY=VALUE"):
        parse_free([pair])


def test_create_normalises_and_uses_given_time() -> None:
    now = dt.datetime(2026, 11, 6, 15, 40, 5, tzinfo=dt.timezone(dt.timedelta(hours=4)))
    a = Achievement.create(
        "did a thing",
        topics=["Kubernetes", "kubernetes"],
        project="My Project",
        category="",
        free={"k1": "v"},
        source={"remote": None, "branch": None, "commit": None, "path": None},
        now=now,
    )
    assert len(a.id) == 32
    assert a.date == "2026-11-06"
    assert a.time == "15:40:05+0400"
    assert a.topics == ["kubernetes"]
    assert a.project == "my-project"
    assert a.category is None
    assert a.free == {"k1": "v"}
    assert a.day == dt.date(2026, 11, 6)


def test_create_uses_current_time_when_not_given() -> None:
    a = Achievement.create("now")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date)
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}[+-]\d{4}", a.time)
    assert a.project is None and a.topics == [] and a.free == {} and a.source is None


def test_to_dict_and_from_dict_round_trip() -> None:
    a = Achievement(
        id="a" * 32,
        date="2026-11-06",
        time="10:00:00+0000",
        idea="idea",
        topics=["x"],
        project="p",
        category="c",
        free={"n": 1, "tags": ["a", "b"]},
        source={"remote": "https://h/x.git", "branch": "b", "commit": "abc", "path": None},
    )
    data = a.to_dict()
    assert data["source"] is not a.source  # to_dict copies
    assert Achievement.from_dict(data) == a


def test_to_dict_keeps_null_source_and_copies_lists() -> None:
    a = Achievement(id="b" * 32, date="2026-11-06", time="10:00:00+0000", idea="i", topics=["t"])
    data = a.to_dict()
    assert data["source"] is None
    data["topics"].append("mutated")
    assert a.topics == ["t"]
