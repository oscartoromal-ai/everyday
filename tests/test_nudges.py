from datetime import datetime, timedelta

from app.models import NudgeType, TaskStatus
from app.services import blocks as blocks_svc
from app.services import nudges as nudges_svc
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

NOW = datetime(2026, 8, 28, 10, 0)
TODAY = NOW.date()


def _missed_task(db, title="deep work"):
    task = tasks_svc.create_task(db, title=title, planned_for=TODAY)
    blocks_svc.schedule_block(
        db, task_id=task.id, start=NOW - timedelta(hours=3), end=NOW - timedelta(hours=2)
    )
    blocks_svc.mark_missed_blocks(db, NOW)
    return task


def test_missed_block_nudge_raised_once(db) -> None:
    task = _missed_task(db)
    created = nudges_svc.evaluate(db, NOW)
    assert [n.type for n in created] == [NudgeType.missed_block]
    assert created[0].task_id == task.id
    assert "deep work" in created[0].message

    # Same fact never nags twice, even after dismissal.
    nudges_svc.dismiss(db, created[0].id, NOW)
    assert nudges_svc.evaluate(db, NOW) == []
    assert nudges_svc.active_nudges(db) == []


def test_due_and_milestone_nudges_within_lookahead(db) -> None:
    p = projects_svc.create_project(db, name="App")
    projects_svc.create_milestone(
        db, project_id=p.id, name="v1", target_date=TODAY + timedelta(days=2)
    )
    tasks_svc.create_task(db, title="near", due=TODAY + timedelta(days=3))
    tasks_svc.create_task(db, title="far", due=TODAY + timedelta(days=10))
    done = tasks_svc.create_task(db, title="done already", due=TODAY + timedelta(days=1))
    tasks_svc.set_status(db, done.id, TaskStatus.done)

    created = nudges_svc.evaluate(db, NOW)
    types = sorted(n.type.value for n in created)
    assert types == ["due_soon", "milestone_soon"]
    assert any("near" in n.message for n in created)
    assert any("v1" in n.message for n in created)


def test_needs_review_nudge_after_threshold(db) -> None:
    fresh = tasks_svc.create_task(db, title="fresh review")
    tasks_svc.set_status(db, fresh.id, TaskStatus.needs_review)
    stale = tasks_svc.create_task(db, title="stale review")
    tasks_svc.set_status(db, stale.id, TaskStatus.needs_review)
    stale.status_changed_at = NOW - timedelta(hours=72)
    db.flush()

    created = nudges_svc.evaluate(db, NOW)
    assert [n.type for n in created] == [NudgeType.needs_review]
    assert "stale review" in created[0].message


def test_morning_digest_shape(db) -> None:
    tasks_svc.create_task(db, title="plan the day", planned_for=TODAY)
    tasks_svc.create_task(db, title="pay invoice", due=TODAY + timedelta(days=1))
    _missed_task(db, title="slipped thing")

    digest = nudges_svc.build_morning_digest(db, NOW)
    assert "2 task(s) planned" in digest
    assert "slipped thing" in digest
    assert "pay invoice" in digest
