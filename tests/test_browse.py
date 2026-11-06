"""Phase 3: fzf browsing. fzf itself is replaced by fakes; the wiring and the preview are tested."""

import pytest

from helpers import rec
from rag import browse as browse_module
from rag.browse import FzfNotInstalled, browse, fzf_command
from rag.cli import EXIT_NO_MATCH, EXIT_OK
from rag.store import Store


class Done:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def test_fzf_command_hides_ids_and_previews_the_record() -> None:
    cmd = fzf_command("preview {1}")
    assert cmd[0] == "fzf"
    assert "--with-nth=2.." in cmd and "--delimiter=\t" in cmd
    assert cmd[cmd.index("--preview") + 1] == "preview {1}"


def test_browse_returns_the_chosen_id() -> None:
    seen = {}

    def runner(cmd, **kwargs):
        seen["input"] = kwargs["input"]
        return Done("abc123\tthe row text\n")

    chosen = browse(["abc123\tthe row text", "def\tother"], "preview", which=lambda _: "/bin/fzf", runner=runner)
    assert chosen == "abc123"
    assert seen["input"] == "abc123\tthe row text\ndef\tother"


def test_browse_with_no_selection_returns_none() -> None:
    assert browse(["a\tb"], "p", which=lambda _: "/bin/fzf", runner=lambda c, **k: Done("")) is None


def test_browse_without_fzf_is_a_clear_error() -> None:
    with pytest.raises(FzfNotInstalled, match="fzf is not installed"):
        browse(["a\tb"], "p", which=lambda _: None, runner=lambda c, **k: Done(""))


def test_cli_browse_passes_rows_and_a_preview_for_the_chosen_database(run, data_dir, monkeypatch) -> None:
    Store(data_dir, "work").append(rec("browse me", topics=["x"], ident="7" * 32))
    captured = {}

    def fake(rows, preview, **kwargs):
        captured["rows"] = rows
        captured["preview"] = preview
        return "7" * 32

    monkeypatch.setattr(browse_module, "browse", fake)
    code, out, _ = run("browse", "--db", "work", "--topic", "x")
    assert code == EXIT_OK and out.strip() == "7" * 32
    assert captured["rows"][0].startswith("7" * 32 + "\t")
    assert "-m rag view --db work {1}" in captured["preview"]


def test_cli_browse_preview_keeps_the_env_file(run, data_dir, monkeypatch, tmp_path) -> None:
    Store(data_dir, "achievements").append(rec("x", ident="8" * 32))
    captured = {}
    monkeypatch.setattr(browse_module, "browse", lambda rows, preview, **k: captured.setdefault("p", preview))
    env = tmp_path / "s.env"
    env.write_text("RAG_DB=achievements\n", encoding="utf-8")
    run("--env", str(env), "browse")
    assert "--env" in captured["p"] and str(env) in captured["p"]


def test_cli_browse_no_match_and_no_selection(run, data_dir, monkeypatch) -> None:
    assert run("browse")[0] == EXIT_NO_MATCH
    Store(data_dir, "achievements").append(rec("x", ident="9" * 32))
    monkeypatch.setattr(browse_module, "browse", lambda rows, preview, **k: None)
    assert run("browse")[0] == EXIT_NO_MATCH


def test_cli_browse_without_fzf_exits_with_error(run, data_dir, monkeypatch) -> None:
    Store(data_dir, "achievements").append(rec("x", ident="a" * 32))
    monkeypatch.setattr(browse_module.shutil, "which", lambda _: None)
    code, _, err = run("browse")
    assert code == 2 and "fzf is not installed" in err


def test_fzf_failure_is_not_mistaken_for_cancel() -> None:
    with pytest.raises(browse_module.FzfFailed, match="status 2"):
        browse(["a\tb"], "p", which=lambda _: "/bin/fzf", runner=lambda c, **k: Done("", returncode=2))


def test_newlines_and_tabs_in_values_cannot_split_a_row() -> None:
    from rag.printers import line

    a = rec("two\nlines\there", free={"k": "line1\nline2\tx"}, ident="e" * 32)
    rows = line(a).splitlines()
    assert len(rows) == 1
    assert rows[0].split("\t")[0] == "e" * 32
    assert "line2" in rows[0] and "\t" not in rows[0].split("\t", 1)[1]
