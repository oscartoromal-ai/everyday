"""A project's context as files (SPEC.md, Agent runs): its documents, in
folders and subfolders on disk, and its project.toml, in its folder of the
everyday files' projects/, the master copy; the database's rows a copy of
them, read again from the files.

Read again (sync_all, sync_project) as the app starts, as a project's page or
its context is read, and as the folder changes while the desktop app runs
(watch). Written by the app (app.services.projects) file first.

Every reading and writing holds LOCK and commits before letting it go
(held), so the watcher's session never reads the database between a file
the app wrote and the copy of it, and never applies the app's own change a
second time.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AGENTS_DOC,
    Project,
    ProjectDoc,
    ProjectDocFolder,
    ProjectDocRevision,
    ProjectRepo,
)
from app.services import everyday

log = logging.getLogger(__name__)

LOCK = threading.RLock()

# Edits in a row to one document by the same hand, each within this long of
# the last, are one step of its history (as a task's description is).
WRITING_SPELL = timedelta(minutes=10)

# Who changed a document from outside the app: its file was written.
FILE = "file"


@contextmanager
def held(db: Session) -> Generator[None, None, None]:
    """The files and their copies to oneself: LOCK held, and what was done
    committed before it is let go."""
    with LOCK:
        yield
        db.commit()


def actor(db: Session) -> str:
    """Who the session acts for: oscar (the pages), claude (MCP), system."""
    return db.info.get("actor", "oscar")


def folder_path(project: Project) -> Path | None:
    return everyday.projects_dir() / project.folder if project.folder else None


# ---- a document's history ----


def record(db: Session, doc: ProjectDoc, who: str) -> None:
    """A step in the document's history, its words as they now are; folded
    into the last when that was by the same hand within WRITING_SPELL."""
    now = datetime.now()
    last = (
        db.scalar(
            select(ProjectDocRevision)
            .where(ProjectDocRevision.doc_id == doc.id)
            .order_by(ProjectDocRevision.at.desc(), ProjectDocRevision.id.desc())
            .limit(1)
        )
        if doc.id
        else None
    )
    if last is not None and last.actor == who and now - last.at <= WRITING_SPELL:
        last.body, last.at = doc.body, now
    else:
        doc.revisions.append(ProjectDocRevision(at=now, actor=who, body=doc.body))
    db.flush()


def set_body(db: Session, doc: ProjectDoc, body: str, who: str) -> None:
    if body == doc.body:
        return
    doc.body = body
    doc.updated_at = datetime.now()
    record(db, doc, who)


# ---- written from the app ----


def folder_of(db: Session, project: Project) -> Path:
    """The project's folder, written whole from the database's copy when it
    has none yet (a new project, or one from before the everyday files) or
    when it is gone."""
    path = folder_path(project)
    if path is None:
        taken = {p.name for p in _folders()} | {
            f for f in db.scalars(select(Project.folder).where(Project.folder.is_not(None)))
        }
        project.folder = everyday.folder_name(project.name, taken)
        db.flush()
        path = folder_path(project)
    assert path is not None
    if not path.is_dir():
        _write_whole(db, project, path)
    return path


def _write_whole(db: Session, project: Project, path: Path) -> None:
    """Every folder and document of the project's to disk, and its
    project.toml."""
    path.mkdir(parents=True, exist_ok=True)
    _write_missing(db, project, path)
    write_manifest(project, path)
    log.info("Wrote the context of %s to %s", project.name, path)


def _write_missing(db: Session, project: Project, path: Path) -> None:
    """The project's folders and documents written to disk beside what is
    there already, each level in turn: a folder into the folder of its name
    there (made when missing), a document to a file of its own. A name from
    before they were on disk is made one Windows allows (a document's ending
    in .md: Notes is Notes.md), numbered on when another has it: those
    already a file's name keep theirs first, so no two are ever named alike."""

    def write(parent: ProjectDocFolder | None, here: Path) -> None:
        here.mkdir(parents=True, exist_ok=True)
        on_disk = {p.name.lower() for p in here.iterdir()}
        claimed: set[str] = set()  # by this level's folders and documents
        for doc in (d for d in project.docs if d.folder is parent and d.is_agents):
            claimed.add(doc.name.lower())
            if doc.name.lower() not in on_disk:
                everyday.write_text(here / doc.name, doc.body)
        folders = sorted(
            (f for f in project.doc_folders if f.parent is parent), key=lambda f: f.id or 0
        )
        for folder in folders:
            folder.name = everyday.safe_folder_file_name(folder.name, claimed)
            claimed.add(folder.name.lower())
            write(folder, here / folder.name)
        docs = sorted(
            (d for d in project.docs if d.folder is parent and not d.is_agents),
            key=lambda d: d.id or 0,
        )
        taken = on_disk | claimed
        named = [d for d in docs if everyday.safe_doc_file_name(d.name, taken) == d.name]
        for doc in named + [d for d in docs if d not in named]:
            doc.name = everyday.safe_doc_file_name(doc.name, taken)
            taken.add(doc.name.lower())
            everyday.write_text(here / doc.name, doc.body)

    write(None, path)
    db.flush()


