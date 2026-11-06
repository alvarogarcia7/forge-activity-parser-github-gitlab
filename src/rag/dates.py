"""Parse date specs into an inclusive (start, end) range. `start` None means "from the beginning".

Keywords (relative to today):
  y      yesterday
  w      Monday of this week through today
  m      first day of this month through today
  -Nd    today minus N days, through today
  -Nm    today minus N months, through today
  -Ny    today minus N years, through today

Absolute dates (a partial date covers the whole period it names):
  2026-11-03   that day        2026-11   the whole month
  2026         the whole year  11-03     that day in the current year

Ranges A..B: from the start of A through the end of B. Either side may be empty
(open-ended): `-1m..` is one month ago through today, `..2026-10` is everything up to
the end of October. A leading ":" is optional.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_DAYS = re.compile(r"^-(\d+)d$")
_MONTHS = re.compile(r"^-(\d+)m$")
_YEARS = re.compile(r"^-(\d+)y$")
_FULL = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")
_YEAR = re.compile(r"^(\d{4})$")
_MONTH_DAY = re.compile(r"^(\d{1,2})-(\d{1,2})$")


class DateSpecError(ValueError):
    pass


def shift_months(day: date, months: int) -> date:
    """Move `day` back by `months` calendar months, clamping the day to the month's length."""
    total = day.year * 12 + (day.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def parse_date_spec(spec: str, today: date | None = None) -> tuple[date | None, date]:
    """Return (start, end) for a date spec. start is None when the range is open at the beginning."""
    today = today or date.today()
    text = spec.strip().lower().removeprefix(":")
    if not text:
        raise DateSpecError("empty date spec")

    if ".." in text:
        left, right = (part.strip() for part in text.split("..", 1))
        if not left and not right:
            raise DateSpecError("a range needs at least one side: A..B, A.., or ..B")
        start = _range_edge(left, today, first=True) if left else None
        end = _range_edge(right, today, first=False) if right else today
        if start is not None and start > end:
            raise DateSpecError(f"range {spec!r} starts after it ends")
        return start, end

    return _bounds(text, today)


def _range_edge(text: str, today: date, first: bool) -> date:
    """One side of a range. A relative date names a single day on either side: -1d is that day."""
    relative = _relative(text, today)
    if relative is not None:
        return relative
    start, end = _bounds(text, today)
    return start if first else end


def _bounds(text: str, today: date) -> tuple[date, date]:
    keyword = _keyword(text, today)
    if keyword is not None:
        return keyword
    relative = _relative(text, today)
    if relative is not None:
        return relative, today
    return _absolute(text, today)


def _keyword(text: str, today: date) -> tuple[date, date] | None:
    if text == "y":
        day = today - timedelta(days=1)
        return day, day
    if text == "w":
        return today - timedelta(days=today.weekday()), today
    if text == "m":
        return today.replace(day=1), today
    return None


def _relative(text: str, today: date) -> date | None:
    if match := _DAYS.match(text):
        return today - timedelta(days=int(match.group(1)))
    if match := _MONTHS.match(text):
        return shift_months(today, int(match.group(1)))
    if match := _YEARS.match(text):
        return shift_months(today, 12 * int(match.group(1)))
    return None


def _absolute(text: str, today: date) -> tuple[date, date]:
    try:
        if match := _FULL.match(text):
            day = date(*map(int, match.groups()))
            return day, day
        if match := _MONTH.match(text):
            year, month = map(int, match.groups())
            last = calendar.monthrange(year, month)[1]
            return date(year, month, 1), date(year, month, last)
        if match := _YEAR.match(text):
            year = int(match.group(1))
            return date(year, 1, 1), date(year, 12, 31)
        if match := _MONTH_DAY.match(text):
            month, day_of_month = map(int, match.groups())
            value = date(today.year, month, day_of_month)
            return value, value
    except ValueError as error:  # e.g. month 13 or February 30
        raise DateSpecError(f"invalid date {text!r}: {error}") from None

    raise DateSpecError(
        f"unknown date spec {text!r}; use y, w, m, -Nd, -Nm, -Ny, YYYY-MM-DD, YYYY-MM, "
        "YYYY, MM-DD, or A..B"
    )
