"""The planner's files kept as the database has them, and the database as
the files have it (SPEC.md, Files first): words are files, fields and
records are rows.

    task.md      a task: its fields (the database's) as front matter, its
                 description, acceptance criteria and outcome (the file's)
    project.md   a project: its fields as front matter, its about (the file's)
    notebook/    a day's notes, the file's

Settling an entity writes its file from the database, after reading in its
words when the file was written outside the app since (its words' hash is
not the one the database last wrote or read: `file_hash`); the front matter
is then written back as the database has it, so an edit there does not
stand. A task's folder is put where it belongs on the way (app.services.
task_files.arrange).

After every commit, the tasks, projects and pages it touched are settled
in a session of their own (the hooks below); the app settles everything as
it starts (settle_all), and a watcher reads in what changes outside it
(sync, watch). Each holds LOCK throughout, and takes it before touching the
database, so the two never interleave, and never wait on each other.
"""

from __future__ import annotations

import copy
import logging
import threading
import uuid
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.models import (
    NotebookPage,
    Project,
    ProjectRepo,
    Setting,
    Task,
    TaskPullRequest,
    TaskRepo,
    Workstream,
)
from app.services import (
    documents,
    everyday,
    notebook_md,
    project_md,
    readme,
    task_files,
    task_md,
)

log = logging.getLogger(__name__)

LOCK = documents.LOCK

# The hand history names for words read in from a file written outside the app.
FILE = documents.FILE

# Settling may be turned off (a script with a database of its own).
enabled = True

# The database this everyday files' folder is, by an id kept on both sides:
# a database copied from another machine, or a folder another database wrote,
# starts again from the database's side rather than read in words that were
# never its own.
CLAIM_SETTING = "everyday_claim"
CLAIM_FILE = ".planner-id"


# ---- where the files are ----


def page_path(day: date) -> Path:
    return everyday.notebook_dir() / f"{day.year}" / f"{day.isoformat()}.md"


def page_name(day: date) -> str:
    return f"{day.year}/{day.isoformat()}.md"


def day_of(name: str) -> date | None:
    """The day a notebook file is, by its name: 2026/2026-10-11.md."""
    stem = name.rpartition("/")[2].removesuffix(everyday.DOC_SUFFIX)
    try:
        return date.fromisoformat(stem)
    except ValueError:
        return None


def _read(path: Path) -> str | None:
    try:
        return everyday.read_text(path)
    except FileNotFoundError:
        return None


def _write(db: Session, path: Path, text: str, current: str | None, place: documents.Place,
           who: str) -> str:
    """The file written when its words are not `text` already, indexed, and
    its history told (but a task.md's, whose history is the task's). Answers
    its version."""
    if text != current:
        everyday.write_text(path, text)
        if not place.is_task_file:
            documents.record(db, place, text, who)
    documents.indexed(db, path, text, place)
    return everyday.version(text)


def _outside(current: str | None, file_hash: str | None) -> bool:
    """The file was written outside the app since it last wrote or read it."""
    return current is not None and file_hash is not None and everyday.version(current) != file_hash


def _kept_before(db: Session, place: documents.Place, current: str | None) -> None:
    """A file the database never wrote nor read (another database's, or one
    from before the files) about to be written over: its words kept in its
    history first."""
    if current is not None and current.strip():
        documents.record(db, place, current, FILE)


# ---- a task ----


def settle_task(db: Session, task: Task, found: list[Path] | None = None,
                who: str | None = None) -> None:
    """The task's folder where it belongs, and its task.md as the database
    has it, its words read in first when the file was written outside the
    app since."""
    folder = task_files.arrange(task, found)
    path = folder / documents.TASK_FILE
    place = documents.Place(f"task:{task.id}", documents.TASK_FILE)
    current = _read(path)
    if _outside(current, task.file_hash):
        _take_task_words(db, task, current)
    elif current is not None and task.file_hash is None:
        _kept_before(db, place, current)
    task.file_hash = _write(db, path, task_md.render(task), current, place, who or FILE)
    db.flush()


