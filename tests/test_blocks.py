from datetime import datetime, timedelta

from app.models import BlockState, Event, EventSource
from app.services import blocks as blocks_svc
from app.services import tasks as tasks_svc

DAY = datetime(2026, 9, 25)
AFTER = DAY.replace(hour=14, minute=7)
UNTIL = DAY.replace(hour=22)
HOUR = timedelta(hours=1)


def at(hour: int, minute: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute)


def work_event(title: str, start: datetime, end: datetime) -> Event:
    return Event(title=title, start=start, end=end, source=EventSource.work, read_only=True)


def test_next_free_slot_starts_on_the_next_quarter_hour(db) -> None:
    assert blocks_svc.next_free_slot(db, duration=HOUR, after=AFTER, until=UNTIL) == at(14, 15)
    assert blocks_svc.next_free_slot(db, duration=HOUR, after=at(14), until=UNTIL) == at(14)


def test_next_free_slot_steps_past_events_and_blocks(db) -> None:
    db.add(work_event("1:1", at(14, 30), at(15)))
    task = tasks_svc.create_task(db, title="deep work")
    blocks_svc.schedule_block(db, task_id=task.id, start=at(15, 30), end=at(16, 30))
    db.flush()
    # 14:15-15:15 hits the 1:1; 15:00-16:00 hits the block; 16:30 is the first gap.
    assert blocks_svc.next_free_slot(db, duration=HOUR, after=AFTER, until=UNTIL) == at(16, 30)
    # A 15-minute task still fits before the 1:1.
    quarter = timedelta(minutes=15)
    assert blocks_svc.next_free_slot(db, duration=quarter, after=AFTER, until=UNTIL) == at(14, 15)


def test_next_free_slot_ignores_all_day_events_and_missed_blocks(db) -> None:
    db.add(Event(title="Holiday", start=DAY, end=DAY + timedelta(days=1), all_day=True))
    task = tasks_svc.create_task(db, title="slipped")
    block = blocks_svc.schedule_block(db, task_id=task.id, start=at(14, 15), end=at(15, 15))
    block.state = BlockState.missed
    db.flush()
    assert blocks_svc.next_free_slot(db, duration=HOUR, after=AFTER, until=UNTIL) == at(14, 15)


def test_next_free_slot_is_none_when_the_day_is_full(db) -> None:
    db.add(work_event("Offsite", at(14), at(21, 30)))
    db.flush()
    assert blocks_svc.next_free_slot(db, duration=HOUR, after=AFTER, until=UNTIL) is None
    assert blocks_svc.next_free_slot(db, duration=HOUR, after=at(21, 30), until=UNTIL) is None


def test_the_hour_label_under_the_now_label_gives_way(db) -> None:
    from app.ui.calendar_view import grid_ctx, week_monday

    monday = week_monday(DAY.date())
    # 15:05 sits 4px under the 15:00 line: that label would peek out, so it hides.
    assert grid_ctx(db, monday, at(15, 5))["hours_under_now"] == [9]
    # 06:41 comes within a line box of 07:00, but the digits never meet: it stays.
    assert grid_ctx(db, monday, at(6, 41))["hours_under_now"] == []
    # 15:30 is clear of both 15:00 and 16:00.
    assert grid_ctx(db, monday, at(15, 30))["hours_under_now"] == []
    # 06:10 is just under the first label, which sits 2px from the top.
    assert grid_ctx(db, monday, at(6, 10))["hours_under_now"] == [0]
