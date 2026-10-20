"""View-model for Calendar's sheet: the days as rows of a spreadsheet, as
Oscar planned them in Excel (Oscar's call on 2026-10-02). A row a day: its
day, where he stays (an item a column), its plan (the tasks planned for it
or due on it, and his own events), and a column per habit, ticked the days
it was done."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import EventSource, NotebookPage, Task, TaskOwner, TaskStatus
from app.services import events as events_svc
from app.services import habits as habits_svc
from app.services import notebook as notebook_svc
from app.services import tasks as tasks_svc

# Four weeks: the last one, this one, and two to plan.
SHEET_DAYS = 28
HABIT_STATES = {"done": "Done", "skipped": "Skipped", "missed": "Missed"}
# Stay items read as a checkbox, whether they are sorted, as Oscar's Excel
# had its AC column (Oscar's call on 2026-10-03); the rest are their words.
CHECK_ITEMS = ("accommodation",)


def home_start(today: date) -> date:
    """Where the sheet opens: the Monday of last week, so the days just gone
    (their habits) sit above the ones to plan."""
    return today - timedelta(days=today.weekday() + 7)


def _stays(db: Session, first: date, last: date) -> dict[date, dict[str, dict[str, Any]]]:
    """Each day's stay, its items by name (lower case), as its page has it."""
    pages = db.scalars(
        select(NotebookPage).where(NotebookPage.day >= first, NotebookPage.day <= last)
    )
    out: dict[date, dict[str, dict[str, Any]]] = {}
    for page in pages:
        stay = next((b for b in page.blocks if b["kind"] == "stay"), None)
        if stay is not None:
            out[page.day] = {
                i["name"].lower(): i for i in notebook_svc.stay_items(stay["text"])
            }
    return out


def _stay_columns(
    db: Session, first: date, stays: dict[date, dict[str, dict[str, Any]]]
) -> list[str]:
    """The stay's items as columns: those the days shown list, in the order
    first written; with none, those a stay written here would start with."""
    names: dict[str, str] = {}
    for day in sorted(stays):
        for item in stays[day].values():
            names.setdefault(item["name"].lower(), item["name"])
    return list(names.values()) or notebook_svc.last_stay_items(db, first)


def _tasks(
    db: Session, first: date, last: date, today: date
) -> dict[date, list[dict[str, Any]]]:
    """Each day's tasks: Oscar's planned for it (done ones too), then those
    still open due on it, a deadline still open saying so: flagged overdue
    only once it is past, not done, a deadline to come just a deadline, soon
    or not (Oscar's call on 2026-10-20); each by priority, then as written,
    and each in its project's colour."""
    found = db.scalars(
        select(Task)
        .where(
            Task.owner == TaskOwner.oscar,
            Task.status != TaskStatus.cancelled,
            or_(Task.planned_for.between(first, last), Task.due.between(first, last)),
        )
        .options(selectinload(Task.project))
        .order_by(Task.created_at)
    )
    out: dict[date, list[dict[str, Any]]] = {}
    for task in found:
        done = task.status == TaskStatus.done
        entry = {
            "id": task.id, "title": task.title, "done": done, "status": task.status.value,
            "priority": task.priority.value if task.priority else "",
            "priority_label": task.priority.label if task.priority else "",
            "rank": tasks_svc.priority_rank(task),
            "overdue": bool(task.due and task.due < today and not done),
            "project": (
                {"name": task.project.name, "color": task.project.color}
                if task.project else None
            ),
        }
        if task.planned_for and first <= task.planned_for <= last:
            out.setdefault(task.planned_for, []).append(
                {**entry, "due": task.due == task.planned_for and not done, "only_due": False}
            )
        if (
            task.due and first <= task.due <= last and task.due != task.planned_for
            and task.status in tasks_svc.OPEN_STATUSES
        ):
            out.setdefault(task.due, []).append({**entry, "due": True, "only_due": True})
    for entries in out.values():
        # The day's work, then its deadlines; the most pressing first in each.
        entries.sort(key=lambda t: (t["only_due"], t["rank"]))
    return out


def _events(db: Session, first: date, last: date) -> dict[date, list[dict[str, Any]]]:
    """Each day's own events (work meetings stay on the grid): all day first,
    then by time; one over days on each of them."""
    start = datetime.combine(first, time.min)
    end = datetime.combine(last + timedelta(days=1), time.min)
    out: dict[date, list[dict[str, Any]]] = {}
    for event in events_svc.calendar_range(db, start, end):
        if event.source != EventSource.local or event.cancelled:
            continue
        day = max(event.start.date(), first)
        while day <= last and datetime.combine(day, time.min) < event.end:
            own_day = event.start.date() == day
            out.setdefault(day, []).append({
                "id": event.id,
                "title": event.shown_title,
                "time": "" if event.all_day or not own_day else f"{event.start:%H:%M}",
                "sort": (not event.all_day and own_day, event.start if own_day else start),
            })
            day += timedelta(days=1)
    for entries in out.values():
        entries.sort(key=lambda e: e["sort"])
    return out


def day_sheet_ctx(db: Session, first: date, today: date, days: int = SHEET_DAYS) -> dict[str, Any]:
    """The sheet over `days` days from `first`."""
    last = first + timedelta(days=days - 1)
    stays = _stays(db, first, last)
    columns = _stay_columns(db, first, stays)
    tasks = _tasks(db, first, last, today)
    events = _events(db, first, last)
    habits = habits_svc.grid(db, first, days)
    rows = []
    for i in range(days):
        day = first + timedelta(days=i)
        stay = stays.get(day, {})
        rows.append({
            "date": day,
            "iso": day.isoformat(),
            "dow": f"{day:%a}",
            "label": f"{day.day} {day:%b}",
            "is_today": day == today,
            "is_weekend": day.weekday() >= 5,
            "week_start": day.weekday() == 0 and i > 0,
            "stay": [stay.get(name.lower()) for name in columns],
            "tasks": tasks.get(day, []),
            "events": events.get(day, []),
            # What its plan holds: a day with more than one line folds to its first.
            "plan_count": len(tasks.get(day, [])) + len(events.get(day, [])),
            "habits": [
                {**h["checks"][i], "label": HABIT_STATES.get(h["checks"][i]["state"], "")}
                for h in habits
            ],
        })
    return {
        "start": first,
        "days": days,
        "columns": [
            {
                "name": name,
                "label": name[:1].upper() + name[1:],
                "check": name.lower() in CHECK_ITEMS,
            }
            for name in columns
        ],
        "habits": [{"slug": h["slug"], "days": h["days"]} for h in habits],
        "rows": rows,
    }
