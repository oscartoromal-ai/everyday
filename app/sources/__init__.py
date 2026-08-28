"""Work-calendar sources.

The app talks to a small interface so the ICS feed can be swapped for Graph
delegated auth later without touching anything else (SPEC.md section 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ExternalEvent:
    """A work-calendar occurrence, already expanded and in local wall time.

    Only subject, times, and location are carried; bodies and attendees never
    enter the personal database.
    """

    external_id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str


class WorkCalendarSource(Protocol):
    def fetch(self, window_start: datetime, window_end: datetime) -> list[ExternalEvent]:
        """Return every occurrence in the window."""
        ...
