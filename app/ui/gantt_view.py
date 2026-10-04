"""View-model for a project's Gantt (partials/gantt_sheet.html): its time
as columns, a week or a day each (its scale), and a row per workstream, task
and place to write one, each with its cells as the sheet shows them and its
bar in columns. Bars are drawn to the day in either scale."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.dates import monday, week_label
from app.models import Project, Task, TaskStatus, Workstream, WorkstreamStatus
from app.services import gantt as gantt_svc
from app.ui.views import DUE_SOON_DAYS

WEEK = timedelta(days=7)
SCALES = ("weeks", "days")
# A column's days, and the unit an edit in that scale moves by.
SCALE_DAYS = {"weeks": 7, "days": 1}
SCALE_UNIT = {"weeks": "week", "days": "day"}
# At the least, the sheet shows from the week before this one to this many after.
WEEKS_AHEAD = 19
# And this many weeks past the plan's last, so a bar can be drawn beyond it.
WEEKS_PAST_PLAN = 4
# The frozen columns before the time: the box, Task, Priority, Start, the
# length, Due.
FROZEN = 6
# Columns before today's left in view as the sheet opens, in each scale.
LEAD = {"weeks": 1, "days": 3}
# A task's status as its box names it.
STATUS_LABEL = {
    TaskStatus.todo: "To do",
    TaskStatus.in_progress: "In progress",
    TaskStatus.blocked: "Blocked",
    TaskStatus.needs_review: "Review",
    TaskStatus.done: "Done",
    TaskStatus.cancelled: "Cancelled",
}


def _day_label(value: date, today: date) -> str:
    """'Fri 16 Oct', and its year's last two digits outside this year."""
    label = f"{value:%a} {value.day} {value:%b}"
    return label if value.year == today.year else f"{label} '{value.year % 100:02d}"


def _in_view(today: date, scale: str, fit: int) -> date:
    """The last day in view as the sheet opens, `fit` columns of time wide."""
    days = SCALE_DAYS[scale]
    opens = (monday(today) if scale == "weeks" else today) - timedelta(days=LEAD[scale] * days)
    return opens + timedelta(days=fit * days - 1)


