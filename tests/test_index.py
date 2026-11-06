"""Phase 4: the ranked full-text index and `select --ranked`."""

import os
import sqlite3
from pathlib import Path

import pytest

from helpers import rec
from rag import index as index_module
from rag.cli import EXIT_INVALID, EXIT_NO_MATCH, EXIT_OK
from rag.index import IndexUnavailable, build, index_path, literal_words, query_for, ranked_ids
from rag.store import Store


@pytest.fixture
def store(data_dir: Path) -> Store:
    s = Store(data_dir, "achievements")
    s.append(rec("kubernetes rollout with helm charts", topics=["kubernetes"], ident="1" * 32))
    s.append(rec("docker image size", topics=["docker"], ident="2" * 32))
    s.append(rec("kubernetes kubernetes kubernetes autoscaling", topics=["kubernetes"], ident="3" * 32))
    s.append(rec("unrelated note", ident="4" * 32))
    return s


def parse(out: str) -> list[str]:
    import json

    return [json.loads(line)["id"] for line in out.splitlines() if line.strip()]


def test_build_indexes_every_record_and_reports_the_count(store: Store) -> None:
    assert build(store) == 4
    assert index_path(store).exists()
    assert not index_path(store).with_name(index_path(store).name + ".tmp").exists()


def test_ranked_ids_match_every_word_and_rank_by_relevance(store: Store) -> None:
    build(store)
    ids = ranked_ids(store, "kubernetes")
    assert set(ids) == {"1" * 32, "3" * 32}
    assert ranked_ids(store, "kubernetes helm") == ["1" * 32]
    assert ranked_ids(store, "nothing-matches-this") == []


def test_query_for_quotes_words_so_punctuation_is_literal() -> None:
    assert query_for('say "hi"') == '"say" AND """hi"""'
    assert query_for("c++ x") == '"c++" AND "x"'
    assert query_for('a"b') == '"a""b"'


def test_query_for_rejects_empty_text() -> None:
    with pytest.raises(IndexUnavailable, match="at least one word"):
        query_for("   ")


def test_missing_index_is_reported(store: Store) -> None:
    with pytest.raises(IndexUnavailable, match="no index"):
        ranked_ids(store, "kubernetes")


def test_index_is_refused_once_the_data_changes(store: Store) -> None:
    build(store)
    store.append(rec("a later record", ident="5" * 32))
    with pytest.raises(IndexUnavailable, match="does not match its data"):
        ranked_ids(store, "kubernetes")


def test_back_dating_the_data_file_does_not_hide_a_change(store: Store) -> None:
    # The check is on content, not on mtime: an edited file with an old timestamp is still refused.
    build(store)
    store.append(rec("a later record", ident="5" * 32))
    old = store.path.stat().st_mtime - 10_000
    os.utime(store.path, (old, old))
    with pytest.raises(IndexUnavailable, match="does not match its data"):
        ranked_ids(store, "kubernetes")


def test_unchanged_data_with_a_newer_mtime_is_still_fine(store: Store) -> None:
    build(store)
    future = store.path.stat().st_mtime + 10_000
    os.utime(store.path, (future, future))
    assert set(ranked_ids(store, "kubernetes")) == {"1" * 32, "3" * 32}


def test_index_is_refused_when_the_database_file_is_gone(store: Store) -> None:
    build(store)
    store.path.unlink()
    with pytest.raises(IndexUnavailable, match="does not match its data"):
        ranked_ids(store, "kubernetes")


def test_concurrent_style_rebuilds_never_share_a_temp_file(store: Store) -> None:
    build(store)
    build(store)
    assert list(index_path(store).parent.glob("*.tmp")) == []
    assert set(ranked_ids(store, "kubernetes")) == {"1" * 32, "3" * 32}


def test_damaged_index_is_reported_not_crashed(store: Store) -> None:
    build(store)
    index_path(store).write_bytes(b"this is not sqlite at all, just text" * 100)
    with pytest.raises(IndexUnavailable, match="damaged|unreadable"):
        ranked_ids(store, "kubernetes")


def test_punctuated_words_are_matched_literally(store: Store) -> None:
    store.append(rec("wrote a C++ parser", ident="6" * 32))
    store.append(rec("compared C and Go build times", ident="7" * 32))
    build(store)
    # The FTS layer only sees tokens, so 'c++' finds both; the CLI then requires the literal text.
    assert set(ranked_ids(store, "c++")) == {"6" * 32, "7" * 32}
    assert literal_words("c++ and go") == ["c++"]


