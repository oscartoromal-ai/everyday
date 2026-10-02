from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from app.api.schemas import CalendarOut, EventIn, EventOut, EventPatch
from app.db import DbSession
from app.services import events as events_svc

router = APIRouter(prefix="/api", tags=["calendar"])


@router.get("/calendar")
def calendar(start: datetime, end: datetime, db: DbSession) -> CalendarOut:
    """The calendar's events in [start, end), of both sources."""
    events = events_svc.calendar_range(db, start, end)
    return CalendarOut(events=[EventOut.model_validate(e) for e in events])


@router.post("/events", status_code=201)
def create_event(body: EventIn, db: DbSession) -> EventOut:
    return EventOut.model_validate(events_svc.create_event(db, **body.model_dump()))


@router.patch("/events/{event_id}")
def update_event(event_id: int, body: EventPatch, db: DbSession) -> EventOut:
    return EventOut.model_validate(
        events_svc.update_event(db, event_id, **body.model_dump(exclude_unset=True))
    )


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: DbSession) -> None:
    events_svc.delete_event(db, event_id)
