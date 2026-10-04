"""Nudge triggers and the morning digest (SPEC.md section 7).

Deterministic rules only: evaluations emit templated nudges, deduplicated by a
key naming the underlying fact, so the same fact never nags twice. The fourth
trigger (activity without plan update) arrives with v2 session capture.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.dates import short_date
from app.models import MoneyBill, Nudge, NudgeType, Task, TaskStatus
from app.services import events as events_svc
from app.services import money as money_svc
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

    open_tasks = list(
        db.scalars(select(Task).where(Task.status.in_(tasks_svc.OPEN_STATUSES)))
    )

    # 1. Upcoming due dates within the lookahead window.
    horizon = today + timedelta(days=DUE_LOOKAHEAD_DAYS)
    for task in open_tasks:
        if task.due is not None and today <= task.due <= horizon:
            nudge = _raise_nudge(
                db,
                type_=NudgeType.due_soon,
                dedup_key=f"due:{task.id}:{task.due.isoformat()}",
                message=_due_words(task.title, task.due, today),
                task_id=task.id,
            )
            if nudge:
                created.append(nudge)

    # 2. Needs-review backlog beyond the threshold.
    for task in open_tasks:
        if (
            task.status == TaskStatus.needs_review
            and now - task.status_changed_at >= NEEDS_REVIEW_THRESHOLD
        ):
            nudge = _raise_nudge(
                db,
                type_=NudgeType.needs_review,
                dedup_key=f"review:{task.id}:{task.status_changed_at.isoformat()}",
                message=_review_words(task.title, task.status_changed_at.date(), today),
                task_id=task.id,
            )
            if nudge:
                created.append(nudge)
    # 3. Bills of Finances coming due, not yet seen paid.
    for day, bill in _bills_due(db, today):
        nudge = _raise_nudge(
            db,
            type_=NudgeType.bill_due,
            dedup_key=f"bill:{bill.id}:{day.isoformat()}",
            message=_bill_words(bill, day, today),
        )
        if nudge:
            created.append(nudge)
    return created


def _bills_due(db: Session, today: date) -> list[tuple[date, MoneyBill]]:
    """The bills coming due, not yet seen paid; none on a machine installed
    without Finances."""
    if not get_settings().installed("finances"):
        return []
    return [
        (day, bill) for day, bill in money_svc.upcoming(db, today, DUE_LOOKAHEAD_DAYS + 1)
        if money_svc.payment(db, bill, day) is None
    ]


def _due_words(title: str, due: date, today: date) -> str:
    return f"“{title}” is due {short_date(due, today)}."


def _review_words(title: str, since: date, today: date) -> str:
    return f"“{title}” has been waiting for review since {short_date(since, today)}."


def _bill_words(bill: MoneyBill, day: date, today: date) -> str:
    return f"{bill.name}, {money_svc.money(bill.cents)}, is due {short_date(day, today)}."


def wording(db: Session, nudge: Nudge, today: date) -> str:
    """A nudge's words as of `today`: a nudge raised yesterday about a task
    due "tomorrow" says "today" now. Its fact is in its dedup key; the
    message kept is what was said when it was raised."""
    kind, *fact = nudge.dedup_key.split(":", 2)
    if kind == "due" and nudge.task is not None:
        return _due_words(nudge.task.title, date.fromisoformat(fact[1]), today)
    if kind == "review" and nudge.task is not None:
        return _review_words(nudge.task.title, datetime.fromisoformat(fact[1]).date(), today)
    if kind == "bill":
        bill = db.get(MoneyBill, int(fact[0]))
        if bill is not None:
            return _bill_words(bill, date.fromisoformat(fact[1]), today)
    return nudge.message


def _bill_still_due(db: Session, nudge: Nudge) -> bool:
    """A bill's nudge asks until the bill is paid, changed or gone, and not
    on a machine installed without Finances."""
    if not get_settings().installed("finances"):
        return False
    _, bill_id, day = nudge.dedup_key.split(":")
    bill = db.get(MoneyBill, int(bill_id))
    due = date.fromisoformat(day)
    if bill is None or due not in money_svc.occurrences(bill, due, due):
        return False
    return money_svc.payment(db, bill, due) is None


def _still_holds(nudge: Nudge) -> bool:
    """Whether the fact a task's nudge names is still true: a finished task
    has had its answer, so its nudge stops asking, and one whose due day
    moved, or whose review ended and began again, is another fact (with a
    nudge of its own, if it calls for one)."""
    task = nudge.task
    if task is None:
        return True
    _, _, fact = nudge.dedup_key.split(":", 2)
    if nudge.type == NudgeType.needs_review:
        return (
            task.status == TaskStatus.needs_review
            and task.status_changed_at is not None
            and task.status_changed_at.isoformat() == fact
        )
    if task.due is None or task.due.isoformat() != fact:
        return False  # a due nudge, the only other a task has
    return task.status in tasks_svc.OPEN_STATUSES


def active_nudges(db: Session) -> list[Nudge]:
    """Undismissed nudges whose fact still holds, newest first."""
    nudges = db.scalars(
        select(Nudge)
        .options(selectinload(Nudge.task))
        .where(Nudge.dismissed_at.is_(None))
        .order_by(Nudge.created_at.desc())
    )
    return [
        n for n in nudges
        if (_bill_still_due(db, n) if n.type == NudgeType.bill_due else _still_holds(n))
    ]


def dismiss(db: Session, nudge_id: int, now: datetime | None = None) -> None:
    nudge = db.get(Nudge, nudge_id)
    if nudge is not None and nudge.dismissed_at is None:
        nudge.dismissed_at = now or datetime.now()
        db.flush()


def build_morning_digest(db: Session, now: datetime) -> str:
    """The day's shape in one message: plan, events, dues, review pile."""
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    planned = [t for t in tasks_svc.daily_list(db, today) if t.status in tasks_svc.OPEN_STATUSES]
    events = events_svc.calendar_range(db, day_start, day_end)
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
    if due:
        lines.append(
            "Due soon: "
            + "; ".join(f"{t.title} ({short_date(t.due, today)})" for t in due[:5])
            + "."
        )
    if review:
        lines.append(f"{len(review)} task(s) waiting for review.")
    bills = _bills_due(db, today)
    if bills:
        lines.append(
            "Bills due: "
            + "; ".join(
                f"{b.name} {money_svc.money(b.cents)} ({short_date(d, today)})"
                for d, b in bills[:5]
            )
            + "."
        )
    if len(lines) == 2 and not planned:
        lines.append("A clear day.")
    return "\n".join(lines)
