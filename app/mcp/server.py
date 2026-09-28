"""The MCP planner interface (SPEC.md section 6).

Claude reads and writes the plan through these tools. The upsert_* /
update_task_status shapes are also the v2 auto-capture contract, so v2 adds
clients, not surface. Everything is a thin wrapper over the service layer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel

from app.api.schemas import EventOut, MilestoneOut, ProjectOut
from app.api.tasks import task_out
from app.db import session_scope
from app.models import ProjectStatus, TaskOwner, TaskStatus
from app.services import DomainError
from app.services import blocks as blocks_svc
from app.services import events as events_svc
from app.services import habits as habits_svc
from app.services import history as history_svc
from app.services import notebook as notebook_svc
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

mcp = FastMCP(
    "personal-calendar",
    instructions=(
        "Oscar's personal planner: projects, tasks, calendar events, and scheduled "
        "task blocks. The app database is canonical for cross-project plan state. "
        "Dates are calendar dates (YYYY-MM-DD); datetimes are naive local wall time. "
        "A task's notes are its free-form description: lines starting with '- ' are "
        "its sub-tasks ('- [x] ' once done), and other lines are context around them. "
        "Each day has a notebook page Oscar writes in: prose, the tasks he wrote there "
        "(as they stand now), reflections, the habits he checked that day, and where he "
        "stays (a stay: its items, such as place and accommodation, each sorted or not); "
        "read it for context with get_notebook. How consistent he is with each habit: "
        "get_habits. His health context (body, activity, goal, diet, allergies, "
        "weigh-ins, estimated daily energy), for anything about what he eats: "
        "get_health_profile."
    ),
)


def _project_payload(db, project) -> dict[str, Any]:  # noqa: ANN001
    payload = ProjectOut.model_validate(project).model_dump()
    payload["milestones"] = [
        MilestoneOut.model_validate(m).model_dump() | {
            "progress": projects_svc.milestone_progress(db, m.id)
        }
        for m in project.milestones
    ]
    return payload


@mcp.tool
def list_projects(status: ProjectStatus | None = None) -> list[dict[str, Any]]:
    """List projects with their milestones and per-milestone (done, total) progress."""
    with session_scope("claude") as db:
        return [_project_payload(db, p) for p in projects_svc.list_projects(db, status=status)]


@mcp.tool
def upsert_project(
    name: str,
    project_id: int | None = None,
    status: ProjectStatus | None = None,
    notes: str | None = None,
    color: int | None = None,
) -> dict[str, Any]:
    """Create or update a project. Matches by project_id when given, else by exact
    name; creates when no match exists. `color` is 1 to 8, one of the app's hues,
    shown as the flag on the project's tasks; a new project gets the least used."""
    with session_scope("claude") as db:
        if project_id is None:
            existing = next(
                (p for p in projects_svc.list_projects(db) if p.name == name.strip()), None
            )
            project_id = existing.id if existing else None
        if project_id is None:
            project = projects_svc.create_project(db, name=name, notes=notes or "", color=color)
            if status is not None:
                project = projects_svc.update_project(db, project.id, status=status)
        else:
            project = projects_svc.update_project(
                db, project_id, name=name, status=status, notes=notes, color=color
            )
        return _project_payload(db, project)


@mcp.tool
def list_tasks(
    project_id: int | None = None,
    status: TaskStatus | None = None,
    owner: TaskOwner | None = None,
    planned_from: date | None = None,
    planned_to: date | None = None,
) -> list[dict[str, Any]]:
    """List tasks, optionally filtered. Each task carries its blocks and a `missed`
    flag (a scheduled block passed uncompleted and was not replanned)."""
    with session_scope("claude") as db:
        found = tasks_svc.list_tasks(
            db,
            project_id=project_id,
            status=status,
            owner=owner,
            planned_from=planned_from,
            planned_to=planned_to,
        )
        now = datetime.now()
        return [task_out(t, now).model_dump() for t in found]


class TaskUpsert(BaseModel):
    task_id: int | None = None
    title: str | None = None
    notes: str | None = None
    status: TaskStatus | None = None
    owner: TaskOwner | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    planned_for: date | None = None
    due: date | None = None


@mcp.tool
def upsert_tasks(tasks: list[TaskUpsert]) -> list[dict[str, Any]]:
    """Create or update tasks in bulk. Items with task_id update that task; items
    without create a new one (title required). planned_for is the intended do-date;
    due is the deadline. owner is oscar or claude. notes is the description: write
    sub-tasks as '- ' lines (tick one by rewriting it as '- [x] '), keeping context
    lines next to the sub-tasks they explain."""
    out: list[dict[str, Any]] = []
    with session_scope("claude") as db:
        for item in tasks:
            fields = item.model_dump(exclude_unset=True)
            task_id = fields.pop("task_id", None)
            if task_id is None:
                if not fields.get("title"):
                    raise DomainError("A new task needs a title")
                task = tasks_svc.create_task(db, **fields)
            else:
                task = tasks_svc.update_task(db, task_id, **fields)
            out.append(task_out(task).model_dump())
    return out


@mcp.tool
def update_task_status(task_id: int, status: TaskStatus) -> dict[str, Any]:
    """Set a task's lifecycle status (todo, in_progress, blocked, needs_review,
    done, cancelled)."""
    with session_scope("claude") as db:
        return task_out(tasks_svc.set_status(db, task_id, status)).model_dump()


