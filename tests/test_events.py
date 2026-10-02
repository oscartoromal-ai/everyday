from datetime import datetime, timedelta

import pytest

from app.models import Event, EventSource
from app.services import DomainError
from app.services import events as events_svc

NOW = datetime(2026, 8, 28, 10, 0)


def _work_event(db, title: str = "standup") -> Event:
    event = Event(
        title=title,
        start=NOW,
        end=NOW + timedelta(hours=1),
        source=EventSource.work,
        read_only=True,
        external_id="abc-1",
    )
    db.add(event)
    db.flush()
    return event


def test_work_events_are_read_only(db) -> None:
    event = _work_event(db)
    with pytest.raises(DomainError):
        events_svc.update_event(db, event.id, title="renamed")
    with pytest.raises(DomainError):
        events_svc.delete_event(db, event.id)


def test_calendar_range_holds_both_sources_in_the_window(db) -> None:
    local = events_svc.create_event(
        db, title="dentist", start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2)
    )
    work = _work_event(db)
    events_svc.create_event(
        db, title="next week", start=NOW + timedelta(days=9), end=NOW + timedelta(days=9, hours=1)
    )

    events = events_svc.calendar_range(db, NOW, NOW + timedelta(days=1))
    assert [e.id for e in events] == [work.id, local.id]


def at(hour: int, minute: int = 0) -> datetime:
    return NOW.replace(hour=hour, minute=minute)


def test_busy_spans_merge_overlaps_and_clip_to_the_window(db) -> None:
    events_svc.create_event(db, title="1:1", start=at(9, 30), end=at(10, 30))
    events_svc.create_event(db, title="review", start=at(10), end=at(11))
    events_svc.create_event(db, title="lunch", start=at(12), end=at(13))
    assert events_svc.busy_spans(db, at(10), at(12, 30)) == [(at(10), at(11)), (at(12), at(12, 30))]


def test_busy_spans_pass_over_all_day_events_and_cancelled_meetings(db) -> None:
    midnight = at(0)
    db.add(Event(title="Holiday", start=midnight, end=midnight + timedelta(days=1), all_day=True))
    db.add(Event(title="Canceled: sync", start=at(14), end=at(15), source=EventSource.work,
                 read_only=True, external_id="c-1"))
    db.flush()
    assert events_svc.busy_spans(db, at(8), at(22)) == []


def test_event_time_validation(db) -> None:
    with pytest.raises(DomainError):
        events_svc.create_event(db, title="bad", start=NOW, end=NOW)
