"""Event domain logic and the unified calendar range query."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Block, Event, EventSource
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


def calendar_range(
    db: Session, start: datetime, end: datetime
) -> tuple[list[Event], list[Block]]:
    """Everything the calendar grid renders for [start, end): events of both
    sources plus task blocks, one query path per the spec."""
    events = list(
        db.scalars(
            select(Event)
            .where(Event.start < end, Event.end > start)
            .order_by(Event.start)
        )
    )
    blocks = list(
        db.scalars(
            select(Block)
            .options(selectinload(Block.task))
            .where(Block.start < end, Block.end > start)
            .order_by(Block.start)
        )
    )
    return events, blocks
