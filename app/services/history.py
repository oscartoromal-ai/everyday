"""Task history: every change to a task, as the task stood after it, and who
made it.

Recorded from the ORM itself (an after_flush hook on every Session), so no
path that writes tasks can forget it: the UI, the REST API, MCP tools and
background jobs all flush through here. Who is acting is the session's
`info["actor"]` (app.db sets it per entry point), Oscar by default.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import event, insert, inspect, select, update
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
    "estimate_minutes",
)

ACTORS = ("oscar", "claude", "system")

# A description written over a while (a task's page saves as it is written)
# is one step: edits to it alone by the same hand, each within this long of
# the last, fold into the step they continue.
WRITING_SPELL = timedelta(minutes=10)


def _plain(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value"):  # a StrEnum
        return value.value
    return value


def snapshot(task: Task) -> dict[str, Any]:
    return {name: _plain(getattr(task, name)) for name in FIELDS}


def _moved(task: Task) -> set[str]:
    state = inspect(task)
    return {name for name in FIELDS if state.attrs[name].history.has_changes()}


def _apart_from_notes(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """The two snapshots differ in the description, if at all."""
    return all(a.get(f) == b.get(f) for f in FIELDS if f != "notes")


def _continues(session: Session, task: Task, actor: str, now: datetime) -> bool:
    """A description edit folded into the step it continues: the task's last,
    by the same hand within WRITING_SPELL, itself an edit to the description
    alone. True when it was."""
    last_two = session.connection().execute(
        select(TaskRevision.id, TaskRevision.at, TaskRevision.change,
               TaskRevision.actor, TaskRevision.snapshot)
        .where(TaskRevision.task_id == task.id)
        .order_by(TaskRevision.at.desc(), TaskRevision.id.desc())
        .limit(2)
    ).all()
    if len(last_two) < 2:
        return False
    last, before = last_two
    after = snapshot(task)
    if not (
        last.change == "updated" and last.actor == actor and now - last.at <= WRITING_SPELL
        and _apart_from_notes(last.snapshot, after)
        and _apart_from_notes(before.snapshot, last.snapshot)
    ):
        return False
    session.connection().execute(
        update(TaskRevision).where(TaskRevision.id == last.id).values(at=now, snapshot=after)
    )
    return True


@event.listens_for(Session, "after_flush")
def _record(session: Session, _flush_context: Any) -> None:
    actor = session.info.get("actor", "oscar")
    now = datetime.now()
    rows = []
    for obj in session.new:
        if isinstance(obj, Task):
            rows.append((obj, "created"))
    for obj in session.dirty:
        if not isinstance(obj, Task):
            continue
        moved = _moved(obj)
        if moved == {"notes"} and _continues(session, obj, actor, now):
            continue
        if moved:
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
