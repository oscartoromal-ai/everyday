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
