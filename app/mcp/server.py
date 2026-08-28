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
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

mcp = FastMCP(
    "personal-calendar",
    instructions=(
        "Oscar's personal planner: projects, tasks, calendar events, and scheduled "
        "task blocks. The app database is canonical for cross-project plan state. "
        "Dates are calendar dates (YYYY-MM-DD); datetimes are naive local wall time."
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
    with session_scope() as db:
        return [_project_payload(db, p) for p in projects_svc.list_projects(db, status=status)]


@mcp.tool
def upsert_project(
    name: str,
    project_id: int | None = None,
    status: ProjectStatus | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create or update a project. Matches by project_id when given, else by exact
    name; creates when no match exists."""
    with session_scope() as db:
        if project_id is None:
            existing = next(
                (p for p in projects_svc.list_projects(db) if p.name == name.strip()), None
            )
            project_id = existing.id if existing else None
        if project_id is None:
            project = projects_svc.create_project(db, name=name, notes=notes or "")
            if status is not None:
                project = projects_svc.update_project(db, project.id, status=status)
        else:
            project = projects_svc.update_project(
                db, project_id, name=name, status=status, notes=notes
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
    with session_scope() as db:
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
    due is the deadline. owner is oscar or claude."""
    out: list[dict[str, Any]] = []
    with session_scope() as db:
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
    with session_scope() as db:
        return task_out(tasks_svc.set_status(db, task_id, status)).model_dump()


@mcp.tool
def get_agenda(start: date | None = None, days: int = 1) -> dict[str, Any]:
    """The plan for `days` days from `start` (default today): calendar events,
    scheduled task blocks, tasks planned per day, and upcoming dues/milestones."""
    with session_scope() as db:
        first = start or date.today()
        window_start = datetime.combine(first, datetime.min.time())
        window_end = window_start + timedelta(days=days)
        events, blocks = events_svc.calendar_range(db, window_start, window_end)
        view = tasks_svc.next_days(db, first, days=days)
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
                }
                for day, v in view.items()
            },
        }


@mcp.tool
def schedule_block(task_id: int, start: datetime, end: datetime) -> dict[str, Any]:
    """Give a task a calendar block (protected time). Naive local datetimes."""
    with session_scope() as db:
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
    with session_scope() as db:
        return EventOut.model_validate(
            events_svc.create_event(
                db, title=title, start=start, end=end, all_day=all_day, location=location
            )
        ).model_dump()
