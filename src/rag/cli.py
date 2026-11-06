"""Command-line interface: `python -m rag <command>`. Parses arguments and wires the modules together."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import SchemaError

from . import backends, browse, index, printers
from .commits import GROUPS, Commit, contributions, load_commits, mine, project_of, tasks
from .config import DEFAULT_DB, ConfigError, data_dir, load_settings
from .dates import DateSpecError, parse_date_spec
from .gitctx import capture_source
from .intake import RecordRejected, save_record
from .model import Achievement, normalize_slug, normalize_topics, parse_free, searchable_text, unslugged
from .query import Filter, select
from .schema import SCHEMA_PATH, validate_file
from .store import Store

EXIT_OK = 0
EXIT_NO_MATCH = 1
EXIT_INVALID = 2

Span = tuple[date | None, date]


@dataclass
class Context:
    settings: dict[str, str]
    data_dir: Path
    today: date | None = None  # None: the real date


class _Invalid(Exception):
    """Invalid input: the command exits with EXIT_INVALID and the message on stderr."""


# --- helpers ---------------------------------------------------------------------------

def _store(args: argparse.Namespace, ctx: Context) -> Store:
    db = getattr(args, "db", None) or ctx.settings.get("RAG_DB") or DEFAULT_DB
    return Store(ctx.data_dir, db)


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _error(message: str) -> int:
    print(f"rag: {message}", file=sys.stderr)
    return EXIT_INVALID


def _rejected(messages: list[str]) -> int:
    print("rejected, nothing written:", file=sys.stderr)
    for message in messages:
        print(f"  - {message}", file=sys.stderr)
    return EXIT_INVALID


def _check_values(topics: list[str], project: str | None, category: str | None) -> None:
    """Raise if a given value has no ASCII letters or digits (normalisation would erase it)."""
    values = [*topics, *([project] if project else []), *([category] if category else [])]
    bad = unslugged(values)
    if bad:
        raise _Invalid(
            f"no ASCII letters or digits in {', '.join(repr(v) for v in bad)}; "
            "use topics, projects and categories with a-z or 0-9"
        )


def _span(spec: str | None, ctx: Context) -> Span | None:
    """The inclusive range for a date spec, or None when no spec was given."""
    if not spec:
        return None
    try:
        return parse_date_spec(spec, ctx.today)
    except DateSpecError as error:
        raise _Invalid(str(error)) from error


def _in_span(day: date | None, span: Span | None) -> bool:
    if span is None:
        return True
    if day is None:
        return False
    start, end = span
    return (start is None or day >= start) and day <= end


def _day(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _emit_rows(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return EXIT_NO_MATCH
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return EXIT_OK


def _guarded(handler: Callable[[argparse.Namespace, Context], int]) -> Callable[[argparse.Namespace, Context], int]:
    def wrapped(args: argparse.Namespace, ctx: Context) -> int:
        try:
            return handler(args, ctx)
        except _Invalid as error:
            return _error(str(error))

    wrapped.__name__ = handler.__name__
    return wrapped


# --- achievements ----------------------------------------------------------------------

@_guarded
def cmd_add(args: argparse.Namespace, ctx: Context) -> int:
    try:
        free = parse_free(args.free)
    except ValueError as error:
        raise _Invalid(str(error)) from error
    topics = _split(args.topic)
    _check_values(topics, args.project, args.category)
    source = None if args.no_source else capture_source(Path.cwd(), args.path)
    achievement = Achievement.create(
        " ".join(args.idea.split()),
        topics=topics,
        project=args.project,
        category=args.category,
        free=free,
        source=source,
    )
    try:
        save_record(_store(args, ctx), achievement.to_dict())
    except RecordRejected as error:
        return _rejected(error.messages)
    print(f"id: {achievement.id}")
    return EXIT_OK


def _filter_from(args: argparse.Namespace, ctx: Context) -> Filter:
    topics = _split(args.topic)
    _check_values(topics, args.project, args.category)
    span = _span(args.date, ctx)
    return Filter(
        start=span[0] if span else None,
        end=span[1] if span else None,
        topics=tuple(normalize_topics(topics)),
        any_topic=args.any_topic,
        project=normalize_slug(args.project) if args.project else None,
        category=normalize_slug(args.category) if args.category else None,
        any_values=tuple(args.any),
        text=args.text,
    )


@_guarded
def cmd_select(args: argparse.Namespace, ctx: Context) -> int:
    fields = _split(args.fields) if args.fields else None
    if fields:
        unknown = printers.check_fields(fields)
        if unknown:
            raise _Invalid(f"unknown field(s): {', '.join(unknown)}")
    wanted = _filter_from(args, ctx)
    store = _store(args, ctx)
    if args.ranked:
        if not args.text:
            raise _Invalid("--ranked needs --text")
        try:
            rank_of = {ident: n for n, ident in enumerate(index.ranked_ids(store, args.text))}
            punctuated = index.literal_words(args.text)
        except index.IndexUnavailable as error:
            raise _Invalid(str(error)) from error
        candidates = select(store.load(), replace(wanted, text=None))
        found = sorted(
            (a for a in candidates
             if a.id in rank_of and all(w in searchable_text(a).lower() for w in punctuated)),
            key=lambda a: rank_of[a.id],
        )
    else:
        found = select(store.load(), wanted)
    if not found:
        return EXIT_NO_MATCH
    for achievement in found:
        if args.format == "line":
            print(printers.line(achievement))
        else:
            print(printers.jsonl(achievement, fields))
    return EXIT_OK


@_guarded
def cmd_browse(args: argparse.Namespace, ctx: Context) -> int:
    store = _store(args, ctx)
    found = select(store.load(), _filter_from(args, ctx))
    if not found:
        return EXIT_NO_MATCH
    preview = [shlex.quote(sys.executable), "-m", "rag"]
    if args.env:
        preview += ["--env", shlex.quote(args.env)]
    preview += ["view", "--db", shlex.quote(store.db), "{1}"]
    try:
        chosen = browse.browse([printers.line(a) for a in found], " ".join(preview))
    except (browse.FzfNotInstalled, browse.FzfFailed) as error:
        raise _Invalid(str(error)) from error
    if chosen is None:
        return EXIT_NO_MATCH
    print(chosen)
    return EXIT_OK


def cmd_view(args: argparse.Namespace, ctx: Context) -> int:
    try:
        achievement = _store(args, ctx).get(args.id)
    except LookupError as error:
        return _error(str(error))
    print(printers.detail(achievement))
    return EXIT_OK


def cmd_index(args: argparse.Namespace, ctx: Context) -> int:
    store = _store(args, ctx)
    try:
        count = index.build(store)
    except index.IndexUnavailable as error:
        return _error(str(error))
    print(f"indexed {count} record(s) into {index.index_path(store)}")
    return EXIT_OK


def cmd_validate(args: argparse.Namespace, ctx: Context) -> int:
    path = Path(args.file)
    if not path.is_file():
        return _error(f"no such file: {path}")
    try:
        checked, problems = validate_file(path, Path(args.schema))
    except SchemaError as error:
        return _error(f"schema {args.schema} is not a valid JSON Schema: {error.message}")
    except json.JSONDecodeError as error:
        return _error(f"schema {args.schema} is not valid JSON: {error}")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"invalid: {len(problems)} problem(s) in {path}", file=sys.stderr)
        return EXIT_INVALID
    print(f"valid: {checked} record(s) in {path} match {args.schema}")
    return EXIT_OK


def cmd_retry(args: argparse.Namespace, ctx: Context) -> int:
    """Insert a record from a JSON file once it validates; the file is removed on success."""
    path = Path(args.file)
    if not path.is_file():
        return _error(f"no such file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return _rejected([f"not valid JSON: {error}"])
    if not isinstance(data, dict):
        return _rejected(["expected one JSON object for the record"])
    try:
        achievement = save_record(_store(args, ctx), data)
    except RecordRejected as error:
        return _rejected(error.messages)
    path.unlink()
    print(f"id: {achievement.id}")
    return EXIT_OK


# --- git activity ----------------------------------------------------------------------

def _my_commits(args: argparse.Namespace, ctx: Context) -> tuple[list[Commit], Span | None]:
    """Commits by me (--author, else AUTHOR_REGEX) within --since."""
    pattern = args.author if args.author is not None else ctx.settings.get("AUTHOR_REGEX", "")
    if not pattern:
        raise _Invalid("no author pattern: set AUTHOR_REGEX in .env or pass --author")
    try:
        re.compile(pattern)
    except re.error as error:
        raise _Invalid(f"invalid author pattern {pattern!r}: {error}") from error
    span = _span(args.since, ctx)
    commits = [c for c in mine(load_commits(ctx.data_dir / "commits"), pattern) if _in_span(c.day, span)]
    return commits, span


@_guarded
def cmd_contributions(args: argparse.Namespace, ctx: Context) -> int:
    commits, _ = _my_commits(args, ctx)  # --group-by is limited to GROUPS by argparse
    return _emit_rows(contributions(commits, args.group_by))


@_guarded
def cmd_tasks(args: argparse.Namespace, ctx: Context) -> int:
    commits, span = _my_commits(args, ctx)
    try:
        reviews = backends.load_reviews(ctx.data_dir / "reviews")
    except backends.FetchError as error:
        raise _Invalid(str(error)) from error
    from_reviews = [r for r in reviews if _in_span(_day(r.get("date")), span)]
    known = {r["url"] for r in from_reviews}
    local = [r for r in tasks(commits) if r["url"] is None or r["url"] not in known]
    rows = sorted([*from_reviews, *local], key=lambda r: r.get("date") or "", reverse=True)
    if args.project:
        wanted = args.project.strip().lower()
        rows = [r for r in rows if project_of(str(r.get("repo") or "")).lower() == wanted]
    return _emit_rows(rows)


@_guarded
def cmd_fetch(args: argparse.Namespace, ctx: Context) -> int:
    settings = ctx.settings
    try:
        if args.host == "gitlab":
            rows = backends.fetch_gitlab(
                backends.http_get_json,
                settings.get("GITLAB_URL") or "https://gitlab.com",
                settings.get("GITLAB_TOKEN") or None,
            )
        else:
            rows = backends.fetch_github(
                backends.http_get_json,
                settings.get("GITHUB_API_URL") or "https://api.github.com",
                settings.get("GITHUB_TOKEN") or None,
            )
    except backends.FetchError as error:
        raise _Invalid(str(error)) from error
    try:
        path = backends.write_reviews(ctx.data_dir / "reviews", args.host, rows)
    except backends.FetchError as error:
        raise _Invalid(str(error)) from error
    print(f"fetched {len(rows)} item(s) into {path}")
    return EXIT_OK


# --- parser ----------------------------------------------------------------------------

_OPTIONS_TAKING_SPECS = ("--date", "--since")


def join_negative_specs(argv: list[str]) -> list[str]:
    """Turn `--date -1m..` into `--date=-1m..`. argparse would read the value as an option otherwise."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if token in _OPTIONS_TAKING_SPECS and nxt is not None and nxt.startswith("-") and not nxt.startswith("--"):
            out.append(f"{token}={nxt}")
            i += 2
            continue
        out.append(token)
        i += 1
    return out


