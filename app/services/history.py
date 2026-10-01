"""Task history: every change to a task, as the task stood after it, and who
made it.

Recorded from the ORM itself (an after_flush hook on every Session), so no
path that writes tasks can forget it: the UI, the REST API, MCP tools and
background jobs all flush through here. Who is acting is the session's
`info["actor"]` (app.db sets it per entry point), Oscar by default.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import event, insert, inspect, select
from sqlalchemy.orm import Session

from app.models import Project, Task, TaskRevision, Workstream

# What a revision remembers of a task: its plan, not its bookkeeping.
FIELDS = (
    "title",
    "notes",
    "status",
    "owner",
    "project_id",
    "workstream_id",
    "planned_for",
    "due",
    "starts_on",
)

ACTORS = ("oscar", "claude", "system")


def _plain(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value"):  # a StrEnum
        return value.value
    return value


def snapshot(task: Task) -> dict[str, Any]:
    return {name: _plain(getattr(task, name)) for name in FIELDS}


def _changed(task: Task) -> bool:
    state = inspect(task)
    return any(state.attrs[name].history.has_changes() for name in FIELDS)


@event.listens_for(Session, "after_flush")
def _record(session: Session, _flush_context: Any) -> None:
    actor = session.info.get("actor", "oscar")
    now = datetime.now()
    rows = []
    for obj in session.new:
        if isinstance(obj, Task):
            rows.append((obj, "created"))
    for obj in session.dirty:
        if isinstance(obj, Task) and _changed(obj):
            rows.append((obj, "updated"))
    for obj in session.deleted:
        if isinstance(obj, Task):
            rows.append((obj, "deleted"))
    if not rows:
        return
    session.connection().execute(
        insert(TaskRevision),
        [
            {"task_id": task.id, "at": now, "change": change, "actor": actor,
             "snapshot": snapshot(task)}
            for task, change in rows
        ],
    )


def revisions(db: Session, task_id: int) -> list[TaskRevision]:
    """A task's history, oldest first."""
    stmt = (
        select(TaskRevision)
        .where(TaskRevision.task_id == task_id)
        .order_by(TaskRevision.at, TaskRevision.id)
    )
    return list(db.scalars(stmt))


def last_known(db: Session, task_ids: list[int]) -> dict[int, dict[str, Any]]:
    """The last snapshot of each task, deleted ones included."""
    if not task_ids:
        return {}
    stmt = (
        select(TaskRevision)
        .where(TaskRevision.task_id.in_(task_ids))
        .order_by(TaskRevision.at, TaskRevision.id)
    )
    return {r.task_id: r.snapshot for r in db.scalars(stmt)}


def changes(db: Session, task_id: int) -> list[dict[str, Any]]:
    """The history as steps a person can read: when, who, what kind of change,
    and each field that moved, from what to what (project and workstream by
    name). Newest first."""
    names = {
        "project_id": {p.id: p.name for p in db.scalars(select(Project))},
        "workstream_id": {m.id: m.name for m in db.scalars(select(Workstream))},
    }

    def shown(field: str, value: Any) -> Any:
        if field in names and value is not None:
            return names[field].get(value, f"#{value}")
        return value

    out: list[dict[str, Any]] = []
    before: dict[str, Any] | None = None
    for rev in revisions(db, task_id):
        after = rev.snapshot
        fields = []
        if rev.change == "updated" and before is not None:
            fields = [
                {"field": f, "from": shown(f, before.get(f)), "to": shown(f, after.get(f))}
                for f in FIELDS
                if before.get(f) != after.get(f)
            ]
        out.append(
            {"at": rev.at, "actor": rev.actor, "change": rev.change, "fields": fields,
             "snapshot": after}
        )
        before = after
    # The baseline (the task as it stood when history began) is not a step,
    # and nor is a save that moved nothing a person would see.
    return [
        c for c in reversed(out)
        if c["change"] != "baseline" and (c["change"] != "updated" or c["fields"])
    ]