def write_manifest(project: Project, path: Path | None = None) -> None:
    path = path or folder_path(project)
    assert path is not None
    everyday.write_manifest(
        path, everyday.Manifest(id=project.id, repos=[r.location for r in project.repos])
    )


def on_disk(project: Project, path: str) -> Path:
    """Where a path of the project's context ("decisions/0001.md") is on disk."""
    root = folder_path(project)
    assert root is not None
    return root.joinpath(*path.split("/"))


def write_folders(db: Session, project: Project) -> None:
    """Every folder of the project's context made on disk, where missing."""
    folder_of(db, project)
    for folder in project.doc_folders:
        on_disk(project, folder.path).mkdir(parents=True, exist_ok=True)


def write_doc(db: Session, doc: ProjectDoc) -> None:
    folder_of(db, doc.project)
    everyday.write_text(on_disk(doc.project, doc.path), doc.body)


def move(db: Session, project: Project, old: str, new: str) -> None:
    """A document's file, or a folder with everything in it, moved from one
    path of the context to another (renamed, or into another folder)."""
    source, target = on_disk(project, old), on_disk(project, new)
    if not source.exists():
        log.warning("Nothing at %s to move to %s", source, target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)


def remove(project: Project, path: str) -> None:
    """A document's file, or a folder with everything in it, deleted."""
    if folder_path(project) is None:
        return
    target = on_disk(project, path)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink(missing_ok=True)


# ---- read from the files ----


def _folders() -> list[Path]:
    root = everyday.projects_dir()
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name.lower(),
    )


def refresh(db: Session, project: Project) -> None:
    """The project's copy read again from its folder (sync_project), held."""
    with held(db):
        sync_project(db, project)


def sync_project(db: Session, project: Project) -> None:
    """The database's copy of the project's context made its folder's: its
    repositories from project.toml, and its documents from their files, each
    written, added, renamed (a new name for the same words) or deleted as the
    files were. AGENTS.md deleted is written back; so is a folder gone."""
    path = folder_path(project)
    if path is None or not path.is_dir():
        folder_of(db, project)
        return
    _sync_manifest(project, path)
    _sync_docs(db, project, path)
    db.flush()


def _sync_manifest(project: Project, path: Path) -> None:
    try:
        manifest = everyday.read_manifest(path)
    except everyday.UnreadableManifest as exc:
        log.warning("Left as it is, and its repositories as they were: %s", exc)
        return
    if manifest is None or manifest.id != project.id:
        write_manifest(project, path)
        return
    if [r.location for r in project.repos] == manifest.repos:
        return
    # Kept in the file's order, which is the rows' (by id): written again whole.
    project.repos.clear()
    for location in manifest.repos:
        project.repos.append(ProjectRepo(location=location))


def _scan(root: Path) -> tuple[dict[str, str], dict[str, Path]]:
    """What a project's folder holds, as context paths: its folders, however
    deep (by their paths in lower case, as Windows tells them apart: their
    paths as written), and its Markdown files (by the same: the file).
    Hidden ones (a name starting with a dot) are not the context's."""
    dirs: dict[str, str] = {}
    files: dict[str, Path] = {}
    for here, subdirs, names in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if not d.startswith("."))
        base = Path(here).relative_to(root)
        for name in subdirs:
            rel = (base / name).as_posix()
            dirs[rel.lower()] = rel
        for name in names:
            if not name.startswith(".") and name.lower().endswith(everyday.DOC_SUFFIX):
                files[(base / name).as_posix().lower()] = Path(here) / name
    return dirs, files


def _last(path: str) -> str:
    return path.rpartition("/")[2]


