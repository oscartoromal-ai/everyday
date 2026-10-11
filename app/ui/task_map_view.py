"""View-model for the map at a task page's left (partials/task_map.html,
Oscar's pick B of the prototypes on 2026-10-11): the task's project, its
context (AGENTS.md and the other documents, in their folders), then its
workstreams, each with its open tasks in the Tasks tab's order and the last
two weeks' finished ones folded under them. The task itself is marked
where it stands, its workstream opened. A task in no project has a map of
itself alone."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.models import Project, Task, TaskStatus
from app.services import tasks as tasks_svc
from app.ui.project_view import context_tree
from app.ui.views import DONE_DAYS, _plan_order

CLOSED = {TaskStatus.done, TaskStatus.cancelled}


def _node(task: Task, here: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "claude": task.owner.value == "claude",
        "here": task.id == here.id,
    }


def _lane(key: str, name: str, tasks: list[Task], here: Task, today: date) -> dict[str, Any]:
    """A workstream's (or no workstream's) tasks: the open ones, soonest
    first, then those finished in the last two weeks; the task itself
    always, wherever it stands."""
    since = datetime.combine(today, datetime.min.time()) - timedelta(days=DONE_DAYS)
    open_tasks = sorted(
        tasks_svc.one_per_series([t for t in tasks if t.status not in CLOSED], today),
        key=_plan_order,
    )
    if here in tasks and here.status not in CLOSED and here not in open_tasks:
        open_tasks.append(here)  # an occurrence its series stood in for
    done = sorted(
        (t for t in tasks if t.status in CLOSED and (t.status_changed_at >= since or t is here)),
        key=lambda t: t.status_changed_at,
        reverse=True,
    )
    return {
        "key": key,
        "name": name,
        "open": [_node(t, here) for t in open_tasks],
        "done": [_node(t, here) for t in done],
        "here": here in tasks,
    }


def map_ctx(task: Task, today: date) -> dict[str, Any]:
    project: Project | None = task.project
    if project is None:
        return {"project": None, "here": _node(task, task)}
    tasks = list(project.tasks)
    lanes = [
        _lane(str(w.id), w.name, [t for t in tasks if t.workstream_id == w.id], task, today)
        for w in project.workstreams
    ]
    loose = [t for t in tasks if t.workstream_id is None]
    if any(t.status not in CLOSED for t in loose) or task in loose:
        lanes.append(_lane("none", "No workstream", loose, task, today))
    return {
        "project": project,
        "context": context_tree(project, today),
        "lanes": lanes,
        "here": _node(task, task),
    }
