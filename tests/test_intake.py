import pytest

from helpers import rec
from rag.intake import RecordRejected, normalize_record, save_record
from rag.store import Store


def test_normalize_record_slugs_topics_project_category_and_free_keys() -> None:
    out = normalize_record({
        "topics": ["Kube Net", "kube-net", 7],
        "project": "My Project",
        "category": "",
        "free": {"Tier Level": "beta", 5: "kept"},
    })
    assert out["topics"] == ["kube-net", 7]  # non-strings are left for the schema to report
    assert out["project"] == "my-project"
    assert out["category"] is None
    assert out["free"] == {"tier-level": "beta", 5: "kept"}


def test_normalize_record_leaves_other_shapes_alone() -> None:
    out = normalize_record({"topics": "not a list", "project": 3, "free": ["x"]})
    assert out == {"topics": "not a list", "project": 3, "free": ["x"]}


def test_save_record_appends_a_valid_record(tmp_path) -> None:
    store = Store(tmp_path, "achievements")
    data = rec("valid", topics=["Kube"]).to_dict()
    data["topics"] = ["Kube"]  # un-normalised on purpose
    saved = save_record(store, data)
    assert saved.topics == ["kube"]
    assert store.load() == [saved]


def test_save_record_rejects_and_writes_nothing(tmp_path) -> None:
    store = Store(tmp_path, "achievements")
    data = rec("ok").to_dict()
    data["idea"] = "   "
    with pytest.raises(RecordRejected) as error:
        save_record(store, data)
    assert error.value.messages and "idea" in error.value.messages[0]
    assert not store.path.exists()