def _week_range(dates: list[date], today: date, scale: str, fit: int) -> tuple[date, int]:
    """The first week shown and how many: this week's neighbourhood and the
    whole plan, with room after it, and at least the view's width from where
    it opens, so the time always fills it. Both scales start on the same week."""
    this = monday(today)
    first = min([this - WEEK, *(monday(d) for d in dates)])
    last = max([this + WEEK * WEEKS_AHEAD, monday(_in_view(today, scale, fit)),
                *(monday(d) + WEEK * WEEKS_PAST_PLAN for d in dates)])
    count = min((last - first).days // 7 + 1, gantt_svc.MAX_WEEKS * 2)
    return first, count


def _columns(first: date, weeks: int, scale: str, today: date) -> list[dict[str, Any]]:
    """The time's columns. A week's head is its ISO week over its Monday's
    day (with the month where it turns, and in the first column; its year
    too where that turns, outside this year, so each fits its column); a
    day's is its weekday's initial and its date, under its week's name on
    Mondays."""
    out = []
    if scale == "weeks":
        this = monday(today)
        for i in range(weeks):
            start = first + WEEK * i
            year, week, _ = start.isocalendar()
            new_month = i == 0 or start.month != (start - WEEK).month
            new_year = i == 0 or year != (start - WEEK).isocalendar()[0]
            out.append({
                "iso": start.isoformat(),
                "top": week_label(start, today) if new_year else f"W{week}",
                "bottom": f"{start.day} {start:%b}" if new_month else str(start.day),
                "new_month": new_month,
                "current": start == this,
                "aria": f"Week {week}"
                        + (f" of {year}" if year != today.isocalendar()[0] else "")
                        + f", from {start.day} {start:%B}"
                        + (", this week" if start == this else ""),
            })
        return out
    for i in range(weeks * 7):
        day = first + timedelta(days=i)
        out.append({
            "iso": day.isoformat(),
            "top": f"{week_label(day, today)} · {day.day} {day:%b}" if day.weekday() == 0 else "",
            "initial": f"{day:%a}"[0],
            "bottom": str(day.day),
            "new_month": day.day == 1,
            "week_start": day.weekday() == 0,
            "weekend": day.weekday() >= 5,
            "current": day == today,
            "aria": f"{day:%A} {day.day} {day:%B}" + (", today" if day == today else ""),
        })
    return out


class _Place:
    """Where days fall on the columns, in columns from the first."""

    def __init__(self, first: date, scale: str) -> None:
        self.first, self.days = first, SCALE_DAYS[scale]

    def at(self, day: date) -> float:
        """A day's start."""
        return round((day - self.first).days / self.days, 4)

    def middle(self, day: date) -> float:
        return round(((day - self.first).days + 0.5) / self.days, 4)

    def span(self, start: date, end: date) -> dict[str, float]:
        """A bar over these days, both included."""
        return {"s": self.at(start), "n": round(((end - start).days + 1) / self.days, 4)}


def _task_row(task: Task, place: _Place, scale: str, today: date, indent: bool) -> dict:
    unit = SCALE_UNIT[scale]
    length = gantt_svc.length_of(task, unit)
    done = task.status == TaskStatus.done
    has_bar = length is not None
    start_label = ""
    if task.starts_on:
        start_label = (
            week_label(task.starts_on, today) if scale == "weeks"
            else _day_label(task.starts_on, today)
        )
    span = (
        f"{_day_label(task.starts_on, today)} to {_day_label(task.due, today)}" if has_bar else ""
    )
    due_label = _day_label(task.due, today) if task.due else ""
    return {
        "kind": "task",
        "key": f"t{task.id}",
        "id": task.id,
        "title": task.title,
        "done": done,
        "indent": indent,
        "status": task.status.value,
        "status_label": STATUS_LABEL[task.status],
        "priority": task.priority.value if task.priority else "",
        "priority_label": task.priority.label if task.priority else "",
        "starts_on": task.starts_on.isoformat() if task.starts_on else "",
        "due": task.due.isoformat() if task.due else "",
        "start_label": start_label,
        "start_title": _day_label(task.starts_on, today) if task.starts_on else "",
        "length": length or "",
        "due_label": due_label,
        "due_soon": bool(
            not done and task.due and task.due <= today + timedelta(days=DUE_SOON_DAYS)
        ),
        "bar": place.span(task.starts_on, task.due) if has_bar else None,
        # A task due with no start: a tick on its due.
        "tick": place.middle(task.due) if task.due and not has_bar else None,
        "describe": ", ".join(
            p for p in (task.title, span, f"due {due_label}" if due_label else "",
                        f"{task.priority.label.lower()} priority"
                        if task.priority else "",
                        STATUS_LABEL[task.status].lower()
                        if task.status != TaskStatus.todo else "") if p
        ),
    }


def _workstream_row(
    workstream: Workstream, tasks: list[Task], place: _Place, scale: str, today: date
) -> dict:
    """A workstream: a lane with no dates of its own. Its Start, length and
    Due are its tasks' (read-only): the first start, the last due, and the
    time between, drawn as a summary over their bars."""
    spans = [(t.starts_on, t.due) for t in tasks if t.starts_on and t.due]
    dues = [t.due for t in tasks if t.due]
    summary = start = None
    length = ""
    if spans:
        start = min(s for s, _ in spans)
        end = max(d for _, d in spans)
        length = (
            (end - start).days + 1 if scale == "days"
            else (monday(end) - monday(start)).days // 7 + 1
        )
        summary = place.span(start, end)
    last_due = max(dues) if dues else None
    done = workstream.status == WorkstreamStatus.done
    start_label = ""
    if start:
        start_label = week_label(start, today) if scale == "weeks" else _day_label(start, today)
    count = len(tasks)
    return {
        "kind": "workstream",
        "key": f"w{workstream.id}",
        "id": workstream.id,
        "title": workstream.name,
        "done": done,
        "status": workstream.status.value,
        "start_label": start_label,
        "length": length,
        "due_label": _day_label(last_due, today) if last_due else "",
        "summary": summary,
        # Folded, its row says what it holds.
        "count_label": f"{count} task" if count == 1 else f"{count} tasks",
        "describe": ", ".join(
            p for p in (f"Workstream {workstream.name}",
                        f"to {_day_label(last_due, today)}" if last_due else "",
                        "done" if done else "") if p
        ),
    }


def gantt_ctx(
    db: Session, project: Project, today: date, scale: str = "weeks", fit: int = 0
) -> dict:
    """The Gantt sheet in its scale, `fit` columns of time in view (as
    gantt.js measured them): its columns, and its groups of rows:
    each workstream's row, its tasks and a row to write one more; then a
    row to write a workstream, the tasks in none under it, and a row to
    write one more of those."""
    scale = scale if scale in SCALES else SCALES[0]
    groups = gantt_svc.groups(db, project, today)
    tasks = [t for g in groups for t in g.tasks]
    dates = [d for t in tasks for d in (t.starts_on, t.due) if d]
    first, weeks = _week_range(dates, today, scale, fit)
    place = _Place(first, scale)
    out = []
    for group in groups:
        m = group.workstream
        rows = []
        if m is not None:
            rows.append(_workstream_row(m, group.tasks, place, scale, today))
        else:
            rows.append({"kind": "add-workstream", "key": "add-workstream",
                         "placeholder": "Add a workstream…"})
        rows += [_task_row(t, place, scale, today, indent=m is not None) for t in group.tasks]
        rows.append({
            "kind": "add",
            "key": f"add-w{m.id}" if m else "add",
            "workstream_id": m.id if m else "",
            "indent": m is not None,
            "placeholder": f"Add a task to {m.name}…" if m else "Add a task…",
        })
        out.append({"key": f"w{m.id}" if m else "other", "workstream_id": m.id if m else "",
                    "rows": rows})
    number = 0
    for group in out:
        for row in group["rows"]:
            number += 1
            row["number"] = number
    spans = [t for t in tasks if t.starts_on]
    this_col = int(place.at(today))
    return {
        "project": project,
        "scale": scale,
        "unit": SCALE_UNIT[scale],
        "columns": _columns(first, weeks, scale, today),
        "first_day": first.isoformat(),
        "column_days": SCALE_DAYS[scale],
        "this_col": this_col,
        "today_iso": today.isoformat(),
        "lead": LEAD[scale],
        # The now-line: the middle of today.
        "now": place.middle(today),
        "groups": out,
        "last_row": number,
        "frozen": FROZEN,
        "length_head": ("Wks", "Weeks") if scale == "weeks" else ("Days", "Days"),
        "task_count": len(tasks),
        "open_count": sum(1 for t in tasks if t.status != TaskStatus.done),
        "plan_span": (
            f"{week_label(min(t.starts_on for t in spans), today)} to "
            f"{week_label(max(t.due for t in spans), today)}"
            if spans else ""
        ),
    }
