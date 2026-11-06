"""Phase 3: interactive browsing with fzf. A thin wrapper; the list rows and the preview come from the CLI."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

Runner = Callable[..., Any]


class FzfNotInstalled(RuntimeError):
    pass


class FzfFailed(RuntimeError):
    pass


def fzf_command(preview: str) -> list[str]:
    """fzf arguments: rows are '<id><TAB><text>', the id is hidden, the preview shows the record."""
    return [
        "fzf",
        "--delimiter=\t",
        "--with-nth=2..",
        "--no-sort",
        "--reverse",
        "--prompt",
        "rag> ",
        "--preview",
        preview,
        "--preview-window=up:40%:wrap",
    ]


def browse(
    rows: Sequence[str],
    preview: str,
    *,
    which: Callable[[str], str | None] | None = None,
    runner: Runner | None = None,
) -> str | None:
    """Show `rows` in fzf. Returns the id of the chosen row, or None if nothing was chosen."""
    # Looked up at call time, so tests and callers can replace shutil.which or subprocess.run.
    which = which or shutil.which
    runner = runner or subprocess.run
    if which("fzf") is None:
        raise FzfNotInstalled("fzf is not installed; install it or use `rag select --format line`")
    proc = runner(
        fzf_command(preview),
        input="\n".join(rows),
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    # 0: a row was chosen. 1: no match. 130: Esc. Anything else is fzf failing, not the user cancelling.
    if proc.returncode not in (0, 1, 130):
        raise FzfFailed(f"fzf exited with status {proc.returncode}")
    chosen = proc.stdout.strip()
    if not chosen:
        return None
    return chosen.split("\t", 1)[0]
