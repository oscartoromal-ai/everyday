"""Project and workstream domain logic."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PROJECT_COLORS,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    Workstream,
    WorkstreamStatus,
)
from app.services import DomainError


def _check_color(color: int) -> int:
    if not 1 <= color <= PROJECT_COLORS:
        raise DomainError(f"A project's colour is 1 to {PROJECT_COLORS}")
    return color


def next_color(db: Session) -> int:
    """The colour a new project gets: the one fewest open projects have
    (the first of them, on a tie), so projects side by side differ."""
    used = dict(
        db.execute(
            select(Project.color, func.count())
            .where(Project.status != ProjectStatus.done)
            .group_by(Project.color)
        ).all()
    )
    return min(range(1, PROJECT_COLORS + 1), key=lambda c: used.get(c, 0))


def create_project(
    db: Session, *, name: str, notes: str = "", color: int | None = None
) -> Project:
    if not name.strip():
        raise DomainError("Project name must not be empty")
    color = next_color(db) if color is None else _check_color(color)
    project = Project(name=name.strip(), notes=notes, color=color)
    db.add(project)
    db.flush()
    return project


def update_project(
    db: Session,
    project_id: int,
    *,
    name: str | None = None,
    status: ProjectStatus | None = None,
    notes: str | None = None,
    color: int | None = None,
) -> Project:
    project = get_project(db, project_id)
    if name is not None:
        if not name.strip():
            raise DomainError("Project name must not be empty")
        project.name = name.strip()
    if status is not None:
        project.status = status
    if notes is not None:
        project.notes = notes
    if color is not None:
        project.color = _check_color(color)
    db.flush()
    return project


def get_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise DomainError(f"Project {project_id} does not exist")
    return project


def list_projects(db: Session, *, status: ProjectStatus | None = None) -> list[Project]:
    stmt = (
        select(Project)
        .options(selectinload(Project.workstreams))
        .order_by(Project.created_at)
    )
    if status is not None:
        stmt = stmt.where(Project.status == status)
    return list(db.scalars(stmt))


def create_workstream(db: Session, *, project_id: int, name: str) -> Workstream:
    get_project(db, project_id)
    if not name.strip():
        raise DomainError("Workstream name must not be empty")
    workstream = Workstream(project_id=project_id, name=name.strip())
    db.add(workstream)
    db.flush()
    return workstream


def update_workstream(
    db: Session,
    workstream_id: int,
    *,
    name: str | None = None,
    status: WorkstreamStatus | None = None,
) -> Workstream:
    workstream = get_workstream(db, workstream_id)
    if name is not None:
        if not name.strip():
            raise DomainError("Workstream name must not be empty")
        workstream.name = name.strip()
    if status is not None:
        workstream.status = status
    db.flush()
    return workstream


def get_workstream(db: Session, workstream_id: int) -> Workstream:
    workstream = db.get(Workstream, workstream_id)
    if workstream is None:
        raise DomainError(f"Workstream {workstream_id} does not exist")
    return workstream


def delete_workstream(db: Session, workstream_id: int) -> None:
    """A workstream gone: its tasks stay in its project, in none."""
    workstream = get_workstream(db, workstream_id)
    project = workstream.project
    for task in list(workstream.tasks):
        task.workstream_id = None
    db.flush()
    db.delete(workstream)
    db.flush()
    # Its project's list is read again, without it.
    db.expire(project, ["workstreams"])


def workstream_progress(db: Session, workstream_id: int) -> tuple[int, int]:
    """(done, total) over the workstream's attached tasks, cancelled excluded."""
    tasks = list(db.scalars(select(Task).where(Task.workstream_id == workstream_id)))
    counted = [t for t in tasks if t.status != TaskStatus.cancelled]
    done = sum(1 for t in counted if t.status == TaskStatus.done)
    return done, len(counted)
