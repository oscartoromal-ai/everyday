from datetime import datetime, timedelta

import pytest

from app.models import Event, EventSource
from app.services import DomainError
from app.services import blocks as blocks_svc
from app.services import events as events_svc
from app.services import tasks as tasks_svc

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


def test_calendar_range_unifies_events_and_blocks(db) -> None:
    local = events_svc.create_event(
        db, title="dentist", start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2)
    )
    work = _work_event(db)
    task = tasks_svc.create_task(db, title="deep work")
    block = blocks_svc.schedule_block(
        db, task_id=task.id, start=NOW + timedelta(hours=3), end=NOW + timedelta(hours=4)
    )
    events_svc.create_event(
        db, title="next week", start=NOW + timedelta(days=9), end=NOW + timedelta(days=9, hours=1)
    )

    events, blocks = events_svc.calendar_range(db, NOW, NOW + timedelta(days=1))
    assert {e.id for e in events} == {local.id, work.id}
    assert [b.id for b in blocks] == [block.id]
    assert blocks[0].task.title == "deep work"


def test_event_time_validation(db) -> None:
    with pytest.raises(DomainError):
        events_svc.create_event(db, title="bad", start=NOW, end=NOW)