def _take_task_words(db: Session, task: Task, text: str) -> None:
    """A task's words as its file has them, written to the task by the
    file's hand (its history says so)."""
    from app.services import tasks as tasks_svc

    words = task_md.parse(text)
    changes: dict[str, Any] = {}
    if words.notes != task.notes.strip():
        changes["notes"] = words.notes
    if words.acceptance != task.acceptance.strip():
        changes["acceptance"] = words.acceptance
    if words.outcome != task.outcome.strip():
        changes["outcome"] = words.outcome
    if changes:
        with _acting(db, FILE):
            tasks_svc.update_task(db, task.id, **changes)
            db.flush()
        log.info("Task %s's %s read in from its file", task.id, ", ".join(changes))


def trash_task(task_id: int) -> None:
    task_files.trash(task_id)


def adopt_task(db: Session, folder: Path) -> Task | None:
    """A folder holding a task.md and no task the database has: a new task,
    its title the front matter's or the folder's name, its project the one
    whose folder it is in, the other fields its front matter gives, its
    words the file's. Its folder then takes its id."""
    from app.services import tasks as tasks_svc

    text = _read(folder / documents.TASK_FILE)
    if text is None:
        return None
    words = task_md.parse(text)
    fields = task_md.new_task_fields(words.front)
    fields.setdefault("title", _title_of_folder(folder.name))
    project_id = None
    if folder.parent.name == "tasks" and folder.parent.parent.parent == everyday.projects_dir():
        project_id = documents.project_folders(db).get(folder.parent.parent.name.lower())
    with _acting(db, FILE):
        task = tasks_svc.create_task(
            db, notes=words.notes, acceptance=words.acceptance, project_id=project_id, **fields
        )
        if words.outcome:
            task.outcome = words.outcome
        db.flush()
    log.info("A new task from its folder: %s is task %s", folder, task.id)
    settle_task(db, task, [folder])
    return task


def _title_of_folder(name: str) -> str:
    """A folder's name as a title: "fix-the-feed" is "Fix the feed"."""
    words = " ".join(name.replace("-", " ").replace("_", " ").split())
    return (words[:1].upper() + words[1:]) or "New task"


# ---- a project ----


def settle_project(db: Session, project: Project, who: str | None = None) -> None:
    """The project's folder where it belongs, and its project.md as the
    database has it, its about read in first when the file was written
    outside the app since."""
    from app.services import project_files

    folder = project_files.folder_of(db, project)
    path = folder / documents.PROJECT_FILE
    place = documents.Place(f"project:{project.id}", documents.PROJECT_FILE)
    current = _read(path)
    if _outside(current, project.file_hash):
        notes = project_md.parse(current or "")
        if notes != project.notes.strip():
            project.notes = notes
            log.info("%s's about read in from its file", project.name)
    elif current is not None and project.file_hash is None:
        if project_md.parse(current) and not project.notes.strip():
            # A project.md written before the database kept one: its about is the file's.
            project.notes = project_md.parse(current)
        else:
            _kept_before(db, place, current)
    project.file_hash = _write(db, path, project_md.render(project), current, place, who or FILE)
    db.flush()


# ---- a day's notes ----


def settle_page(db: Session, day: date, who: str | None = None) -> None:
    """The day's file as its page has it, the file read in first when it
    was written outside the app since (or when the day has no page yet: a
    file written for it is its first)."""
    from app.services import notebook

    page = notebook.get_page(db, day)
    path = page_path(day)
    place = documents.Place("notebook", page_name(day))
    current = _read(path)
    if page is None:
        if current is None or not current.strip():
            return
        page = notebook.store_from_file(db, day, notebook_md.parse(current))
        page.file_hash = everyday.version(current)
        documents.indexed(db, path, current, place)
        db.flush()
        return
    if _outside(current, page.file_hash):
        notebook.store_from_file(db, day, notebook_md.parse(current or ""))
        log.info("The notes of %s read in from their file", day)
    elif current is not None and page.file_hash is None:
        _kept_before(db, place, current)
    text = notebook_md.blocks_text(db, page.blocks)
    if not text and current is None:
        return
    page.file_hash = _write(db, path, text, current, place, who or FILE)
    db.flush()


