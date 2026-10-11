from datetime import datetime, timedelta

from app.models import NudgeType, TaskStatus
from app.services import notebook as notebook_svc
from app.services import nudges as nudges_svc
from app.services import tasks as tasks_svc

NOW = datetime(2026, 8, 28, 10, 0)
TODAY = NOW.date()


def test_a_nudge_is_raised_once(db) -> None:
    task = tasks_svc.create_task(db, title="pay invoice", due=TODAY + timedelta(days=1))
    created = nudges_svc.evaluate(db, NOW)
    assert [n.type for n in created] == [NudgeType.due_soon]
    assert created[0].task_id == task.id
    assert "pay invoice" in created[0].message

    # Same fact never nags twice, even after dismissal.
    nudges_svc.dismiss(db, created[0].id, NOW)
    assert nudges_svc.evaluate(db, NOW) == []
    assert nudges_svc.active_nudges(db) == []


def test_a_nudge_says_its_days_from_today(db) -> None:
    task = tasks_svc.create_task(db, title="pay invoice", due=TODAY + timedelta(days=1))
    [nudge] = nudges_svc.evaluate(db, NOW)
    assert nudge.message == "“pay invoice” is due tomorrow."
    # Read the next day, the same nudge says today.
    assert nudges_svc.wording(db, nudge, TODAY + timedelta(days=1)) == "“pay invoice” is due today."
    tasks_svc.update_task(db, task.id, title="pay the invoice")
    assert nudges_svc.wording(db, nudge, TODAY) == "“pay the invoice” is due tomorrow."


def test_due_nudges_within_lookahead(db) -> None:
    tasks_svc.create_task(db, title="near", due=TODAY + timedelta(days=3))
    tasks_svc.create_task(db, title="far", due=TODAY + timedelta(days=10))
    done = tasks_svc.create_task(db, title="done already", due=TODAY + timedelta(days=1))
    tasks_svc.set_status(db, done.id, TaskStatus.done)

    created = nudges_svc.evaluate(db, NOW)
    types = sorted(n.type.value for n in created)
    assert types == ["due_soon"]
    assert any("near" in n.message for n in created)


def test_a_nudge_stays_only_while_its_fact_holds(db) -> None:
    due = tasks_svc.create_task(db, title="invoice", due=TODAY + timedelta(days=1))
    review = tasks_svc.create_task(db, title="review me")
    tasks_svc.set_status(db, review.id, TaskStatus.needs_review)
    review.status_changed_at = NOW - timedelta(hours=72)
    db.flush()
    nudges_svc.evaluate(db, NOW)
    assert len(nudges_svc.active_nudges(db)) == 2

    # Finished, reviewed: each nudge has had its answer.
    tasks_svc.set_status(db, due.id, TaskStatus.done)
    tasks_svc.set_status(db, review.id, TaskStatus.done)
    assert nudges_svc.active_nudges(db) == []

    # Its fact true again (the task open again), the due nudge comes back.
    tasks_svc.set_status(db, due.id, TaskStatus.todo)
    assert [n.task_id for n in nudges_svc.active_nudges(db)] == [due.id]


def test_a_nudge_goes_when_its_task_moves_off_that_fact(db) -> None:
    task = tasks_svc.create_task(db, title="invoice", due=TODAY + timedelta(days=1))
    [due] = nudges_svc.evaluate(db, NOW)
    # Its due day moved on a month: not due tomorrow any more.
    tasks_svc.update_task(db, task.id, due=TODAY + timedelta(days=30))
    assert nudges_svc.active_nudges(db) == []
    # Moved back near, it is the fact again, and the nudge says so.
    tasks_svc.update_task(db, task.id, due=TODAY + timedelta(days=1))
    assert nudges_svc.active_nudges(db) == [due]

    # A review that ended and began again is a new fact: the old one's
    # nudge goes as the new one's comes.
    review = tasks_svc.create_task(db, title="review me")
    tasks_svc.set_status(db, review.id, TaskStatus.needs_review)
    review.status_changed_at = NOW - timedelta(hours=72)
    [first] = [n for n in nudges_svc.evaluate(db, NOW) if n.type == NudgeType.needs_review]
    tasks_svc.set_status(db, review.id, TaskStatus.in_progress)
    tasks_svc.set_status(db, review.id, TaskStatus.needs_review)
    review.status_changed_at = NOW - timedelta(hours=50)
    [second] = [n for n in nudges_svc.evaluate(db, NOW) if n.type == NudgeType.needs_review]
    assert [n for n in nudges_svc.active_nudges(db) if n.task_id == review.id] == [second]
    assert first is not second


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

    digest = nudges_svc.build_morning_digest(db, NOW)
    assert "1 task(s) planned" in digest
    assert "pay invoice" in digest


def test_today_shows_each_task_once(db) -> None:
    later = tasks_svc.create_task(db, title="later", due=TODAY + timedelta(days=2))
    planned = tasks_svc.create_task(
        db, title="planned", due=TODAY + timedelta(days=2), planned_for=TODAY
    )
    due_today = tasks_svc.create_task(db, title="due today", due=TODAY)
    written = tasks_svc.create_task(db, title="written", due=TODAY + timedelta(days=2))
    notebook_svc.save_page(
        db, TODAY, [{"kind": "text", "text": "- [ ] written", "links": {"0": written.id}}],
        version=0,
    )
    review = tasks_svc.create_task(db, title="review me", planned_for=TODAY)
    tasks_svc.set_status(db, review.id, TaskStatus.needs_review)
    review.status_changed_at = NOW - timedelta(hours=72)
    db.flush()
    nudges_svc.evaluate(db, NOW)
    assert {n.task_id for n in nudges_svc.active_nudges(db)} == {
        later.id, planned.id, due_today.id, written.id, review.id,
    }

    # A due the page has already, written in its notes or offered to bring
    # there with its due beside it, is not nudged again; a review is.
    assert {n.task_id for n in nudges_svc.on_today(db, TODAY)} == {later.id, review.id}
