"""Project and workstream domain logic, and a project's repositories, whose
master copy is its project.toml (app.services.project_files): each change
to them is made there too, after reading in what changed there since, all
of it held (project_files.held) so the watcher never reads it half made.
A project's documents are its folder's files (project_files)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PROJECT_COLORS,
    Project,
    ProjectRepo,
    ProjectStatus,
    Task,
    TaskStatus,
    Workstream,
    WorkstreamStatus,
)
from app.services import DomainError, project_files


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
    last = db.scalar(select(func.max(Project.position)))
    project = Project(
        name=name.strip(), notes=notes, color=color, position=0 if last is None else last + 1
    )
    db.add(project)
    db.flush()
    # Its folder, project.md and AGENTS.md (empty until written) are made as
    # it is committed (app.services.settling).
    return project


def update_project(
    db: Session,
    project_id: int,
    *,
    name: str | None = None,
    status: ProjectStatus | None = None,
    notes: str | None = None,
    color: int | None = None,
    folded: bool | None = None,
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
    if folded is not None:
        project.folded = folded
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
        .order_by(Project.position, Project.created_at)
    )
    if status is not None:
        stmt = stmt.where(Project.status == status)
    return list(db.scalars(stmt))


def reorder_projects(db: Session, project_ids: list[int]) -> None:
    """The projects named, in this order, as dragged in the sidebar. They
    swap the places they held among themselves, so the projects not named
    (the shelved, under the active ones) keep theirs."""
    if len(set(project_ids)) != len(project_ids):
        raise DomainError("A project is named twice")
    projects = {p.id: p for p in db.scalars(select(Project).where(Project.id.in_(project_ids)))}
    missing = [i for i in project_ids if i not in projects]
    if missing:
        raise DomainError(f"No project {missing[0]}")
    places = sorted(p.position for p in projects.values())
    # Places shared (projects made before positions) are spread out first.
    if len(set(places)) != len(places):
        _renumber(db)
        places = sorted(p.position for p in projects.values())
    for project_id, place in zip(project_ids, places, strict=True):
        projects[project_id].position = place
    db.flush()


def _renumber(db: Session) -> None:
    for place, project in enumerate(
        db.scalars(select(Project).order_by(Project.position, Project.created_at, Project.id))
    ):
        project.position = place


def create_workstream(db: Session, *, project_id: int, name: str) -> Workstream:
    project = get_project(db, project_id)
    if not name.strip():
        raise DomainError("Workstream name must not be empty")
    last = db.scalar(
        select(func.max(Workstream.position)).where(Workstream.project_id == project_id)
    )
    workstream = Workstream(
        project_id=project_id, name=name.strip(), position=0 if last is None else last + 1
    )
    db.add(workstream)
    db.flush()
    # Its project's list is read again, with it.
    db.expire(project, ["workstreams"])
    return workstream


def place_workstream(db: Session, workstream_id: int, before_id: int | None) -> None:
    """A workstream moved among its project's: before another of them, or
    last (before_id None). Its project's are numbered again from 0."""
    workstream = get_workstream(db, workstream_id)
    project = workstream.project
    order = [m for m in project.workstreams if m.id != workstream.id]
    before = next((m for m in order if m.id == before_id), None) if before_id else None
    if before_id and before is None:
        raise DomainError(f"Workstream {before_id} is not in {project.name}")
    order.insert(order.index(before) if before else len(order), workstream)
    for position, m in enumerate(order):
        m.position = position
    db.flush()
    db.expire(project, ["workstreams"])


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


# ---- a project's context: its repositories and its documents ----


def repo_name(location: str) -> str:
    """A repository's name, read from where it is: the last part of its path
    or URL, without ".git" ("C:/code/app" and "https://github.com/me/app.git"
    are both "app")."""
    last = location.strip().rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]
    return last.removesuffix(".git") or location.strip()


def add_repo(db: Session, *, project_id: int, location: str) -> ProjectRepo:
    project = get_project(db, project_id)
    with project_files.held(db):
        project_files.sync_project(db, project)
        repo = ProjectRepo(location=_check_location(project, location))
        project.repos.append(repo)
        db.flush()
        project_files.write_manifest(project)
    return repo


def update_repo(db: Session, repo_id: int, *, location: str) -> ProjectRepo:
    repo = get_repo(db, repo_id)
    project = repo.project
    with project_files.held(db):
        project_files.sync_project(db, project)
        if repo not in project.repos:
            raise _repo_gone(repo)
        repo.location = _check_location(project, location, renaming=repo)
        db.flush()
        project_files.write_manifest(project)
    return repo


def delete_repo(db: Session, repo_id: int) -> None:
    repo = get_repo(db, repo_id)
    project = repo.project
    with project_files.held(db):
        project_files.sync_project(db, project)
        if repo in project.repos:
            project.repos.remove(repo)
            db.flush()
            project_files.write_manifest(project)


def _repo_gone(repo: ProjectRepo) -> DomainError:
    return DomainError(
        f"{repo.location} is not in the project's project.toml any more: it was taken out there"
    )


def get_repo(db: Session, repo_id: int) -> ProjectRepo:
    repo = db.get(ProjectRepo, repo_id)
    if repo is None:
        raise DomainError(f"Repository {repo_id} does not exist")
    return repo


def _check_location(
    project: Project, location: str, renaming: ProjectRepo | None = None
) -> str:
    """Where a repository of the project's is: written, and not another of
    its repositories already."""
    location = location.strip()
    if not location:
        raise DomainError("Write where the repository is: a path or a URL")
    if len(location) > 1000:
        raise DomainError("A repository's location is 1000 characters at most")
    if any(r is not renaming and r.location == location for r in project.repos):
        raise DomainError(f"{location} is one of {project.name}'s repositories already")
    return location


def project_context(project: Project) -> dict[str, Any]:
    """What an agent working on the project is given: the project, where its
    code is, and its documents in full, AGENTS.md first, each with its path
    among the context's folders, and the folders themselves."""
    folder = project_files.folder_path(project)
    return {
        "id": project.id,
        "name": project.name,
        "status": project.status.value,
        "notes": project.notes,
        # Where its files are: the master copy, for agents to write.
        "folder": str(folder) if folder else None,
        "repos": [{"name": repo_name(r.location), "location": r.location} for r in project.repos],
        "folders": [f.path for f in project_files.folders_of(project)],
        "docs": [
            {
                "name": d.name,
                "path": d.path,
                "body": d.body,
                "updated_at": d.updated_at.isoformat(timespec="seconds"),
            }
            for d in project_files.docs_of(project)
        ],
    }