# ---- after every commit ----


def _touched(session: Session) -> dict[str, set[Any]]:
    return session.info.setdefault(
        "settle", {"tasks": set(), "deleted": set(), "projects": set(), "renamed": set(),
                   "workstreams": set(), "pages": set()}
    )


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _flush_context: Any) -> None:
    if session.info.get("settling") or not enabled:
        return
    touched = _touched(session)
    for obj in [*session.new, *session.dirty]:
        if isinstance(obj, Task):
            touched["tasks"].add(obj.id)
        elif isinstance(obj, (TaskPullRequest, TaskRepo)):
            touched["tasks"].add(obj.task_id)
        elif isinstance(obj, Project):
            touched["projects"].add(obj.id)
            # Its name is in its tasks' files, and its folder in their paths.
            if obj in session.new or _changed(obj, "name", "folder"):
                touched["renamed"].add(obj.id)
        elif isinstance(obj, ProjectRepo):
            touched["projects"].add(obj.project_id)
        elif isinstance(obj, Workstream):
            touched["projects"].add(obj.project_id)
            if obj in session.new or _changed(obj, "name"):
                touched["workstreams"].add(obj.id)
        elif isinstance(obj, NotebookPage):
            touched["pages"].add(obj.day)
    for obj in session.deleted:
        if isinstance(obj, Task):
            touched["deleted"].add(obj.id)
        elif isinstance(obj, (TaskPullRequest, TaskRepo)):
            touched["tasks"].add(obj.task_id)
        elif isinstance(obj, (Workstream, ProjectRepo)):
            touched["projects"].add(obj.project_id)


def _changed(obj: Any, *names: str) -> bool:
    """Any of the named attributes changed in this flush."""
    state = inspect(obj)
    return any(state.attrs[n].history.has_changes() for n in names)


@event.listens_for(Session, "after_commit")
def _settle_committed(session: Session) -> None:
    touched = session.info.pop("settle", None)
    if not touched or not any(touched.values()) or session.info.get("settling"):
        return
    who = session.info.get("actor", "oscar")
    try:
        settled = settle(session.get_bind(), touched, who)
    except Exception:
        log.exception("Writing the files of a change failed; they are put right as the app starts")
        return
    # What settling wrote (a folder, a file's hash, words read in) known to
    # the session that committed, should it go on, without asking the
    # database (a committed session may not) nor counting as a change.
    for key, obj in list(session.identity_map.items()):
        values = settled.get((key[0], key[1][0]))
        if values:
            for name, value in values.items():
                set_committed_value(obj, name, value)


@event.listens_for(Session, "after_rollback")
def _forget(session: Session) -> None:
    session.info.pop("settle", None)


