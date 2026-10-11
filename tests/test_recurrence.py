from datetime import date, timedelta

from sqlalchemy import select

from app.models import Event, RecurrenceKind, Task, TaskStatus
from app.services import recurrence as rec_svc
from app.services import tasks as tasks_svc

TODAY = date(2026, 8, 28)  # a Friday


def _task_template(db, repeat: str = "daily", **kwargs):
    return rec_svc.create_template(
        db,
        kind=RecurrenceKind.task,
        repeat=repeat,
        start_date=TODAY,
        title="water the plants",
        **kwargs,
    )


def test_daily_rule_with_interval(db) -> None:
    t = _task_template(db, repeat="daily", interval=2)
    days = rec_svc.rule_dates(t, TODAY, TODAY + timedelta(days=8))
    assert days == [TODAY + timedelta(days=i) for i in (0, 2, 4, 6, 8)]


def test_weekdays_rule(db) -> None:
    t = _task_template(db, repeat="weekdays")
    days = rec_svc.rule_dates(t, TODAY, TODAY + timedelta(days=6))
    # Friday, then Mon-Thu of next week (Sat/Sun skipped)
    assert [d.isoweekday() for d in days] == [5, 1, 2, 3, 4]


def test_monthly_rule_skips_short_months(db) -> None:
    t = rec_svc.create_template(
        db,
        kind=RecurrenceKind.task,
        repeat="monthly",
        start_date=date(2026, 8, 31),
        title="pay rent",
    )
    days = rec_svc.rule_dates(t, date(2026, 8, 31), date(2026, 12, 31))
    assert days == [date(2026, 8, 31), date(2026, 10, 31), date(2026, 12, 31)]


def test_materialize_is_idempotent_and_respects_deletions(db) -> None:
    t = _task_template(db, repeat="daily")
    created = rec_svc.materialize_template(db, t, TODAY)
    assert created == 8 * 7 + 1  # today through the 8-week horizon

    assert rec_svc.materialize_template(db, t, TODAY) == 0  # idempotent

    # Deleting an occurrence must not resurrect it on the next run.
    victim = db.scalars(
        select(Task).where(Task.occurrence_date == TODAY + timedelta(days=3))
    ).one()
    db.delete(victim)
    db.flush()
    assert rec_svc.materialize_template(db, t, TODAY) == 0

    # A day later the horizon moves: exactly one new occurrence appears.
    assert rec_svc.materialize_template(db, t, TODAY + timedelta(days=1)) == 1


def test_occurrences_are_individually_editable_tasks(db) -> None:
    t = _task_template(db, repeat="daily")
    rec_svc.materialize_template(db, t, TODAY)
    first = db.scalars(select(Task).where(Task.occurrence_date == TODAY)).one()
    assert first.planned_for == TODAY
    tasks_svc.set_status(db, first.id, TaskStatus.done)
    assert first.recurrence_template_id == t.id


def test_occurrences_start_with_their_subtasks_open(db) -> None:
    t = _task_template(
        db, repeat="daily", notes="Before watering:\n- [x] check soil\n- [ ] fill can\n- a bullet"
    )
    rec_svc.materialize_template(db, t, TODAY)
    first = db.scalars(select(Task).where(Task.occurrence_date == TODAY)).one()
    assert first.notes == "Before watering:\n- [ ] check soil\n- [ ] fill can\n- a bullet"


def test_stop_template_drops_pristine_future_only(db) -> None:
    t = _task_template(db, repeat="daily")
    rec_svc.materialize_template(db, t, TODAY)
    touched = db.scalars(
        select(Task).where(Task.occurrence_date == TODAY + timedelta(days=2))
    ).one()
    tasks_svc.set_status(db, touched.id, TaskStatus.in_progress)

    rec_svc.stop_template(db, t.id, from_date=TODAY)
    remaining = list(db.scalars(select(Task).where(Task.recurrence_template_id == t.id)))
    assert {task.occurrence_date for task in remaining} == {TODAY, TODAY + timedelta(days=2)}
    assert not t.active


def test_event_template_materializes_events(db) -> None:
    t = rec_svc.create_template(
        db,
        kind=RecurrenceKind.event,
        repeat="weekly",
        start_date=TODAY,
        title="Yoga",
        start_time="18:00",
        end_time="19:00",
    )
    rec_svc.materialize_template(db, t, TODAY)
    events = list(db.scalars(select(Event).where(Event.recurrence_template_id == t.id)))
    assert len(events) == 9  # every Friday over 8 weeks, inclusive
    assert all(e.start.hour == 18 and e.end.hour == 19 for e in events)
    assert all(e.start.date().isoweekday() == 5 for e in events)
