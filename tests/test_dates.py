from datetime import date, timedelta

import pytest

from rag.dates import DateSpecError, parse_date_spec, shift_months

TODAY = date(2026, 11, 6)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("y", (date(2026, 11, 5), date(2026, 11, 5))),
        ("m", (date(2026, 11, 1), TODAY)),
        ("-30d", (date(2026, 10, 7), TODAY)),
        ("-1m", (date(2026, 10, 6), TODAY)),
        ("-3m", (date(2026, 8, 6), TODAY)),
        ("-1y", (date(2025, 11, 6), TODAY)),
        ("-1m..", (date(2026, 10, 6), TODAY)),
        ("..2026-10", (None, date(2026, 10, 31))),
        ("2026-10..2026-11-15", (date(2026, 10, 1), date(2026, 11, 15))),
        ("2026-11-03", (date(2026, 11, 3), date(2026, 11, 3))),
        ("2026-11", (date(2026, 11, 1), date(2026, 11, 30))),
        ("2026", (date(2026, 1, 1), date(2026, 12, 31))),
        ("11-03", (date(2026, 11, 3), date(2026, 11, 3))),
        (":y", (date(2026, 11, 5), date(2026, 11, 5))),
        (" -30D ", (date(2026, 10, 7), TODAY)),
        ("2026-10-01..", (date(2026, 10, 1), TODAY)),
        ("..-1d", (None, date(2026, 11, 5))),
    ],
)
def test_valid_specs(spec: str, expected: tuple[date | None, date]) -> None:
    assert parse_date_spec(spec, today=TODAY) == expected


def test_week_keyword_starts_on_monday() -> None:
    start, end = parse_date_spec("w", today=TODAY)
    assert start == TODAY - timedelta(days=TODAY.weekday())
    assert start.weekday() == 0
    assert end == TODAY


def test_default_today_is_the_real_date() -> None:
    start, end = parse_date_spec("y")
    assert start == end == date.today() - timedelta(days=1)


@pytest.mark.parametrize(
    "spec",
    ["", ":", "..", "2026-13-01", "2026-02-30", "garbage", "2026-11-10..2026-11-01", "2026-13"],
)
def test_invalid_specs(spec: str) -> None:
    with pytest.raises(DateSpecError):
        parse_date_spec(spec, today=TODAY)


def test_shift_months_clamps_to_month_length() -> None:
    assert shift_months(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert shift_months(date(2024, 3, 31), 1) == date(2024, 2, 29)


def test_shift_months_crosses_year_boundary() -> None:
    assert shift_months(date(2026, 1, 15), 1) == date(2025, 12, 15)
    assert shift_months(date(2026, 1, 15), 0) == date(2026, 1, 15)
