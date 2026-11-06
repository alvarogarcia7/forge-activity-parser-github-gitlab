from datetime import date

from helpers import rec
from rag.query import Filter, matches, select

RECORDS = [
    rec("kube rollout", day="2026-10-02", topics=["kubernetes", "helm"], project="infra",
        category="professional", free={"tier": "beta", "owners": ["ana", "bo"], "count": 3}),
    rec("docker image", day="2026-11-01", topics=["docker"], project="infra", category="personal"),
    rec("kube autoscaler", day="2026-11-05", topics=["kubernetes"], project="api",
        category="professional", free={"tier": "stable"}),
    rec("plain note", day="2026-11-06"),
]


def ideas(found: list) -> list[str]:
    return [a.idea for a in found]


def test_empty_filter_keeps_everything_in_order() -> None:
    assert ideas(select(RECORDS, Filter())) == [a.idea for a in RECORDS]


def test_date_bounds_are_inclusive_and_open_ended() -> None:
    assert ideas(select(RECORDS, Filter(start=date(2026, 11, 1), end=date(2026, 11, 5)))) == [
        "docker image",
        "kube autoscaler",
    ]
    assert ideas(select(RECORDS, Filter(end=date(2026, 10, 2)))) == ["kube rollout"]
    assert ideas(select(RECORDS, Filter(start=date(2026, 11, 6)))) == ["plain note"]


def test_all_topics_must_match_by_default() -> None:
    found = select(RECORDS, Filter(topics=("kubernetes", "helm")))
    assert ideas(found) == ["kube rollout"]


def test_any_topic_matches_at_least_one() -> None:
    found = select(RECORDS, Filter(topics=("helm", "docker"), any_topic=True))
    assert ideas(found) == ["kube rollout", "docker image"]


def test_project_and_category_filters() -> None:
    assert ideas(select(RECORDS, Filter(project="infra"))) == ["kube rollout", "docker image"]
    assert ideas(select(RECORDS, Filter(category="professional"))) == ["kube rollout", "kube autoscaler"]
    assert ideas(select(RECORDS, Filter(project="infra", category="personal"))) == ["docker image"]


def test_any_value_matches_scalars_and_list_members() -> None:
    assert ideas(select(RECORDS, Filter(any_values=("beta",)))) == ["kube rollout"]
    assert ideas(select(RECORDS, Filter(any_values=("ana",)))) == ["kube rollout"]
    assert ideas(select(RECORDS, Filter(any_values=("3",)))) == ["kube rollout"]  # numbers compare as text


def test_several_any_values_must_all_match() -> None:
    assert ideas(select(RECORDS, Filter(any_values=("beta", "ana")))) == ["kube rollout"]
    assert select(RECORDS, Filter(any_values=("beta", "stable"))) == []


def test_text_is_case_insensitive_over_idea_topics_project_category_and_free_values() -> None:
    assert ideas(select(RECORDS, Filter(text="KUBE"))) == ["kube rollout", "kube autoscaler"]
    assert ideas(select(RECORDS, Filter(text="helm"))) == ["kube rollout"]
    assert ideas(select(RECORDS, Filter(text="api"))) == ["kube autoscaler"]
    assert ideas(select(RECORDS, Filter(text="professional"))) == ["kube rollout", "kube autoscaler"]
    assert ideas(select(RECORDS, Filter(text="bo"))) == ["kube rollout"]
    assert select(RECORDS, Filter(text="nothing like this")) == []


def test_filters_combine_with_and() -> None:
    found = select(
        RECORDS,
        Filter(start=date(2026, 10, 1), topics=("kubernetes",), project="api", any_values=("stable",)),
    )
    assert ideas(found) == ["kube autoscaler"]


def test_matches_checks_one_record() -> None:
    assert matches(RECORDS[0], Filter(project="infra"))
    assert not matches(RECORDS[0], Filter(project="api"))
