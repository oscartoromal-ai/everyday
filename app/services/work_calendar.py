"""Sync the work calendar into the unified Event table.

Rows are upserted by (source=work, external_id); occurrences that vanish from
the feed inside the sync window are deleted (cancelled meetings). Removing the
integration entirely is delete-by-source.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, EventSource
from app.sources import WorkCalendarSource

WINDOW_PAST_DAYS = 7
WINDOW_FUTURE_DAYS = 60


def sync_window(today: date) -> tuple[datetime, datetime]:
    start = datetime.combine(today - timedelta(days=WINDOW_PAST_DAYS), time.min)
    end = datetime.combine(today + timedelta(days=WINDOW_FUTURE_DAYS), time.min)
    return start, end


def poll_due(poll_times: list[str], last_polled: datetime | None, now: datetime) -> bool:
    """Whether a poll time ("HH:MM") has passed since the last poll, or the
    app has not polled since it started."""
    if not poll_times or last_polled is None:
        return bool(poll_times)
    for day in (now.date(), now.date() - timedelta(days=1)):
        for poll_time in poll_times:
            hour, minute = poll_time.split(":")
            at = datetime.combine(day, time(int(hour), int(minute)))
            if last_polled < at <= now:
                return True
    return False


def sync(db: Session, source: WorkCalendarSource, *, today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    window_start, window_end = sync_window(today)
    fetched = source.fetch(window_start, window_end)

    existing = {
        e.external_id: e
        for e in db.scalars(
            select(Event).where(
                Event.source == EventSource.work,
                Event.start >= window_start,
                Event.start < window_end,
            )
        )
    }
    seen: set[str] = set()
    created = updated = 0
    for ext in fetched:
        seen.add(ext.external_id)
        row = existing.get(ext.external_id) or db.scalar(
            select(Event).where(
                Event.source == EventSource.work, Event.external_id == ext.external_id
            )
        )
        if row is None:
            db.add(
                Event(
                    title=ext.title,
                    start=ext.start,
                    end=ext.end,
                    all_day=ext.all_day,
                    location=ext.location,
                    source=EventSource.work,
                    read_only=True,
                    external_id=ext.external_id,
                )
            )
            created += 1
        else:
            changed = (
                row.title != ext.title
                or row.start != ext.start
                or row.end != ext.end
                or row.all_day != ext.all_day
                or row.location != ext.location
            )
            if changed:
                row.title = ext.title
                row.start = ext.start
                row.end = ext.end
                row.all_day = ext.all_day
                row.location = ext.location
                updated += 1
    deleted = 0
    for external_id, row in existing.items():
        if external_id not in seen:
            db.delete(row)
            deleted += 1
    db.flush()
    return {"created": created, "updated": updated, "deleted": deleted}
