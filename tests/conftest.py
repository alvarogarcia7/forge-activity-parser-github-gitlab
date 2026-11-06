from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from rag.cli import main


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated data directory. The working directory is a temp dir with no .env."""
    directory = tmp_path / "data"
    monkeypatch.setenv("RAG_DATA_DIR", str(directory))
    monkeypatch.delenv("RAG_DB", raising=False)
    monkeypatch.delenv("AUTHOR_REGEX", raising=False)
    monkeypatch.chdir(tmp_path)
    return directory


@pytest.fixture
def run(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> Callable[..., tuple[int, str, str]]:
    """Run the CLI in-process. Returns (exit code, stdout, stderr)."""

    def _run(*argv: str, today: date | None = None) -> tuple[int, str, str]:
        code = main(list(argv), today=today)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run
