"""Project and milestone domain logic."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Milestone, MilestoneStatus, Project, ProjectStatus, Task, TaskStatus
from app.services import DomainError


def create_project(db: Session, *, name: str, notes: str = "") -> Project:
    if not name.strip():
        raise DomainError("Project name must not be empty")
    project = Project(name=name.strip(), notes=notes)
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
        .options(selectinload(Project.milestones))
        .order_by(Project.created_at)
    )
    if status is not None:
        stmt = stmt.where(Project.status == status)
    return list(db.scalars(stmt))


def create_milestone(
    db: Session,
    *,
    project_id: int,
    name: str,
    target_date: date | None = None,
) -> Milestone:
    get_project(db, project_id)
    if not name.strip():
        raise DomainError("Milestone name must not be empty")
    milestone = Milestone(project_id=project_id, name=name.strip(), target_date=target_date)
    db.add(milestone)
    db.flush()
    return milestone


def update_milestone(
    db: Session,
    milestone_id: int,
    *,
    name: str | None = None,
    target_date: date | None = None,
    clear_target_date: bool = False,
    status: MilestoneStatus | None = None,
) -> Milestone:
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise DomainError(f"Milestone {milestone_id} does not exist")
    if name is not None:
        if not name.strip():
            raise DomainError("Milestone name must not be empty")
        milestone.name = name.strip()
    if clear_target_date:
        milestone.target_date = None
    elif target_date is not None:
        milestone.target_date = target_date
    if status is not None:
        milestone.status = status
    db.flush()
    return milestone


def milestone_progress(db: Session, milestone_id: int) -> tuple[int, int]:
    """(done, total) over the milestone's attached tasks, cancelled excluded."""
    tasks = list(db.scalars(select(Task).where(Task.milestone_id == milestone_id)))
    counted = [t for t in tasks if t.status != TaskStatus.cancelled]
    done = sum(1 for t in counted if t.status == TaskStatus.done)
    return done, len(counted)