def settle(
    bind: Any, touched: dict[str, set[Any]], who: str
) -> dict[tuple[type, Any], dict[str, Any]]:
    """What a commit touched settled, in a session of its own. Answers each
    task, project and page settled (by its model and id) with its columns as
    they now are."""
    with LOCK, _session(bind) as db:
        for project_id in sorted(touched["projects"]):
            project = db.get(Project, project_id)
            if project is not None:
                settle_project(db, project, who)
        task_ids = set(touched["tasks"]) - set(touched["deleted"])
        if touched["workstreams"]:
            task_ids |= set(
                db.scalars(select(Task.id).where(Task.workstream_id.in_(touched["workstreams"])))
            )
        if touched["renamed"]:
            # Their name and folder are in their tasks' files and paths.
            task_ids |= set(
                db.scalars(select(Task.id).where(Task.project_id.in_(touched["renamed"])))
            )
        for task_id in sorted(task_ids):
            task = db.get(Task, task_id)
            if task is not None:
                settle_task(db, task, who=who)
        for task_id in sorted(touched["deleted"]):
            if db.get(Task, task_id) is None:
                documents.forget_owner(db, f"task:{task_id}")
                trash_task(task_id)
        for day in sorted(touched["pages"]):
            settle_page(db, day, who)
        db.flush()
        return {
            (type(obj), obj.id): {
                c.key: copy.deepcopy(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs
            }
            for obj in db.identity_map.values()
            if isinstance(obj, (Task, Project, NotebookPage))
        }


class _session:
    """A session of settling's own: its changes are not settled again."""

    def __init__(self, bind: Any) -> None:
        self.db = Session(bind=bind, expire_on_commit=False)
        self.db.info["settling"] = True
        self.db.info["actor"] = FILE

    def __enter__(self) -> Session:
        return self.db

    def __exit__(self, kind: Any, *_: Any) -> None:
        try:
            if kind is None:
                self.db.commit()
            else:
                self.db.rollback()
        finally:
            self.db.close()


class _acting:
    """The session acting for another hand a while (history names it)."""

    def __init__(self, db: Session, who: str) -> None:
        self.db, self.who = db, who

    def __enter__(self) -> None:
        self.before = self.db.info.get("actor")
        self.db.info["actor"] = self.who

    def __exit__(self, *_: Any) -> None:
        self.db.info["actor"] = self.before


# ---- everything ----


def _claim(db: Session) -> bool:
    """The everyday files claimed for this database: True when they were
    already its own. When not, every file_hash is forgotten, so the files
    are written from the database rather than read in."""
    setting = db.get(Setting, CLAIM_SETTING)
    mine = setting.value if setting else None
    path = everyday.root() / CLAIM_FILE
    theirs = _read(path)
    theirs = theirs.strip() if theirs else None
    if mine and theirs == mine:
        return True
    if not mine:
        mine = uuid.uuid4().hex
        db.add(Setting(key=CLAIM_SETTING, value=mine))
    if theirs is not None or db.scalar(select(Task.id).where(Task.file_hash.is_not(None))):
        log.info("The everyday files at %s are this database's from now on", everyday.root())
    for model in (Task, Project, NotebookPage):
        for row in db.scalars(select(model).where(model.file_hash.is_not(None))):
            row.file_hash = None
    everyday.write_text(path, mine + "\n")
    db.flush()
    return False


def settle_all(db: Session) -> None:
    """Every project, task and day settled, as the app starts: their files
    written from the database (their words read in first where written
    outside the app), every task's folder where it belongs, a folder made
    by hand a new project or task, the index read again, and README.md."""
    from app.services import project_files

    with LOCK:
        everyday.ensure()
        claimed = _claim(db)
        if not claimed:
            documents.clear(db)
        project_files.sync_all(db)
        projects = list(db.scalars(select(Project)))
        for project in projects:
            settle_project(db, project)
        # Again, for folders named after each other's projects, swapped: the
        # first of them took a numbered name while its own was taken.
        for project in projects:
            project_files.folder_of(db, project)
        _settle_tasks(db, everything=True, adopt=claimed)
        days = set(db.scalars(select(NotebookPage.day))) | set(_days_on_disk())
        for day in sorted(days):
            settle_page(db, day)
        _rescan(db)
        readme.write()
        db.commit()


def sync(db: Session) -> None:
    """What changed outside the app read in (the watcher's): projects'
    folders and project.toml, every file written since it was last read,
    a task or page whose file is gone written again, and a folder made by
    hand a new task."""
    from app.services import project_files

    with LOCK:
        everyday.ensure()
        project_files.sync_all(db)
        _rescan(db)
        _settle_tasks(db, everything=False, adopt=True)
        for page in db.scalars(select(NotebookPage)):
            if page.file_hash is not None and not page_path(page.day).is_file():
                settle_page(db, page.day)
        for project in db.scalars(select(Project)):
            folder = project_files.folder_path(project)
            if folder is None or not (folder / documents.PROJECT_FILE).is_file():
                settle_project(db, project)
        db.commit()


def _days_on_disk() -> Iterable[date]:
    root = everyday.notebook_dir()
    if not root.is_dir():
        return []
    return [d for p in root.glob("*/*.md") if (d := day_of(p.name)) is not None]


def _settle_tasks(db: Session, *, everything: bool, adopt: bool) -> None:
    """Every task's folder and task.md where they belong (all of them settled
    when `everything`, else those whose folder or task.md is missing or out
    of place); a folder no task has with a task.md in it, a new task (when
    `adopt`: not while the folder is another database's being taken over);
    one without, or of a task deleted, to the trash."""
    folders = task_files.all_folders()
    ids = set()
    for task in db.scalars(select(Task)):
        ids.add(task.id)
        found = folders.get(task.id, [])
        if (
            everything
            or len(found) != 1
            or found[0] != task_files.home_of(task)
            or not (found[0] / documents.TASK_FILE).is_file()
        ):
            settle_task(db, task, found)
    for task_id, found in folders.items():
        if task_id in ids:
            continue
        for folder in found:
            if adopt and (folder / documents.TASK_FILE).is_file() and not _was_task(db, task_id):
                adopt_task(db, folder)
            else:
                # A task deleted while the app was not watching: its folder to the trash.
                task_files.trash(task_id)
    for folder in _unnumbered_task_folders():
        adopt_task(db, folder)


def _was_task(db: Session, task_id: int) -> bool:
    """The id was a task's once (it was deleted)."""
    from app.models import TaskRevision

    return db.scalar(select(TaskRevision.id).where(TaskRevision.task_id == task_id).limit(1)) \
        is not None


def _unnumbered_task_folders() -> list[Path]:
    """Folders made by hand in a tasks/ folder, a task.md in them and no id
    in their name: new tasks."""
    out = []
    for parent in task_files._parents():
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and documents.task_id_of(child.name) is None
                and (child / documents.TASK_FILE).is_file()
            ):
                out.append(child)
    return out