def test_cli_ranked_select_requires_punctuated_words_literally(run, store: Store) -> None:
    store.append(rec("wrote a C++ parser", ident="6" * 32))
    store.append(rec("compared C and Go build times", ident="7" * 32))
    run("index")
    code, out, _ = run("select", "--ranked", "--text", "c++")
    assert code == EXIT_OK and parse(out) == ["6" * 32]


def test_missing_fts5_is_reported_clearly(store: Store, monkeypatch) -> None:
    real_connect = sqlite3.connect

    class NoFts:
        def __init__(self, *args, **kwargs) -> None:
            self._db = real_connect(*args, **kwargs)

        def execute(self, sql, *params):
            if "fts5" in sql:
                raise sqlite3.OperationalError("no such module: fts5")
            return self._db.execute(sql, *params)

        def __getattr__(self, name):
            return getattr(self._db, name)

    monkeypatch.setattr(index_module.sqlite3, "connect", lambda *a, **k: NoFts(*a, **k))
    with pytest.raises(IndexUnavailable, match="lacks FTS5"):
        build(store)
    assert not index_path(store).exists()


def test_other_sqlite_errors_are_reported(store: Store, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(index_module.sqlite3, "connect", broken)
    with pytest.raises(IndexUnavailable, match="cannot build the index: disk I/O error"):
        build(store)
    assert list(index_path(store).parent.glob("*.tmp")) == []


def test_cli_index_and_ranked_select(run, store: Store) -> None:
    code, out, _ = run("index")
    assert code == EXIT_OK and "indexed 4 record(s)" in out
    code, out, _ = run("select", "--ranked", "--text", "kubernetes")
    assert code == EXIT_OK
    assert set(parse(out)) == {"1" * 32, "3" * 32}


def test_ranked_select_keeps_other_filters(run, store: Store) -> None:
    run("index")
    code, out, _ = run("select", "--ranked", "--text", "kubernetes", "--topic", "kubernetes")
    assert code == EXIT_OK and set(parse(out)) == {"1" * 32, "3" * 32}
    assert run("select", "--ranked", "--text", "kubernetes", "--topic", "docker")[0] == EXIT_NO_MATCH
    assert run("select", "--ranked", "--text", "kubernetes", "--any=zzz")[0] == EXIT_NO_MATCH


def test_ranked_select_needs_text(run, store: Store) -> None:
    code, _, err = run("select", "--ranked")
    assert code == EXIT_INVALID and "--ranked needs --text" in err


def test_ranked_select_without_index_is_an_error(run, store: Store) -> None:
    code, _, err = run("select", "--ranked", "--text", "kubernetes")
    assert code == EXIT_INVALID and "rag index" in err


def test_ranked_select_with_no_hits_is_no_match(run, store: Store) -> None:
    run("index")
    assert run("select", "--ranked", "--text", "zzz")[0] == EXIT_NO_MATCH


def test_cli_index_reports_fts5_absence(run, store: Store, monkeypatch) -> None:
    def no_fts(*args, **kwargs):
        raise IndexUnavailable("this Python's SQLite lacks FTS5; ranked search is unavailable")

    monkeypatch.setattr(index_module, "build", no_fts)
    code, _, err = run("index")
    assert code == EXIT_INVALID and "lacks FTS5" in err


def test_failed_build_removes_its_temp_file(store: Store, monkeypatch) -> None:
    def explode(a):
        raise RuntimeError("boom while indexing")

    monkeypatch.setattr(index_module, "searchable_text", explode)
    with pytest.raises(RuntimeError, match="boom"):
        build(store)
    assert list(index_path(store).parent.glob("*.tmp")) == []
    assert not index_path(store).exists()


def test_non_fts5_build_error_is_reported(store: Store, monkeypatch) -> None:
    class Broken:
        def __init__(self, *args, **kwargs) -> None:
            self.calls = 0

        def execute(self, sql, *params):
            raise sqlite3.OperationalError("database is locked")

        def close(self) -> None:
            pass

    monkeypatch.setattr(index_module.sqlite3, "connect", lambda *a, **k: Broken())
    with pytest.raises(IndexUnavailable, match="cannot build the index: database is locked"):
        build(store)


def test_ranked_search_reports_a_missing_fts5_module(store: Store, monkeypatch) -> None:
    build(store)

    def no_fts(*args, **kwargs):
        raise sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(index_module.sqlite3, "connect", no_fts)
    with pytest.raises(IndexUnavailable, match="lacks FTS5"):
        ranked_ids(store, "kubernetes")


def test_ranked_search_reports_a_locked_index(store: Store, monkeypatch) -> None:
    build(store)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(index_module.sqlite3, "connect", locked)
    with pytest.raises(IndexUnavailable, match="unreadable"):
        ranked_ids(store, "kubernetes")
