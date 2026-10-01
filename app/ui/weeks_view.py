"""View-model for the multi-week planner: several weeks of days at a glance.

Each day carries what planning ahead needs: tasks planned for it, deadlines
landing on it, personal events by name, and the work calendar
condensed to a load figure (meeting count and busy hours), since individual
meetings are the week calendar's job.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    BlockState,
    Event,
    EventSource,
    Task,
    TaskOwner,
    TaskStatus,
)
from app.services import events as events_svc
from app.services import tasks as tasks_svc
from app.ui.calendar_view import week_monday
from app.ui.views import DUE_SOON_DAYS

WEEK_COUNT = 6
LAYOUTS = ("grid", "rows")
# A grid cell shows this many entries before folding the rest into "+N more".
CELL_LIMIT = 5
# Meeting load from which a day's busy figure is inked copper rather than muted.
HEAVY_DAY_HOURS = 4


def _busy_hours(spans: list[tuple[datetime, datetime]]) -> float:
    """Hours covered by the union of spans, so overlapping meetings count once."""
    total = timedelta()
    current_start: datetime | None = None
    current_end: datetime | None = None
    for start, end in sorted(spans):
        if current_end is None or start > current_end:
            if current_end is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        total += current_end - current_start
    return total.total_seconds() / 3600


def hours_label(hours: float) -> str:
    """'45m', '2h', '4.5h'."""
    if hours < 1:
        return f"{round(hours * 60)}m"
    rounded = math.floor(hours * 2 + 0.5) / 2  # half-up to the half hour, not banker's rounding
    return f"{rounded:g}h"


def _event_days(event: Event) -> tuple[date, date]:
    """First and last calendar day an event occupies (all-day ends are exclusive)."""
    last = event.end - timedelta(microseconds=1)
    return event.start.date(), last.date()


def week_title(week_start: date, today: date) -> str:
    this_week = week_monday(today)
    if week_start == this_week:
        return "This week"
    if week_start == this_week + timedelta(days=7):
        return "Next week"
    if week_start == this_week - timedelta(days=7):
        return "Last week"
    return f"Week of {week_start.day} {week_start.strftime('%B')}"


def range_label(first: date, last: date) -> str:
    """'21–27 Sep' or '28 Sep – 4 Oct', with the year only when it changes."""
    if first.month == last.month:
        return f"{first.day}–{last.day} {last.strftime('%b')}"
    year = f" {first.year}" if first.year != last.year else ""
    return f"{first.day} {first.strftime('%b')}{year} – {last.day} {last.strftime('%b')}"


def weeks_ctx(db: Session, anchor: date, today: date) -> dict[str, Any]:
    first_day = week_monday(anchor)
    day_count = WEEK_COUNT * 7
    last_day = first_day + timedelta(days=day_count - 1)
    range_start = datetime.combine(first_day, time.min)
    range_end = datetime.combine(last_day + timedelta(days=1), time.min)

    days: dict[date, dict[str, Any]] = {
        first_day + timedelta(days=i): {
            "tasks": [],
            "dues": [],
            "events": [],
            "all_day": [],
            "work_spans": [],
        }
        for i in range(day_count)
    }

    planned = db.scalars(
        select(Task)
        .options(selectinload(Task.blocks), selectinload(Task.project))
        .where(
            Task.owner == TaskOwner.oscar,
            Task.status != TaskStatus.cancelled,
            Task.planned_for.between(first_day, last_day),
        )
        .order_by(Task.status_changed_at)
    )
    for task in planned:
        days[task.planned_for]["tasks"].append(_task_entry(task, task.planned_for))

    due = db.scalars(
        select(Task)
        .options(selectinload(Task.project))
        .where(
            Task.status.in_(tasks_svc.OPEN_STATUSES),
            Task.due.between(first_day, last_day),
        )
    )
    for task in due:
        if task.planned_for != task.due:  # a task planned on its due day shows once
            days[task.due]["dues"].append(
                {"id": task.id, "title": task.title, "planned_for": task.planned_for}
            )

    events, _ = events_svc.calendar_range(db, range_start, range_end)
    for event in events:
        first, last = _event_days(event)
        day = max(first, first_day)
        while day <= min(last, last_day):
            slot = days[day]
            if event.all_day:
                slot["all_day"].append({"title": event.title, "source": event.source.value})
            elif event.source == EventSource.work:
                day_start = datetime.combine(day, time.min)
                slot["work_spans"].append(
                    (max(event.start, day_start), min(event.end, day_start + timedelta(days=1)))
                )
            else:
                slot["events"].append(
                    {
                        "title": event.title,
                        "time": f"{event.start:%H:%M}" if event.start.date() == day else "",
                    }
                )
            day += timedelta(days=1)

    weeks = []
    for w in range(WEEK_COUNT):
        week_start = first_day + timedelta(days=7 * w)
        week_days = []
        week_meetings = 0
        week_busy = 0.0
        for i in range(7):
            day = week_start + timedelta(days=i)
            slot = days[day]
            busy = _busy_hours(slot["work_spans"])
            meetings = len(slot["work_spans"])
            week_meetings += meetings
            week_busy += busy
            # Fixed points first (all-day, deadlines, events), then the
            # movable plan: that order survives the grid's "+N more" fold.
            entries = (
                [{"kind": "all_day", **e} for e in slot["all_day"]]
                + [{"kind": "due", **d} for d in slot["dues"]]
                + [{"kind": "event", **e} for e in slot["events"]]
                + [{"kind": "task", **t} for t in slot["tasks"]]
            )
            week_days.append(
                {
                    "date": day,
                    "is_today": day == today,
                    "is_past": day < today,
                    "show_month": day == first_day or day.day == 1,
                    "entries": entries,
                    "meetings": meetings,
                    "busy_label": hours_label(busy) if meetings else None,
                    "heavy": busy >= HEAVY_DAY_HOURS,
                    # "+1 more" would take the line the entry itself needs.
                    "overflow": (
                        len(entries) - (CELL_LIMIT - 1) if len(entries) > CELL_LIMIT else 0
                    ),
                }
            )
        weeks.append(
            {
                "start": week_start,
                "title": week_title(week_start, today),
                "range": range_label(week_start, week_start + timedelta(days=6)),
                "days": week_days,
                "meetings": week_meetings,
                "busy_label": hours_label(week_busy) if week_meetings else None,
            }
        )

    span = timedelta(days=7 * WEEK_COUNT)
    return {
        "weeks": weeks,
        "start": first_day,
        "range_label": range_label(first_day, last_day),
        "prev": (first_day - span).isoformat(),
        "next": (first_day + span).isoformat(),
        "is_current": first_day == week_monday(today),
        "cell_limit": CELL_LIMIT,
        "tray": unplanned_tasks(db, today),
    }


def _task_entry(task: Task, day: date) -> dict[str, Any]:
    blocks = [
        b for b in task.blocks if b.start.date() == day and b.state != BlockState.missed
    ]
    first_block = min(blocks, key=lambda b: b.start) if blocks else None
    return {
        "id": task.id,
        "title": task.title,
        "done": task.status == TaskStatus.done,
        "time": f"{first_block.start:%H:%M}" if first_block else "",
        "project": task.project.name if task.project else None,
        "due_today": task.due == day,
    }


def unplanned_tasks(db: Session, today: date) -> list[dict[str, Any]]:
    """Oscar's open tasks with no do-date, deadlines first, then newest."""
    tasks = db.scalars(
        select(Task)
        .options(selectinload(Task.project))
        .where(
            Task.owner == TaskOwner.oscar,
            Task.status.in_(tasks_svc.OPEN_STATUSES),
            Task.planned_for.is_(None),
        )
        .order_by(Task.due.is_(None), Task.due, Task.created_at.desc())
    )
    return [
        {
            "id": task.id,
            "title": task.title,
            "project": task.project,
            "due": task.due,
            "due_soon": bool(task.due and task.due <= today + timedelta(days=DUE_SOON_DAYS)),
        }
        for task in tasks
    ]