@mcp.tool
def get_agenda(start: date | None = None, days: int = 1) -> dict[str, Any]:
    """The plan for `days` days from `start` (default today): calendar events,
    scheduled task blocks, tasks planned per day, and upcoming dues/milestones."""
    with session_scope("claude") as db:
        first = start or date.today()
        window_start = datetime.combine(first, datetime.min.time())
        window_end = window_start + timedelta(days=days)
        events, blocks = events_svc.calendar_range(db, window_start, window_end)
        view = tasks_svc.next_days(db, first, days=days)
        pages = {
            first + timedelta(days=i): _notebook_payload(db, first + timedelta(days=i), brief=True)
            for i in range(days)
        }
        return {
            "events": [EventOut.model_validate(e).model_dump() for e in events],
            "blocks": [
                {
                    "id": b.id,
                    "task_id": b.task_id,
                    "task_title": b.task.title,
                    "start": b.start,
                    "end": b.end,
                    "state": b.state,
                }
                for b in blocks
            ],
            "days": {
                str(day): {
                    "planned": [task_out(t).model_dump() for t in v["planned"]],
                    "due": [task_out(t).model_dump() for t in v["due"]],
                    "milestones": [
                        MilestoneOut.model_validate(m).model_dump() for m in v["milestones"]
                    ],
                    "notebook": pages[day],
                }
                for day, v in view.items()
            },
        }


def _notebook_payload(db, day: date, *, brief: bool = False) -> list[dict[str, Any]]:  # noqa: ANN001
    """A day's notebook page as blocks: prose and reflections as written, and
    each task as it stands now (brief: its id, title and status only)."""
    out: list[dict[str, Any]] = []
    for block in notebook_svc.blocks_of(db, day):
        if block["kind"] == "habit":
            out.append({"kind": "habit", "habit": block["slug"], "done": block["done"],
                        "note": block["text"].strip()})
        elif block["kind"] == "stay":
            # Where he stays that day: each item (place, accommodation...), sorted or not.
            out.append({"kind": "stay", "text": block["text"],
                        "items": notebook_svc.stay_items(block["text"])})
        elif block["kind"] != "task":
            out.append({"kind": block["kind"], "text": block["text"]})
        elif block["task"] is None:
            out.append({"kind": "task", "task_id": block["id"], "deleted": True,
                        "title": block["last_known"].get("title")})
        elif brief:
            task = block["task"]
            out.append({"kind": "task", "task_id": task.id, "title": task.title,
                        "status": task.status})
        else:
            out.append({"kind": "task", "task": task_out(block["task"]).model_dump()})
    return out


@mcp.tool
def get_notebook(start: date | None = None, days: int = 1) -> dict[str, Any]:
    """Oscar's notebook pages for `days` days from `start` (default today), in
    the order he wrote them: prose ("text"), tasks written there ("task", as
    they stand now; a deleted one keeps its last title) and reflections.
    Read-only: the notebook is Oscar's own writing."""
    with session_scope("claude") as db:
        first = start or date.today()
        return {
            str(first + timedelta(days=i)): _notebook_payload(db, first + timedelta(days=i))
            for i in range(days)
        }


@mcp.tool
def get_habits(start: date | None = None, days: int = 14) -> list[dict[str, Any]]:
    """Oscar's habits over `days` days from `start` (default: the 14 days up to
    today), day by day: "done", "skipped" (written, its box unticked),
    "missed" (one of its days, not written, the day past) or null (not due,
    or today still open), with his note. A habit's `days` are the weekdays it
    is due, Monday 0 to Sunday 6, or "" for any day (never missed).
    Read-only: habits are checked in his notes."""
    with session_scope("claude") as db:
        first = start or date.today() - timedelta(days=days - 1)
        return [
            {**row, "checks": [{**c, "day": c["day"].isoformat()} for c in row["checks"]]}
            for row in habits_svc.grid(db, first, days)
        ]


@mcp.tool
def get_health_profile() -> dict[str, Any]:
    """Oscar's health context (Health > Me), for advice on what he eats: his
    height, birth date and age, sex, activity level, goal and target weight,
    his latest weight and recent weigh-ins (newest first), his dietary
    pattern, allergies and intolerances, foods he avoids, and health notes;
    with his BMI and estimated daily energy to keep his weight (kcal,
    Mifflin-St Jeor times his activity's factor). A field he has not filled
    is null or empty. Read-only: he keeps it himself."""
    from app.services import health as health_svc

    with session_scope("claude") as db:
        me = health_svc.context(db)
        return {
            **me,
            "birth_date": me["birth_date"].isoformat() if me["birth_date"] else None,
            "weighed_on": me["weighed_on"].isoformat() if me["weighed_on"] else None,
            "weights": [{**w, "day": w["day"].isoformat()} for w in me["weights"]],
        }


@mcp.tool
def get_task_history(task_id: int) -> list[dict[str, Any]]:
    """How a task changed, newest first: when, who (oscar, claude or system),
    the kind of change (created, updated, deleted) and, for an update, each
    field that moved from what to what. Works for deleted tasks too."""
    with session_scope("claude") as db:
        return [
            {"at": c["at"], "actor": c["actor"], "change": c["change"], "fields": c["fields"]}
            for c in history_svc.changes(db, task_id)
        ]


@mcp.tool
def schedule_block(task_id: int, start: datetime, end: datetime) -> dict[str, Any]:
    """Give a task a calendar block (protected time). Naive local datetimes."""
    with session_scope("claude") as db:
        block = blocks_svc.schedule_block(db, task_id=task_id, start=start, end=end)
        return {"id": block.id, "task_id": block.task_id, "start": block.start,
                "end": block.end, "state": block.state}


@mcp.tool
def add_event(
    title: str,
    start: datetime,
    end: datetime,
    all_day: bool = False,
    location: str = "",
) -> dict[str, Any]:
    """Create a local calendar event. Work-calendar events are read-only and
    cannot be created or edited."""
    with session_scope("claude") as db:
        return EventOut.model_validate(
            events_svc.create_event(
                db, title=title, start=start, end=end, all_day=all_day, location=location
            )
        ).model_dump()
