"""Settings from a .env file and the process environment. Environment variables win.

Same format as the collector's .env: KEY=VALUE per line, comments on their own line,
optional `export`, optional quotes. The file is parsed, never executed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .schema import REPO

DEFAULT_ENV_FILE = ".env"
DEFAULT_DB = "achievements"


class ConfigError(RuntimeError):
    pass


def parse_env_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            raise ConfigError(f"env file line {number}: expected KEY=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def load_settings(
    env_file: str | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, str]:
    """Merge the env file with the process environment (environment wins).

    An explicitly named `env_file` must exist; the default `.env` in `cwd` is optional.
    """
    environ = os.environ if environ is None else environ
    settings: dict[str, str] = {}
    if env_file is None:
        path = (Path.cwd() if cwd is None else cwd) / DEFAULT_ENV_FILE
        if path.is_file():
            settings = parse_env_file(path.read_text(encoding="utf-8"))
    else:
        path = Path(env_file)
        if not path.is_file():
            raise ConfigError(f"env file not found: {env_file}")
        settings = parse_env_file(path.read_text(encoding="utf-8"))
    return {**settings, **environ}


def data_dir(settings: Mapping[str, str]) -> Path:
    """RAG_DATA_DIR, or <repo>/data. Relative values are taken from the repository root."""
    value = settings.get("RAG_DATA_DIR", "").strip()
    if not value:
        return REPO / "data"
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO / path
