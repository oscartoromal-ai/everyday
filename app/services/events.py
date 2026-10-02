"""Event domain logic, the calendar range query, and the time events take."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, EventSource
from app.services import DomainError


def create_event(
    db: Session,
    *,
    title: str,
    start: datetime,
    end: datetime,
    all_day: bool = False,
    location: str = "",
) -> Event:
    if not title.strip():
        raise DomainError("Event title must not be empty")
    if end <= start:
        raise DomainError("An event must end after it starts")
    event = Event(
        title=title.strip(),
        start=start,
        end=end,
        all_day=all_day,
        location=location,
        source=EventSource.local,
    )
    db.add(event)
    db.flush()
    return event


def update_event(
    db: Session,
    event_id: int,
    *,
    title: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    all_day: bool | None = None,
    location: str | None = None,
) -> Event:
    event = get_event(db, event_id)
    if event.read_only:
        raise DomainError("Work-calendar events are read-only")
    if title is not None:
        if not title.strip():
            raise DomainError("Event title must not be empty")
        event.title = title.strip()
    if start is not None:
        event.start = start
    if end is not None:
        event.end = end
    if event.end <= event.start:
        raise DomainError("An event must end after it starts")
    if all_day is not None:
        event.all_day = all_day
    if location is not None:
        event.location = location
    db.flush()
    return event


def delete_event(db: Session, event_id: int) -> None:
    event = get_event(db, event_id)
    if event.read_only:
        raise DomainError("Work-calendar events are read-only")
    db.delete(event)
    db.flush()


def get_event(db: Session, event_id: int) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise DomainError(f"Event {event_id} does not exist")
    return event


def calendar_range(db: Session, start: datetime, end: datetime) -> list[Event]:
    """Every event the calendar shows in [start, end), of both sources."""
    return list(
        db.scalars(
            select(Event)
            .where(Event.start < end, Event.end > start)
            .order_by(Event.start)
        )
    )


def busy_spans(db: Session, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """The time taken between `start` and `end`, as sorted spans that never
    overlap: timed events, clipped to the window. All-day events and
    cancelled meetings take none."""
    spans = sorted(
        (e.start, e.end)
        for e in calendar_range(db, start, end)
        if not e.all_day and not e.cancelled
    )
    merged: list[tuple[datetime, datetime]] = []
    for s, e in spans:
        s, e = max(s, start), min(e, end)
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged
