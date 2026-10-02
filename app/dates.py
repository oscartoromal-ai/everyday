"""Human date formatting shared by the UI, nudges, and the digest."""

from __future__ import annotations

from datetime import date, timedelta


def human_date(value: date) -> str:
    """'Friday 28 August' without platform-specific strftime flags."""
    return f"{value.strftime('%A')} {value.day} {value.strftime('%B')}"


def short_date(value: date, today: date | None = None) -> str:
    """'today', 'tomorrow', 'Tue 2 Sep' relative to today."""
    today = today or date.today()
    if value == today:
        return "today"
    if value == today + timedelta(days=1):
        return "tomorrow"
    if value == today - timedelta(days=1):
        return "yesterday"
    return f"{value.strftime('%a')} {value.day} {value.strftime('%b')}"


def upper_first(text: str) -> str:
    """The first letter in capitals and the rest as it was ("Mon 5 Oct"),
    where str.capitalize would lower the month ("Mon 5 oct")."""
    return text[:1].upper() + text[1:]


def duration_label(minutes: int) -> str:
    """A length of time as it is written: '45m', '1h', '1h 30m'."""
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest}m"
    return f"{hours}h {rest}m" if rest else f"{hours}h"


def monday(value: date) -> date:
    """The Monday of the week `value` falls in: weeks run Monday to Sunday."""
    return value - timedelta(days=value.weekday())


def week_label(value: date, today: date | None = None) -> str:
    """The ISO week `value` falls in: 'W40', or "W2 '27" outside this year's."""
    today = today or date.today()
    year, week, _ = value.isocalendar()
    return f"W{week}" if year == today.isocalendar()[0] else f"W{week} '{year % 100:02d}"
