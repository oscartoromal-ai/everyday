"""The published-ICS work-calendar source: anonymous GET plus icalendar parsing."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import httpx
import recurring_ical_events
from icalendar import Calendar

from app.sources import ExternalEvent


def _to_local_naive(value: datetime | date) -> tuple[datetime, bool]:
    """(naive local datetime, is_all_day). Date-only values mean all-day."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value, False
    return datetime.combine(value, time.min), True


class IcsWorkCalendarSource:
    def __init__(self, url: str, *, timeout: float = 30.0) -> None:
        self._url = url
        self._timeout = timeout

    def _download(self) -> bytes:
        response = httpx.get(self._url, timeout=self._timeout, follow_redirects=True)
        response.raise_for_status()
        return response.content

    def fetch(self, window_start: datetime, window_end: datetime) -> list[ExternalEvent]:
        calendar = Calendar.from_ical(self._download())
        occurrences = recurring_ical_events.of(calendar).between(window_start, window_end)
        out: list[ExternalEvent] = []
        for occ in occurrences:
            uid = str(occ.get("UID", ""))
            summary = str(occ.get("SUMMARY", "")) or "(no title)"
            location = str(occ.get("LOCATION", "") or "")
            start_raw = occ["DTSTART"].dt
            start, all_day = _to_local_naive(start_raw)
            if "DTEND" in occ:
                end, _ = _to_local_naive(occ["DTEND"].dt)
            elif all_day:
                end = start + timedelta(days=1)
            else:
                end = start + timedelta(minutes=30)
            external_id = f"{uid}:{start.isoformat()}"
            out.append(
                ExternalEvent(
                    external_id=external_id,
                    title=summary,
                    start=start,
                    end=end,
                    all_day=all_day,
                    location=location,
                )
            )
        return out
