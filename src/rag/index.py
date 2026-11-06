"""Phase 4: a ranked full-text index (SQLite FTS5, BM25) derived from a database file.

The index is a cache: it is rebuilt from data/<db>.jsonl by `rag index` and can be deleted at any
time. It is never the source of truth. It stores a SHA-256 of the data file it was built from, and
`select --ranked` refuses an index whose fingerprint no longer matches (so a restored or back-dated
file cannot slip past a timestamp check).

Known limits: the FTS5 tokenizer splits on punctuation and does not stem, and it finds nothing
inside unspaced CJK text. Words that contain punctuation (c++, a-b) are therefore also required as
literal substrings, and text search is only as good as the tokenizer for other scripts.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from .model import Achievement, searchable_text
from .store import Store


class IndexUnavailable(RuntimeError):
    """The index is missing, stale, unreadable, or this Python's SQLite has no FTS5."""


_FTS5_MISSING = "this Python's SQLite lacks FTS5; ranked search is unavailable"


def index_path(store: Store) -> Path:
    return store.data_dir / f"{store.db}.fts.sqlite"


def _fingerprint(store: Store) -> str:
    """SHA-256 of the data file, or of nothing when the file does not exist."""
    data = store.path.read_bytes() if store.path.exists() else b""
    return hashlib.sha256(data).hexdigest()


def build(store: Store) -> int:
    """Rebuild the index from the database file. Returns the number of records indexed."""
    records: list[Achievement] = store.load()
    fingerprint = _fingerprint(store)
    path = index_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temporary name, so two rebuilds at once cannot clobber each other.
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        with contextlib.closing(sqlite3.connect(tmp)) as db:
            db.execute("CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, body)")
            db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO meta (key, value) VALUES ('source_sha256', ?)", (fingerprint,))
            db.executemany(
                "INSERT INTO docs (id, body) VALUES (?, ?)",
                [(a.id, searchable_text(a)) for a in records],
            )
            db.commit()
        os.replace(tmp, path)
    except sqlite3.OperationalError as error:
        _discard(tmp)
        if "fts5" in str(error):
            raise IndexUnavailable(_FTS5_MISSING) from error
        raise IndexUnavailable(f"cannot build the index: {error}") from error
    except BaseException:
        _discard(tmp)
        raise
    return len(records)


def _discard(path: Path) -> None:
    with contextlib.suppress(OSError):  # best effort: the original error is the one to report
        path.unlink(missing_ok=True)


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def words_of(text: str) -> list[str]:
    words = re.findall(r"\S+", text)
    if not words:
        raise IndexUnavailable("ranked search needs at least one word")
    return words


def query_for(text: str) -> str:
    """An FTS5 query requiring every word of `text`. Each word is quoted, so operators are literal."""
    return " AND ".join(_quote(w) for w in words_of(text))


def literal_words(text: str) -> list[str]:
    """Words the tokenizer cannot keep whole (they contain punctuation); these must also match literally."""
    return [w.lower() for w in words_of(text) if not w.isalnum()]


def ranked_ids(store: Store, text: str) -> list[str]:
    """Record ids that match every word of `text`, best match first."""
    path = index_path(store)
    if not path.exists():
        raise IndexUnavailable(f"no index for {store.db!r}; run `rag index --db {store.db}` first")
    query = query_for(text)
    try:
        with contextlib.closing(sqlite3.connect(path)) as db:
            row = db.execute("SELECT value FROM meta WHERE key = 'source_sha256'").fetchone()
            if row is None or row[0] != _fingerprint(store):
                raise IndexUnavailable(
                    f"the index for {store.db!r} does not match its data; run `rag index --db {store.db}`"
                )
            rows = db.execute(
                "SELECT id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs), id",
                (query,),
            ).fetchall()
    except sqlite3.OperationalError as error:
        if "fts5" in str(error):
            raise IndexUnavailable(_FTS5_MISSING) from error
        raise IndexUnavailable(
            f"the index for {store.db!r} is unreadable ({error}); run `rag index --db {store.db}`"
        ) from error
    except sqlite3.DatabaseError as error:
        raise IndexUnavailable(
            f"the index for {store.db!r} is damaged ({error}); run `rag index --db {store.db}`"
        ) from error
    return [row[0] for row in rows]