def _sync_docs(db: Session, project: Project, path: Path) -> None:
    """The project's folders and documents made its folder's on disk: a
    folder there and not here added; a file written, added, moved (the same
    words at another path) or deleted; a folder gone, gone."""
    dirs, files = _scan(path)
    folders = {f.path.lower(): f for f in project.doc_folders}
    for key in sorted(dirs, key=lambda k: k.count("/")):
        name = _last(dirs[key])
        folder = folders.get(key)
        if folder is None:
            parent_key = key.rpartition("/")[0]
            folder = ProjectDocFolder(name=name, parent=folders.get(parent_key))
            project.doc_folders.append(folder)
            folders[key] = folder
        elif folder.name != name:
            folder.name = name  # renamed in case alone
    db.flush()

    def folder_at(key: str) -> ProjectDocFolder | None:
        return folders.get(key.rpartition("/")[0])

    docs = {d.path.lower(): d for d in project.docs}
    added: dict[str, tuple[str, str]] = {}  # a new file's key: its name, its words
    for key, file in files.items():
        body = everyday.read_text(file)
        doc = docs.get(key)
        if doc is None:
            added[key] = (file.name, body)
            continue
        if doc.name != file.name and not doc.is_agents:
            doc.name = file.name  # renamed in case alone
        set_body(db, doc, body, FILE)
    for key, doc in docs.items():
        if key in files:
            continue
        if doc.is_agents:
            everyday.write_text(path / doc.name, doc.body)
            continue
        moved = next((k for k, (_, body) in added.items() if body == doc.body), None)
        if moved is not None:
            name, _ = added.pop(moved)
            doc.name, doc.folder = name, folder_at(moved)
        else:
            doc.folder = None  # out of its folder's list too
            project.docs.remove(doc)
        db.flush()
    for key, (name, body) in added.items():
        doc = ProjectDoc(name=name, body=body, updated_at=datetime.now())
        doc.folder = folder_at(key)
        project.docs.append(doc)
        db.flush()
        record(db, doc, FILE)
    # Folders gone from disk go, each with its subfolders, as a folder deleted
    # in the app does (what they held went above).
    gone = {key for key in folders if key not in dirs}
    if gone:
        # Each folder's list of its documents read again: one moved out and
        # deleted since a list was read would be cascaded to as it goes.
        for folder in project.doc_folders:
            db.expire(folder, ["docs"])
    for key in gone:
        if key.rpartition("/")[0] in gone:
            continue  # it goes with the folder it is in
        top = folders[key]
        below = [f for k, f in folders.items() if k.startswith(f"{key}/")]
        # Taken out of their lists, they are orphans, and go as such.
        for folder in (top, *below):
            project.doc_folders.remove(folder)
        if top.parent is not None:
            top.parent.children.remove(top)
    db.flush()
    if not any(d.is_agents for d in project.docs):
        project.docs.append(ProjectDoc(name=AGENTS_DOC))
        everyday.write_text(path / AGENTS_DOC, "")


def sync_all(db: Session) -> None:
    """Every project's copy made its folder's, held. A folder is its
    project's by the id in its project.toml, else by the name the database
    keeps for it; a project with neither gets its folder written, and a
    folder no project has is a new project, named after it."""
    with held(db):
        everyday.ensure()
        projects = {p.id: p for p in db.scalars(select(Project))}
        by_id: dict[int, Path] = {}
        others: list[Path] = []  # no project.toml, another project's id, or unreadable
        adoptable: set[Path] = set()  # of those, the ones that may be a new project
        for path in _folders():
            try:
                manifest = everyday.read_manifest(path)
            except everyday.UnreadableManifest as exc:
                log.warning("Its project.toml left as it is: %s", exc)
                others.append(path)
                continue
            if manifest is not None and manifest.id in projects and manifest.id not in by_id:
                by_id[manifest.id] = path
            else:
                others.append(path)
                adoptable.add(path)
        by_name = {p.name.lower(): p for p in others}
        for project in projects.values():
            # A project without a folder yet takes one already named after it.
            name = (project.folder or everyday.folder_name(project.name, set())).lower()
            if project.id in by_id:
                path = by_id[project.id]
            elif name in by_name:
                path = by_name.pop(name)
                adoptable.discard(path)
                if not project.folder:
                    # Its first folder, made by hand: what it has goes in too.
                    _write_missing(db, project, path)
            else:
                project.folder = None  # its folder is gone: written again
                folder_of(db, project)
                continue
            if project.folder != path.name:
                log.info("%s's folder is now %s", project.name, path)
                project.folder = path.name
            sync_project(db, project)
        for path in by_name.values():
            if path in adoptable:
                _adopt(db, path)


def _adopt(db: Session, path: Path) -> Project:
    """A folder no project has: a new project, named after it."""
    from app.services.projects import next_color

    last = db.scalar(select(func.max(Project.position)))
    project = Project(
        name=path.name,
        color=next_color(db),
        position=0 if last is None else last + 1,
        folder=path.name,
    )
    db.add(project)
    db.flush()
    write_manifest(project, path)
    _sync_docs(db, project, path)
    db.flush()
    log.info("A new project from its folder: %s", path)
    return project


# ---- watched while the desktop app runs ----


def run_sync() -> None:
    from app.db import session_scope

    with session_scope("system") as db:
        sync_all(db)


def watch(stop: threading.Event) -> None:
    """The everyday files read in, then read again whenever projects/
    changes, until stop is set. A failure (the drive gone, say) is logged
    and tried again a little later."""
    from watchfiles import watch as watch_files

    while not stop.is_set():
        try:
            run_sync()
            for _changes in watch_files(
                everyday.projects_dir(),
                stop_event=stop,
                debounce=800,
                watch_filter=lambda _change, p: not Path(p).name.startswith("."),
                ignore_permission_denied=True,
            ):
                run_sync()
        except Exception:
            log.exception("Watching the everyday files failed; trying again in a minute")
            stop.wait(60)