def _add_filters(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=None)
    p.add_argument("--date", default=None, metavar="SPEC", help="date spec, e.g. --date -1m.. or --date=2026-10..2026-11-15")
    p.add_argument("--topic", default="", help="comma-separated topics; all must match")
    p.add_argument("--any-topic", action="store_true", help="match at least one topic instead of all")
    p.add_argument("--project", default=None)
    p.add_argument("--category", default=None)
    p.add_argument(
        "--any", action="append", default=[], metavar="VALUE",
        help="a free value equal to VALUE; repeatable, every one must match",
    )
    p.add_argument("--text", default=None, help="case-insensitive substring search")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag", description="Retrieve and record achievements.")
    parser.add_argument(
        "--env",
        metavar="FILE",
        default=None,
        help="read settings from FILE; default is .env in the current directory, if it exists",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="record an achievement")
    add.add_argument("idea", help="one sentence: what was achieved")
    add.add_argument("--db", default=None, help="database name (data/<db>.jsonl)")
    add.add_argument("--topic", default="", help="comma-separated topics (tags)")
    add.add_argument("--project", default=None)
    add.add_argument("--category", default=None)
    add.add_argument("--free", action="append", default=[], metavar="KEY=VALUE", help="repeatable")
    add.add_argument("--path", default=None, help="path inside the repository that holds the work")
    add.add_argument("--no-source", action="store_true", help="do not record the git remote/branch/commit")
    add.set_defaults(handler=cmd_add)

    select_p = sub.add_parser("select", help="print matching achievements as JSON Lines")
    _add_filters(select_p)
    select_p.add_argument("--ranked", action="store_true", help="order --text matches by relevance (needs rag index)")
    select_p.add_argument("--format", choices=["jsonl", "line"], default="jsonl")
    select_p.add_argument("--fields", default=None, help="comma-separated fields to print (JSON output)")
    select_p.set_defaults(handler=cmd_select)

    browse_p = sub.add_parser("browse", help="browse matching achievements with fzf")
    _add_filters(browse_p)
    browse_p.set_defaults(handler=cmd_browse)

    view = sub.add_parser("view", help="show one achievement by id or unique id prefix")
    view.add_argument("id")
    view.add_argument("--db", default=None)
    view.set_defaults(handler=cmd_view)

    index_p = sub.add_parser("index", help="build the ranked full-text index for a database")
    index_p.add_argument("--db", default=None)
    index_p.set_defaults(handler=cmd_index)

    validate = sub.add_parser("validate", help="validate a JSON Lines file against the schema")
    validate.add_argument("file")
    validate.add_argument("--schema", default=str(SCHEMA_PATH))
    validate.set_defaults(handler=cmd_validate)

    retry = sub.add_parser("retry", help="insert a record from a JSON file once it validates")
    retry.add_argument("file")
    retry.add_argument("--db", default=None)
    retry.set_defaults(handler=cmd_retry)

    for name, handler, text in (
        ("contributions", cmd_contributions, "summarise commits and merges by project, repo or month"),
        ("tasks", cmd_tasks, "list merged MRs/PRs and fetched issues as JSON Lines"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--author", default=None, help="regular expression over 'Name <email>' (default AUTHOR_REGEX)")
        p.add_argument("--since", default=None, metavar="SPEC", help="date spec, e.g. --since -1m..")
        if name == "contributions":
            p.add_argument("--group-by", choices=list(GROUPS), default="project")
        else:
            p.add_argument("--project", default=None, help="only this project (the repository's last path segment)")
        p.set_defaults(handler=handler)

    fetch = sub.add_parser("fetch", help="fetch merged MRs/PRs and assigned issues from GitLab or GitHub")
    fetch.add_argument("host", choices=["gitlab", "github"])
    fetch.set_defaults(handler=cmd_fetch)

    return parser


def main(argv: list[str] | None = None, today: date | None = None) -> int:
    raw = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(join_negative_specs(raw))
    try:
        settings = load_settings(args.env)
    except ConfigError as error:
        return _error(str(error))
    ctx = Context(settings=settings, data_dir=data_dir(settings), today=today)
    handler: Callable[[argparse.Namespace, Context], int] = args.handler
    try:
        return int(handler(args, ctx))
    except ValueError as error:  # invalid database name, corrupt database or commit data
        return _error(str(error))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
