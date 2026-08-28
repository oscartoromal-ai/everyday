"""Nudge triggers and the morning digest (SPEC.md section 7).

Deterministic rules only: evaluations emit templated nudges, deduplicated by a
key naming the underlying fact, so the same fact never nags twice. The fourth
trigger (activity without plan update) arrives with v2 session capture.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.dates import short_date
from app.models import (
    Block,
    BlockState,
    Milestone,
    MilestoneStatus,
    Nudge,
    NudgeType,
    Task,
    TaskStatus,
)
from app.services import events as events_svc
from app.services import tasks as tasks_svc

DUE_LOOKAHEAD_DAYS = 3
NEEDS_REVIEW_THRESHOLD = timedelta(hours=48)


def _raise_nudge(
    db: Session,
    *,
    type_: NudgeType,
    dedup_key: str,
    message: str,
    task_id: int | None = None,
) -> Nudge | None:
    exists = db.scalar(select(Nudge).where(Nudge.dedup_key == dedup_key))
    if exists is not None:
        return None
    nudge = Nudge(type=type_, dedup_key=dedup_key, message=message, task_id=task_id)
    db.add(nudge)
    db.flush()
    return nudge


def evaluate(db: Session, now: datetime) -> list[Nudge]:
    """Run every v1 trigger; returns only newly created nudges."""
    today = now.date()
    created: list[Nudge] = []

    # 1. Missed blocks: nudge to replan the fallen-back task.
    open_tasks = list(
        db.scalars(
            select(Task)
            .options(selectinload(Task.blocks))
            .where(Task.status.in_(tasks_svc.OPEN_STATUSES))
        )
    )
    for task in open_tasks:
        if not tasks_svc.has_missed_marker(task, now):
            continue
        missed_blocks = [b for b in task.blocks if b.state == BlockState.missed]
        block: Block = max(missed_blocks, key=lambda b: b.start)
        nudge = _raise_nudge(
            db,
            type_=NudgeType.missed_block,
            dedup_key=f"missed:{block.id}",
            message=(
                f"“{task.title}” missed its block {short_date(block.start.date(), today)} "
                f"at {block.start:%H:%M}. Replan it?"
            ),
            task_id=task.id,
        )
        if nudge:
            created.append(nudge)

    # 3. Upcoming due dates and milestone targets within the lookahead window.
    horizon = today + timedelta(days=DUE_LOOKAHEAD_DAYS)
    for task in open_tasks:
        if task.due is not None and today <= task.due <= horizon:
            nudge = _raise_nudge(
                db,
                type_=NudgeType.due_soon,
                dedup_key=f"due:{task.id}:{task.due.isoformat()}",
                message=f"“{task.title}” is due {short_date(task.due, today)}.",
                task_id=task.id,
            )
            if nudge:
                created.append(nudge)
    milestones = db.scalars(
        select(Milestone)
        .options(selectinload(Milestone.project))
        .where(
            Milestone.status == MilestoneStatus.open,
            Milestone.target_date.is_not(None),
            Milestone.target_date.between(today, horizon),
        )
    )
    for milestone in milestones:
        nudge = _raise_nudge(
            db,
            type_=NudgeType.milestone_soon,
            dedup_key=f"milestone:{milestone.id}:{milestone.target_date.isoformat()}",
            message=(
                f"Milestone “{milestone.name}” ({milestone.project.name}) targets "
                f"{short_date(milestone.target_date, today)}."
            ),
        )
        if nudge:
            created.append(nudge)

    # 4. Needs-review backlog beyond the threshold.
    for task in open_tasks:
        if (
            task.status == TaskStatus.needs_review
            and now - task.status_changed_at >= NEEDS_REVIEW_THRESHOLD
        ):
            nudge = _raise_nudge(
                db,
                type_=NudgeType.needs_review,
                dedup_key=f"review:{task.id}:{task.status_changed_at.isoformat()}",
                message=(
                    f"“{task.title}” has been waiting for review since "
                    f"{short_date(task.status_changed_at.date(), today)}."
                ),
                task_id=task.id,
            )
            if nudge:
                created.append(nudge)
    return created


def active_nudges(db: Session) -> list[Nudge]:
    return list(
        db.scalars(
            select(Nudge)
            .where(Nudge.dismissed_at.is_(None))
            .order_by(Nudge.created_at.desc())
        )
    )


def dismiss(db: Session, nudge_id: int, now: datetime | None = None) -> None:
    nudge = db.get(Nudge, nudge_id)
    if nudge is not None and nudge.dismissed_at is None:
        nudge.dismissed_at = now or datetime.now()
        db.flush()


def build_morning_digest(db: Session, now: datetime) -> str:
    """The day's shape in one message: plan, events, misses, dues, review pile."""
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    planned = [t for t in tasks_svc.daily_list(db, today) if t.status in tasks_svc.OPEN_STATUSES]
    events, _ = events_svc.calendar_range(db, day_start, day_end)
    missed = [
        t
        for t in db.scalars(
            select(Task)
            .options(selectinload(Task.blocks))
            .where(Task.status.in_(tasks_svc.OPEN_STATUSES))
        )
        if tasks_svc.has_missed_marker(t, now)
    ]
    horizon = today + timedelta(days=DUE_LOOKAHEAD_DAYS)
    due = list(
        db.scalars(
            select(Task).where(
                Task.status.in_(tasks_svc.OPEN_STATUSES), Task.due.between(today, horizon)
            )
        )
    )
    review = list(
        db.scalars(select(Task).where(Task.status == TaskStatus.needs_review))
    )

    lines = [f"{today.strftime('%A')} {today.day} {today.strftime('%B')}"]
    lines.append(
        f"{len(planned)} task(s) planned, {len(events)} event(s) on the calendar."
    )
    if missed:
        lines.append("Missed and unreplanned: " + "; ".join(t.title for t in missed[:5]) + ".")
    if due:
        lines.append(
            "Due soon: "
            + "; ".join(f"{t.title} ({short_date(t.due, today)})" for t in due[:5])
            + "."
        )
    if review:
        lines.append(f"{len(review)} task(s) waiting for review.")
    if len(lines) == 2 and not planned:
        lines.append("A clear day.")
    return "\n".join(lines)
