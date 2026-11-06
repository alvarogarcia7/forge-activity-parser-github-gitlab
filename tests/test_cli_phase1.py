"""Phase 1 CLI: add, select, view, validate, retry, and the environment handling around them."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from helpers import make_repo, rec
from rag.cli import EXIT_INVALID, EXIT_NO_MATCH, EXIT_OK, main
from rag.store import Store

REPO_SRC = Path(__file__).resolve().parents[1] / "src"


def seed(data_dir: Path, *records, db: str = "achievements") -> Store:
    store = Store(data_dir, db)
    for record in records:
        store.append(record)
    return store


def parse_lines(out: str) -> list[dict]:
    return [json.loads(line) for line in out.splitlines() if line.strip()]


# --- add -------------------------------------------------------------------------------

def test_add_writes_a_record_without_source(run, data_dir: Path) -> None:
    code, out, err = run("add", "Shipped   the  thing", "--no-source", "--topic", "Kube, helm",
                          "--project", "Infra", "--category", "professional", "--free", "Tier=beta")
    assert code == EXIT_OK and err == ""
    assert out.startswith("id: ")
    [saved] = Store(data_dir, "achievements").load()
    assert saved.idea == "Shipped the thing"  # whitespace collapsed
    assert saved.topics == ["kube", "helm"]
    assert saved.project == "infra" and saved.category == "professional"
    assert saved.free == {"tier": "beta"}
    assert saved.source is None
    assert out.strip() == f"id: {saved.id}"


def test_add_captures_git_source_from_the_current_directory(run, tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path / "work", remote="https://tok@example.com/o/r.git", branch="topic")
    monkeypatch.chdir(repo)
    code, _, _ = run("add", "from git", "--path", "src/app.py")
    assert code == EXIT_OK
    [saved] = Store(tmp_path / "data", "achievements").load()
    assert saved.source is not None
    assert saved.source["remote"] == "https://example.com/o/r.git"
    assert saved.source["branch"] == "topic"
    assert saved.source["path"] == "src/app.py"
    assert saved.source["commit"]


def test_add_outside_a_repository_has_null_source(run, data_dir: Path) -> None:
    assert run("add", "no repo")[0] == EXIT_OK
    [saved] = Store(data_dir, "achievements").load()
    assert saved.source is None


def test_add_rejects_an_empty_idea(run, data_dir: Path) -> None:
    code, _, err = run("add", "   ", "--no-source")
    assert code == EXIT_INVALID
    assert "rejected, nothing written" in err and "idea" in err
    assert not (data_dir / "achievements.jsonl").exists()


def test_add_rejects_a_malformed_free_pair(run) -> None:
    code, _, err = run("add", "x", "--no-source", "--free", "novalue")
    assert code == EXIT_INVALID
    assert "KEY=VALUE" in err


def test_add_to_a_named_database(run, data_dir: Path) -> None:
    assert run("add", "for work", "--db", "work", "--no-source")[0] == EXIT_OK
    assert (data_dir / "work.jsonl").exists()
    assert not (data_dir / "achievements.jsonl").exists()


def test_add_with_an_invalid_database_name_fails(run) -> None:
    code, _, err = run("add", "x", "--db", "Bad Name", "--no-source")
    assert code == EXIT_INVALID
    assert "invalid database name" in err


def test_default_database_comes_from_settings(run, data_dir: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAG_DB", "mine")
    assert run("add", "x", "--no-source")[0] == EXIT_OK
    assert (data_dir / "mine.jsonl").exists()


# --- select ----------------------------------------------------------------------------

@pytest.fixture
def seeded(data_dir: Path) -> Path:
    seed(
        data_dir,
        rec("kube rollout", day="2026-10-02", topics=["kubernetes", "helm"], project="infra",
            category="professional", free={"tier": "beta"}, ident="1" * 32),
        rec("docker image", day="2026-11-01", topics=["docker"], project="infra",
            category="personal", ident="2" * 32),
        rec("kube autoscaler", day="2026-11-04", topics=["kubernetes"], project="api",
            category="professional", free={"tier": "stable", "owners": ["ana"]}, ident="3" * 32),
    )
    return data_dir


def test_select_prints_jsonl_for_matching_records(run, seeded: Path) -> None:
    code, out, _ = run("select", "--topic=kubernetes")
    assert code == EXIT_OK
    rows = parse_lines(out)
    assert [r["idea"] for r in rows] == ["kube rollout", "kube autoscaler"]
    assert set(rows[0]) == {"id", "date", "time", "idea", "topics", "project", "category", "free", "source"}


TODAY = date(2026, 11, 6)


def test_select_absolute_range(run, seeded: Path) -> None:
    code, out, _ = run("select", "--date=2026-11-01..2026-11-30", "--fields", "idea")
    assert code == EXIT_OK
    assert parse_lines(out) == [{"idea": "docker image"}, {"idea": "kube autoscaler"}]


def test_select_relative_open_range_uses_today(run, seeded: Path) -> None:
    # -1m.. is 2026-10-06 through today: the 2026-10-02 rollout is outside it.
    code, out, _ = run("select", "--date=-1m..", "--fields", "idea", today=TODAY)
    assert code == EXIT_OK
    assert parse_lines(out) == [{"idea": "docker image"}, {"idea": "kube autoscaler"}]


def test_select_relative_range_that_ends_yesterday(run, seeded: Path) -> None:
    # ..-6d is everything up to 2026-10-31: only the October rollout.
    code, out, _ = run("select", "--date=..-6d", "--fields", "idea", today=TODAY)
    assert code == EXIT_OK
    assert parse_lines(out) == [{"idea": "kube rollout"}]


def test_select_keyword_yesterday(run, seeded: Path) -> None:
    # With today = 2026-11-05, y is 2026-11-04: the autoscaler record.
    code, out, _ = run("select", "--date=y", "--fields", "idea", today=date(2026, 11, 5))
    assert code == EXIT_OK
    assert parse_lines(out) == [{"idea": "kube autoscaler"}]


def test_select_fields_projection(run, seeded: Path) -> None:
    code, out, _ = run("select", "--project=api", "--fields", "idea,topics")
    assert code == EXIT_OK
    assert parse_lines(out) == [{"idea": "kube autoscaler", "topics": ["kubernetes"]}]


def test_select_rejects_unknown_fields(run, seeded: Path) -> None:
    code, _, err = run("select", "--fields", "idea,nope")
    assert code == EXIT_INVALID and "nope" in err


def test_select_all_topics_or_any_topic(run, seeded: Path) -> None:
    assert parse_lines(run("select", "--topic", "kubernetes,helm")[1])[0]["idea"] == "kube rollout"
    any_rows = parse_lines(run("select", "--topic", "helm,docker", "--any-topic")[1])
    assert [r["idea"] for r in any_rows] == ["kube rollout", "docker image"]


def test_select_any_value_must_match_every_given_value(run, seeded: Path) -> None:
    assert parse_lines(run("select", "--any=beta")[1])[0]["idea"] == "kube rollout"
    assert run("select", "--any=beta", "--any=stable")[0] == EXIT_NO_MATCH
    owned = parse_lines(run("select", "--any=ana", "--any=stable")[1])
    assert [r["idea"] for r in owned] == ["kube autoscaler"]


def test_select_text_and_category_filters(run, seeded: Path) -> None:
    rows = parse_lines(run("select", "--text", "DOCKER")[1])
    assert [r["idea"] for r in rows] == ["docker image"]
    rows = parse_lines(run("select", "--category", "professional")[1])
    assert [r["idea"] for r in rows] == ["kube rollout", "kube autoscaler"]


def test_select_line_format(run, seeded: Path) -> None:
    code, out, _ = run("select", "--project=api", "--format", "line")
    assert code == EXIT_OK
    record_id, body = out.strip().split("\t")
    assert record_id == "3" * 32
    assert "kube autoscaler" in body and "(api)" in body


def test_select_no_match_exits_one_and_prints_nothing(run, seeded: Path) -> None:
    code, out, _ = run("select", "--topic", "nothing-here")
    assert code == EXIT_NO_MATCH and out == ""


def test_select_on_missing_database_is_no_match(run, data_dir: Path) -> None:
    assert run("select", "--db", "absent")[0] == EXIT_NO_MATCH


def test_select_invalid_date_is_an_error(run, seeded: Path) -> None:
    code, _, err = run("select", "--date=2026-13")
    assert code == EXIT_INVALID and "invalid date" in err


def test_select_from_a_named_database(run, seeded: Path) -> None:
    seed(seeded, rec("only in work", topics=["x"], ident="9" * 32), db="work")
    rows = parse_lines(run("select", "--db", "work")[1])
    assert [r["idea"] for r in rows] == ["only in work"]


# --- view ------------------------------------------------------------------------------

def test_view_prints_detail(run, seeded: Path) -> None:
    code, out, _ = run("view", "1111")
    assert code == EXIT_OK
    assert "kube rollout" in out and "Remote" in out


def test_view_unknown_or_ambiguous_id_is_an_error(run, seeded: Path) -> None:
    assert run("view", "ffff")[0] == EXIT_INVALID
    seed(seeded, rec("clash", ident="1" + "5" * 31), db="achievements")
    code, _, err = run("view", "1")
    assert code == EXIT_INVALID and "matches 2" in err


# --- validate --------------------------------------------------------------------------

def test_validate_good_file(run, tmp_path: Path) -> None:
    path = tmp_path / "ok.jsonl"
    path.write_text(json.dumps(rec("ok").to_dict()) + "\n", encoding="utf-8")
    code, out, _ = run("validate", str(path))
    assert code == EXIT_OK and "valid: 1 record(s)" in out


def test_validate_bad_file_reports_problems(run, tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    code, _, err = run("validate", str(path))
    assert code == EXIT_INVALID and "invalid: 9 problem(s)" in err


def test_validate_missing_file_and_bad_schema(run, tmp_path: Path) -> None:
    assert run("validate", str(tmp_path / "nope.jsonl"))[0] == EXIT_INVALID
    path = tmp_path / "x.jsonl"
    path.write_text("", encoding="utf-8")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    code, _, err = run("validate", str(path), "--schema", str(broken))
    assert code == EXIT_INVALID and "not valid JSON" in err
    invalid_schema = tmp_path / "invalid.schema.json"
    invalid_schema.write_text(json.dumps({"type": 5}), encoding="utf-8")
    code, _, err = run("validate", str(path), "--schema", str(invalid_schema))
    assert code == EXIT_INVALID and "not a valid JSON Schema" in err


# --- retry -----------------------------------------------------------------------------

def test_retry_inserts_a_valid_file_and_removes_it(run, data_dir: Path, tmp_path: Path) -> None:
    path = tmp_path / "captured.json"
    data = rec("from a file", topics=["Retry Me"]).to_dict()
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out, _ = run("retry", str(path))
    assert code == EXIT_OK and out.startswith("id: ")
    assert not path.exists()
    [saved] = Store(data_dir, "achievements").load()
    assert saved.topics == ["retry-me"]  # normalised on the way in


def test_retry_keeps_a_rejected_file(run, data_dir: Path, tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    data = rec("x").to_dict()
    data["idea"] = " "
    path.write_text(json.dumps(data), encoding="utf-8")
    code, _, err = run("retry", str(path))
    assert code == EXIT_INVALID and "idea" in err
    assert path.exists()


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
def test_retry_rejects_non_records(run, tmp_path: Path, content: str) -> None:
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")
    code, _, err = run("retry", str(path))
    assert code == EXIT_INVALID and "rejected" in err
    assert path.exists()


def test_retry_missing_file(run, tmp_path: Path) -> None:
    code, _, err = run("retry", str(tmp_path / "nope.json"))
    assert code == EXIT_INVALID and "no such file" in err


# --- settings and entry point ----------------------------------------------------------

def test_explicit_env_file_is_read(run, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RAG_DATA_DIR", raising=False)
    env = tmp_path / "settings.env"
    env.write_text(f"RAG_DATA_DIR={tmp_path / 'from-env'}\nRAG_DB=profile\n", encoding="utf-8")
    code, _, _ = run("--env", str(env), "add", "via env file", "--no-source")
    assert code == EXIT_OK
    assert (tmp_path / "from-env" / "profile.jsonl").exists()


def test_missing_explicit_env_file_is_an_error(run, tmp_path: Path) -> None:
    code, _, err = run("--env", str(tmp_path / "missing.env"), "select")
    assert code == EXIT_INVALID and "env file not found" in err


def test_invalid_settings_file_is_an_error(run, tmp_path: Path) -> None:
    env = tmp_path / "bad.env"
    env.write_text("this line has no equals\n", encoding="utf-8")
    code, _, err = run("--env", str(env), "select")
    assert code == EXIT_INVALID and "expected KEY=VALUE" in err


def test_python_m_rag_help_runs() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "rag", "--help"],
        env={"PYTHONPATH": str(REPO_SRC), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0
    assert "select" in done.stdout and "retry" in done.stdout


# --- regressions for the phase 1 verification review -----------------------------------

def test_select_normalises_filter_values(run, seeded: Path) -> None:  # D1
    rows = parse_lines(run("select", "--topic", "KUBERNETES", "--project", "API", "--category", "Professional")[1])
    assert [r["idea"] for r in rows] == ["kube autoscaler"]


def test_add_and_select_refuse_values_that_normalise_to_nothing(run, seeded: Path) -> None:  # D5
    code, _, err = run("add", "x", "--no-source", "--topic", "日本")
    assert code == EXIT_INVALID and "no ASCII letters" in err
    code, _, err = run("add", "x", "--no-source", "--project", "测试")
    assert code == EXIT_INVALID and "no ASCII letters" in err
    code, _, err = run("select", "--category", "分类")
    assert code == EXIT_INVALID and "no ASCII letters" in err


def test_blank_category_is_allowed_and_means_none(run, data_dir: Path) -> None:  # D5
    assert run("add", "x", "--no-source", "--category", "   ")[0] == EXIT_OK


def test_select_reports_corrupt_lines_with_location(run, seeded: Path) -> None:  # D3
    path = seeded / "achievements.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
    code, out, err = run("select")
    assert code == EXIT_INVALID and out == ""
    assert f"{path}:4: not valid JSON" in err


def test_select_reports_records_that_are_not_objects(run, seeded: Path) -> None:  # D3
    path = seeded / "achievements.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "[1, 2]\n", encoding="utf-8")
    code, _, err = run("select")
    assert code == EXIT_INVALID and f"{path}:4: not an achievement record" in err


def test_view_reports_corrupt_database(run, seeded: Path) -> None:  # D3
    path = seeded / "achievements.jsonl"
    path.write_text('{"id": "x"}\n', encoding="utf-8")
    code, _, err = run("view", "1111")
    assert code == EXIT_INVALID and "not an achievement record" in err


def test_retry_refuses_an_impossible_date(run, data_dir: Path, tmp_path: Path) -> None:  # D2
    path = tmp_path / "feb30.json"
    data = rec("feb thirtieth").to_dict()
    data["date"] = "2026-02-30"
    path.write_text(json.dumps(data), encoding="utf-8")
    code, _, err = run("retry", str(path))
    assert code == EXIT_INVALID and "date" in err
    assert not (data_dir / "achievements.jsonl").exists()


def test_validate_flags_an_impossible_date(run, tmp_path: Path) -> None:  # D2
    path = tmp_path / "db.jsonl"
    data = rec("feb thirtieth").to_dict()
    data["date"] = "2026-02-30"
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    code, _, err = run("validate", str(path))
    assert code == EXIT_INVALID and "date" in err


def test_database_name_with_trailing_newline_is_refused(run) -> None:  # D4
    code, _, err = run("add", "x", "--db", "abc\n", "--no-source")
    assert code == EXIT_INVALID and "invalid database name" in err


def test_join_negative_specs_only_touches_spec_options() -> None:
    from rag.cli import join_negative_specs

    assert join_negative_specs(["select", "--date", "-1m..", "--any", "x"]) == [
        "select", "--date=-1m..", "--any", "x"]
    assert join_negative_specs(["select", "--date", "--topic", "a"]) == ["select", "--date", "--topic", "a"]
    assert join_negative_specs(["select", "--date"]) == ["select", "--date"]
