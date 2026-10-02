from datetime import datetime, timedelta

import pytest

from app.models import TaskOwner, TaskStatus
from app.services import DomainError
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

NOW = datetime(2026, 8, 28, 10, 0)
TODAY = NOW.date()


def test_workstream_must_belong_to_tasks_project(db) -> None:
    p1 = projects_svc.create_project(db, name="App")
    p2 = projects_svc.create_project(db, name="Other")
    m1 = projects_svc.create_workstream(db, project_id=p1.id, name="v1")
    with pytest.raises(DomainError):
        tasks_svc.create_task(db, title="t", project_id=p2.id, workstream_id=m1.id)
    with pytest.raises(DomainError):
        tasks_svc.create_task(db, title="t", workstream_id=m1.id)
    task = tasks_svc.create_task(db, title="t", project_id=p1.id, workstream_id=m1.id)
    assert task.workstream_id == m1.id


def test_moving_task_off_project_drops_workstream(db) -> None:
    p1 = projects_svc.create_project(db, name="App")
    p2 = projects_svc.create_project(db, name="Other")
    m1 = projects_svc.create_workstream(db, project_id=p1.id, name="v1")
    task = tasks_svc.create_task(db, title="t", project_id=p1.id, workstream_id=m1.id)
    tasks_svc.update_task(db, task.id, project_id=p2.id)
    assert task.workstream_id is None


def test_status_change_stamps_status_changed_at(db) -> None:
    task = tasks_svc.create_task(db, title="t")
    before = task.status_changed_at
    tasks_svc.set_status(db, task.id, TaskStatus.todo)  # no-op keeps the stamp
    assert task.status_changed_at == before
    tasks_svc.set_status(db, task.id, TaskStatus.in_progress)
    assert task.status_changed_at > before


def test_daily_backlog_delegated_lists(db) -> None:
    planned = tasks_svc.create_task(db, title="today", planned_for=TODAY)
    backlog_task = tasks_svc.create_task(db, title="someday")
    delegated_task = tasks_svc.create_task(db, title="claude job", owner=TaskOwner.claude)
    done = tasks_svc.create_task(db, title="finished")
    tasks_svc.set_status(db, done.id, TaskStatus.done)

    assert [t.id for t in tasks_svc.daily_list(db, TODAY)] == [planned.id]
    backlog_ids = {t.id for t in tasks_svc.backlog(db)}
    assert backlog_task.id in backlog_ids and delegated_task.id in backlog_ids
    assert done.id not in backlog_ids
    assert [t.id for t in tasks_svc.delegated(db)] == [delegated_task.id]


def test_planning_list_is_oscars_open_tasks(db) -> None:
    mine = tasks_svc.create_task(db, title="mine")
    dated = tasks_svc.create_task(db, title="dated", planned_for=TODAY + timedelta(days=9))
    tasks_svc.create_task(db, title="claude job", owner=TaskOwner.claude)
    done = tasks_svc.create_task(db, title="finished")
    tasks_svc.set_status(db, done.id, TaskStatus.done)

    assert {t.id for t in tasks_svc.planning_list(db, TODAY)} == {mine.id, dated.id}


def test_planning_list_shows_one_occurrence_per_series(db) -> None:
    from app.models import RecurrenceKind
    from app.services import recurrence as rec_svc

    series = rec_svc.create_template(
        db,
        kind=RecurrenceKind.task,
        repeat="daily",
        start_date=TODAY - timedelta(days=2),
        title="water the plants",
    )
    rec_svc.materialize_template(db, series, TODAY - timedelta(days=2))
    shown = [t for t in tasks_svc.planning_list(db, TODAY) if t.recurrence_template_id]
    # The next one due, not the missed ones behind it or the weeks ahead.
    assert [t.planned_for for t in shown] == [TODAY]

    # Once every upcoming one is closed, the latest overdue one stands in.
    for t in tasks_svc.list_tasks(db):
        if t.planned_for >= TODAY:
            tasks_svc.set_status(db, t.id, TaskStatus.done)
    shown = [t for t in tasks_svc.planning_list(db, TODAY) if t.recurrence_template_id]
    assert [t.planned_for for t in shown] == [TODAY - timedelta(days=1)]


def test_next_days_view(db) -> None:
    planned = tasks_svc.create_task(db, title="planned", planned_for=TODAY + timedelta(days=1))
    due = tasks_svc.create_task(db, title="due", due=TODAY + timedelta(days=2))
    tasks_svc.create_task(db, title="far away", due=TODAY + timedelta(days=30))

    view = tasks_svc.next_days(db, TODAY, days=7)
    assert [t.id for t in view[TODAY + timedelta(days=1)]["planned"]] == [planned.id]
    assert [t.id for t in view[TODAY + timedelta(days=2)]["due"]] == [due.id]
    assert all(not v["due"] for day, v in view.items() if day != TODAY + timedelta(days=2))


def test_workstream_progress(db) -> None:
    p = projects_svc.create_project(db, name="App")
    m = projects_svc.create_workstream(db, project_id=p.id, name="v1")
    t1 = tasks_svc.create_task(db, title="a", project_id=p.id, workstream_id=m.id)
    tasks_svc.create_task(db, title="b", project_id=p.id, workstream_id=m.id)
    cancelled = tasks_svc.create_task(db, title="c", project_id=p.id, workstream_id=m.id)
    tasks_svc.set_status(db, t1.id, TaskStatus.done)
    tasks_svc.set_status(db, cancelled.id, TaskStatus.cancelled)
    assert projects_svc.workstream_progress(db, m.id) == (1, 2)


def test_deleting_a_task_takes_its_nudges(db) -> None:
    from sqlalchemy import select

    from app.models import Nudge
    from app.services import nudges as nudges_svc

    task = tasks_svc.create_task(db, title="invoice", due=TODAY + timedelta(days=1))
    assert nudges_svc.evaluate(db, NOW)  # a due nudge now points at the task

    tasks_svc.delete_task(db, task.id)

    assert db.scalars(select(Nudge)).all() == []


def test_a_new_project_takes_the_colour_fewest_open_projects_have(db) -> None:
    from app.models import ProjectStatus

    first, second = (projects_svc.create_project(db, name=n) for n in ("Home", "Work"))
    assert (first.color, second.color) == (1, 2)
    # A finished project's colour is free again; one chosen is kept.
    projects_svc.update_project(db, first.id, status=ProjectStatus.done)
    assert projects_svc.create_project(db, name="Garden").color == 1
    assert projects_svc.create_project(db, name="Trip", color=2).color == 2
    assert projects_svc.update_project(db, second.id, color=8).color == 8
    for wrong in (0, 9):
        with pytest.raises(DomainError):
            projects_svc.update_project(db, second.id, color=wrong)
