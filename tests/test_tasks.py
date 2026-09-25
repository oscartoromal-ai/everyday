from datetime import datetime, timedelta

import pytest

from app.models import BlockState, TaskOwner, TaskStatus
from app.services import DomainError
from app.services import blocks as blocks_svc
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

NOW = datetime(2026, 8, 28, 10, 0)
TODAY = NOW.date()


def test_milestone_must_belong_to_tasks_project(db) -> None:
    p1 = projects_svc.create_project(db, name="App")
    p2 = projects_svc.create_project(db, name="Other")
    m1 = projects_svc.create_milestone(db, project_id=p1.id, name="v1")
    with pytest.raises(DomainError):
        tasks_svc.create_task(db, title="t", project_id=p2.id, milestone_id=m1.id)
    with pytest.raises(DomainError):
        tasks_svc.create_task(db, title="t", milestone_id=m1.id)
    task = tasks_svc.create_task(db, title="t", project_id=p1.id, milestone_id=m1.id)
    assert task.milestone_id == m1.id


def test_moving_task_off_project_drops_milestone(db) -> None:
    p1 = projects_svc.create_project(db, name="App")
    p2 = projects_svc.create_project(db, name="Other")
    m1 = projects_svc.create_milestone(db, project_id=p1.id, name="v1")
    task = tasks_svc.create_task(db, title="t", project_id=p1.id, milestone_id=m1.id)
    tasks_svc.update_task(db, task.id, project_id=p2.id)
    assert task.milestone_id is None


def test_status_change_stamps_status_changed_at(db) -> None:
    task = tasks_svc.create_task(db, title="t")
    before = task.status_changed_at
    tasks_svc.set_status(db, task.id, TaskStatus.todo)  # no-op keeps the stamp
    assert task.status_changed_at == before
    tasks_svc.set_status(db, task.id, TaskStatus.in_progress)
    assert task.status_changed_at > before


def test_missed_marker_derives_from_blocks(db) -> None:
    task = tasks_svc.create_task(db, title="deep work", planned_for=TODAY)
    block = blocks_svc.schedule_block(
        db, task_id=task.id, start=NOW - timedelta(hours=3), end=NOW - timedelta(hours=2)
    )
    assert not tasks_svc.has_missed_marker(task, NOW)

    missed = blocks_svc.mark_missed_blocks(db, NOW)
    assert [b.id for b in missed] == [block.id]
    assert tasks_svc.has_missed_marker(task, NOW)

    # Replanning to a future slot clears the marker; the missed block stays missed.
    blocks_svc.schedule_block(
        db, task_id=task.id, start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2)
    )
    assert not tasks_svc.has_missed_marker(task, NOW)
    assert block.state == BlockState.missed


def test_missed_marker_gone_when_done(db) -> None:
    task = tasks_svc.create_task(db, title="t")
    blocks_svc.schedule_block(
        db, task_id=task.id, start=NOW - timedelta(hours=3), end=NOW - timedelta(hours=2)
    )
    blocks_svc.mark_missed_blocks(db, NOW)
    tasks_svc.set_status(db, task.id, TaskStatus.done)
    assert not tasks_svc.has_missed_marker(task, NOW)


def test_ghost_blocks_scoped_to_day(db) -> None:
    task = tasks_svc.create_task(db, title="t")
    yesterday = blocks_svc.schedule_block(
        db,
        task_id=task.id,
        start=NOW - timedelta(days=1, hours=2),
        end=NOW - timedelta(days=1, hours=1),
    )
    today = blocks_svc.schedule_block(
        db, task_id=task.id, start=NOW - timedelta(hours=2), end=NOW - timedelta(hours=1)
    )
    blocks_svc.mark_missed_blocks(db, NOW)
    ghosts = blocks_svc.ghost_blocks(db, TODAY)
    assert [g.id for g in ghosts] == [today.id]
    assert yesterday.state == BlockState.missed  # still missed, just not today's ghost


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


def test_next_days_view(db) -> None:
    p = projects_svc.create_project(db, name="App")
    m = projects_svc.create_milestone(
        db, project_id=p.id, name="v1", target_date=TODAY + timedelta(days=2)
    )
    planned = tasks_svc.create_task(db, title="planned", planned_for=TODAY + timedelta(days=1))
    due = tasks_svc.create_task(db, title="due", due=TODAY + timedelta(days=2))
    tasks_svc.create_task(db, title="far away", due=TODAY + timedelta(days=30))

    view = tasks_svc.next_days(db, TODAY, days=7)
    assert [t.id for t in view[TODAY + timedelta(days=1)]["planned"]] == [planned.id]
    assert [t.id for t in view[TODAY + timedelta(days=2)]["due"]] == [due.id]
    assert [ms.id for ms in view[TODAY + timedelta(days=2)]["milestones"]] == [m.id]
    assert all(not v["due"] for day, v in view.items() if day != TODAY + timedelta(days=2))


def test_milestone_progress(db) -> None:
    p = projects_svc.create_project(db, name="App")
    m = projects_svc.create_milestone(db, project_id=p.id, name="v1")
    t1 = tasks_svc.create_task(db, title="a", project_id=p.id, milestone_id=m.id)
    tasks_svc.create_task(db, title="b", project_id=p.id, milestone_id=m.id)
    cancelled = tasks_svc.create_task(db, title="c", project_id=p.id, milestone_id=m.id)
    tasks_svc.set_status(db, t1.id, TaskStatus.done)
    tasks_svc.set_status(db, cancelled.id, TaskStatus.cancelled)
    assert projects_svc.milestone_progress(db, m.id) == (1, 2)


def test_block_requires_open_task(db) -> None:
    task = tasks_svc.create_task(db, title="t")
    tasks_svc.set_status(db, task.id, TaskStatus.done)
    with pytest.raises(DomainError):
        blocks_svc.schedule_block(
            db, task_id=task.id, start=NOW, end=NOW + timedelta(hours=1)
        )


def test_deleting_a_task_takes_its_blocks_and_nudges(db) -> None:
    from sqlalchemy import select

    from app.models import Block, Nudge
    from app.services import nudges as nudges_svc

    task = tasks_svc.create_task(db, title="slipped", planned_for=TODAY)
    blocks_svc.schedule_block(
        db, task_id=task.id, start=NOW - timedelta(hours=3), end=NOW - timedelta(hours=2)
    )
    blocks_svc.mark_missed_blocks(db, NOW)
    assert nudges_svc.evaluate(db, NOW)  # a missed-block nudge now points at the task

    tasks_svc.delete_task(db, task.id)

    assert db.scalars(select(Block)).all() == []
    assert db.scalars(select(Nudge)).all() == []