def _rescan(db: Session) -> None:
    """The index read again from the files, and the planner's files among
    those written since read in."""
    for place, _path, _body in documents.rescan(db):
        if place.owner.startswith("task:") and place.name == documents.TASK_FILE:
            task = db.get(Task, int(place.owner.split(":")[1]))
            if task is not None:
                settle_task(db, task)
        elif place.owner.startswith("project:") and place.name == documents.PROJECT_FILE:
            project = db.get(Project, int(place.owner.split(":")[1]))
            if project is not None:
                settle_project(db, project)
        elif place.owner == "notebook" and (day := day_of(place.name)) is not None:
            settle_page(db, day)


# ---- watched while the desktop app runs ----


def run_settle_all() -> None:
    from app.db import session_scope

    with session_scope(FILE) as db:
        db.info["settling"] = True
        settle_all(db)


def run_sync() -> None:
    from app.db import session_scope

    with session_scope(FILE) as db:
        db.info["settling"] = True
        sync(db)


def _watched(_change: Any, path: str) -> bool:
    """A change the watcher reads in: in projects/, tasks/ or notebook/, not
    a hidden file (the app's own temporary files among them)."""
    rel = Path(path)
    try:
        parts = rel.relative_to(everyday.root()).parts
    except ValueError:
        return False
    return bool(parts) and parts[0] in documents.INDEXED and not any(
        p.startswith(".") for p in parts
    )


def watch(stop: threading.Event) -> None:
    """Everything settled, then what changes outside the app read in a
    moment after it does, until stop is set. A failure (the drive gone, say)
    is logged and tried again a little later."""
    from watchfiles import watch as watch_files

    settled = False
    while not stop.is_set():
        try:
            if not settled:
                run_settle_all()
                settled = True
            else:
                run_sync()
            for _changes in watch_files(
                everyday.root(),
                stop_event=stop,
                debounce=800,
                watch_filter=_watched,
                ignore_permission_denied=True,
            ):
                run_sync()
        except Exception:
            log.exception("Watching the everyday files failed; trying again in a minute")
            stop.wait(60)
