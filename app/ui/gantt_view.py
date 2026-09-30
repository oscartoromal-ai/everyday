"""View-model for a project's Gantt (partials/gantt_sheet.html): its weeks
as columns, and a row per milestone, task and place to write one, each
with its cells as the sheet shows them and its bar in weeks."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.dates import monday, week_label
from app.models import Milestone, MilestoneStatus, Project, Task, TaskStatus
from app.services import gantt as gantt_svc
from app.ui.views import DUE_SOON_DAYS

WEEK = timedelta(days=7)
# At the least, the sheet shows from the week before this one to this many after.
WEEKS_AHEAD = 19
# And this many weeks past the plan's last, so a bar can be drawn beyond it.
WEEKS_PAST_PLAN = 4
# The frozen columns before the weeks: the box, Task, Start, Wks, Due.
FROZEN = 5


def _due_label(value: date, today: date) -> str:
    """'Fri 16 Oct', and its year's last two digits outside this year."""
    label = f"{value:%a} {value.day} {value:%b}"
    return label if value.year == today.year else f"{label} '{value.year % 100:02d}"


def _at(value: date, first: date) -> float:
    """Where a day falls on the weeks, in weeks from the first: the middle of it."""
    return (value - first).days / 7 + 1 / 14


def _week_range(dates: list[date], today: date) -> tuple[date, int]:
    """The first week shown and how many: this week's neighbourhood and the
    whole plan, with room after it."""
    this = monday(today)
    first = min([this - WEEK, *(monday(d) for d in dates)])
    last = max([this + WEEK * WEEKS_AHEAD, *(monday(d) + WEEK * WEEKS_PAST_PLAN for d in dates)])
    count = min((last - first).days // 7 + 1, gantt_svc.MAX_WEEKS * 2)
    return first, count


def _weeks(first: date, count: int, today: date) -> list[dict[str, Any]]:
    """The week columns: the ISO week, and its Monday's day, with the month
    where it changes (and in the first column)."""
    this = monday(today)
    out = []
    for i in range(count):
        start = first + WEEK * i
        new_month = i == 0 or start.month != (start - WEEK).month
        out.append({
            "iso": start.isoformat(),
            "label": week_label(start, today),
            "day": f"{start.day} {start:%b}" if new_month else str(start.day),
            "new_month": new_month,
            "current": start == this,
            "aria": f"Week {start.isocalendar()[1]}, from {start.day} {start:%B}"
                    + (", this week" if start == this else ""),
        })
    return out


def _task_row(task: Task, first: date, today: date, indent: bool) -> dict[str, Any]:
    weeks = gantt_svc.weeks_of(task)
    done = task.status == TaskStatus.done
    bar = None
    if weeks is not None:
        bar = {"s": (task.starts_on - first).days // 7, "n": weeks}
    span = (
        f"{week_label(task.starts_on, today)} to {week_label(monday(task.due), today)}"
        if weeks else ""
    )
    due_label = _due_label(task.due, today) if task.due else ""
    return {
        "kind": "task",
        "key": f"t{task.id}",
        "id": task.id,
        "title": task.title,
        "done": done,
        "indent": indent,
        "status": task.status.value,
        "starts_on": task.starts_on.isoformat() if task.starts_on else "",
        "due": task.due.isoformat() if task.due else "",
        "start_label": week_label(task.starts_on, today) if task.starts_on else "",
        "weeks": weeks or "",
        "due_label": due_label,
        "due_soon": bool(
            not done and task.due and task.due <= today + timedelta(days=DUE_SOON_DAYS)
        ),
        "bar": bar,
        # A task due with no start week: a tick on its due.
        "tick": _at(task.due, first) if task.due and weeks is None else None,
        "describe": ", ".join(
            p for p in (task.title, span, f"due {due_label}" if due_label else "",
                        "done" if done else "") if p
        ),
    }


def _milestone_row(milestone: Milestone, tasks: list[Task], first: date, today: date) -> dict:
    """A milestone: its diamond on its target, and over its tasks' bars a
    summary from the first's start to the last's end, its Start and Wks
    theirs (read-only)."""
    spans = [(t.starts_on, t.due) for t in tasks if t.starts_on and t.due]
    summary = start = None
    weeks = ""
    if spans:
        start = min(s for s, _ in spans)
        end = monday(max(d for _, d in spans))
        weeks = (end - start).days // 7 + 1
        summary = {"s": (start - first).days // 7, "n": weeks}
    target = milestone.target_date
    reached = milestone.status == MilestoneStatus.reached
    target_label = _due_label(target, today) if target else ""
    return {
        "kind": "milestone",
        "key": f"m{milestone.id}",
        "id": milestone.id,
        "title": milestone.name,
        "reached": reached,
        "status": milestone.status.value,
        "target": target.isoformat() if target else "",
        "start_label": week_label(start, today) if start else "",
        "weeks": weeks,
        "due_label": target_label,
        "due_soon": bool(
            not reached and target and target <= today + timedelta(days=DUE_SOON_DAYS)
        ),
        "summary": summary,
        "diamond": _at(target, first) if target else None,
        "describe": ", ".join(
            p for p in (f"Milestone {milestone.name}",
                        f"target {target_label}" if target else "",
                        "reached" if reached else "") if p
        ),
    }


def gantt_ctx(db: Session, project: Project, today: date) -> dict[str, Any]:
    """The Gantt sheet: its week columns, and its groups of rows: each
    milestone's row, its tasks and a row to write one more; then the other
    tasks (under a heading when there are milestones), and a row to write a
    milestone."""
    groups = gantt_svc.groups(db, project, today)
    tasks = [t for g in groups for t in g.tasks]
    dates = [d for t in tasks for d in (t.starts_on, t.due) if d]
    dates += [g.milestone.target_date for g in groups if g.milestone and g.milestone.target_date]
    first, count = _week_range(dates, today)
    has_milestones = len(groups) > 1
    out = []
    for group in groups:
        m = group.milestone
        rows = []
        if m is not None:
            rows.append(_milestone_row(m, group.tasks, first, today))
        elif has_milestones:
            rows.append({"kind": "heading", "key": "other", "title": "Other tasks"})
        rows += [_task_row(t, first, today, indent=m is not None) for t in group.tasks]
        rows.append({
            "kind": "add",
            "key": f"add-m{m.id}" if m else "add",
            "milestone_id": m.id if m else "",
            "indent": m is not None,
            "placeholder": f"Add a task to {m.name}…" if m else "Add a task…",
        })
        out.append({"key": f"m{m.id}" if m else "other", "rows": rows})
    number = 0
    for group in out:
        for row in group["rows"]:
            number += 1
            row["number"] = number
    spans = [t for t in tasks if t.starts_on]
    this = monday(today)
    return {
        "project": project,
        "weeks": _weeks(first, count, today),
        "first_week": first.isoformat(),
        "this_week": (this - first).days // 7,
        # The now-line: today's place in its week.
        "now": _at(today, first),
        "groups": out,
        "milestone_row": number + 1,
        "frozen": FROZEN,
        "task_count": len(tasks),
        "open_count": sum(1 for t in tasks if t.status != TaskStatus.done),
        "plan_span": (
            f"{week_label(min(t.starts_on for t in spans), today)} to "
            f"{week_label(monday(max(t.due for t in spans)), today)}"
            if spans else ""
        ),
    }
