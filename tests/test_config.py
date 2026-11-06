from pathlib import Path

import pytest

from rag.config import ConfigError, data_dir, load_settings, parse_env_file
from rag.schema import REPO


def test_parse_env_file_syntax() -> None:
    text = """
# a comment
export RAG_DB=work
RAG_DATA_DIR = '/tmp/x'
QUOTED="double quoted"
EMPTY=
"""
    assert parse_env_file(text) == {
        "RAG_DB": "work",
        "RAG_DATA_DIR": "/tmp/x",
        "QUOTED": "double quoted",
        "EMPTY": "",
    }


@pytest.mark.parametrize("text", ["no equals sign", "=value"])
def test_parse_env_file_rejects_bad_lines(text: str) -> None:
    with pytest.raises(ConfigError, match="expected KEY=VALUE"):
        parse_env_file(text)


def test_environment_wins_over_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("RAG_DB=from-file\nONLY_FILE=1\n", encoding="utf-8")
    settings = load_settings(str(env), environ={"RAG_DB": "from-env"})
    assert settings["RAG_DB"] == "from-env"
    assert settings["ONLY_FILE"] == "1"


def test_default_dotenv_in_cwd_is_optional(tmp_path: Path) -> None:
    assert load_settings(None, environ={}, cwd=tmp_path) == {}
    (tmp_path / ".env").write_text("RAG_DB=here\n", encoding="utf-8")
    assert load_settings(None, environ={}, cwd=tmp_path) == {"RAG_DB": "here"}


def test_explicit_missing_env_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(str(tmp_path / "nope.env"), environ={})


def test_data_dir_defaults_and_resolves_relative_paths(tmp_path: Path) -> None:
    assert data_dir({}) == REPO / "data"
    assert data_dir({"RAG_DATA_DIR": "  "}) == REPO / "data"
    assert data_dir({"RAG_DATA_DIR": "mine"}) == REPO / "mine"
    assert data_dir({"RAG_DATA_DIR": str(tmp_path)}) == tmp_path
    assert data_dir({"RAG_DATA_DIR": "~/rag-data"}) == Path.home() / "rag-data"
