"""A task's folder and its files (SPEC.md, Files first): every task has a
folder, `tasks/<id>-<words>/` in its project's folder of the everyday files
(projects/<folder>/tasks/), or in the everyday files' own tasks/ when it is
in no project, the words its title's. It holds task.md (the task itself,
app.services.task_md) and the task's other files, Markdown documents in
folders and subfolders: its plans, research and notes, written on the
task's page or by the agents working it, the master copy.

The folder follows the database (Oscar's call on 2026-10-11): a task moved
to another project, or renamed, has its folder moved there (arrange). It is
found by its id wherever it is meanwhile, so one Windows would not move just
then (a file open in it) still is the task's; a second folder of the same
task (an agent writing to where it was) is merged into it.

A file is named by its path in the folder, "/" between its folders
("research/trees.md"); a path that leaves the folder is refused, and
task.md at the top is the task's own, not one of its files.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from app.models import Task
from app.services import DomainError, documents, everyday

log = logging.getLogger(__name__)

TASK_FILE = documents.TASK_FILE
held = documents.held


class FileChanged(DomainError):
    """A file saved from a copy older than the file: written elsewhere (an
    editor, an agent) since the copy was read. Its version is the file's."""

    def __init__(self, path: str, body: str) -> None:
        super().__init__(f"{path} was changed elsewhere since this copy was read")
        self.version = everyday.version(body)


# ---- where a task's folder is ----


def folder_name(task: Task) -> str:
    return f"{task.id}-{everyday.words(task.title)}"


def home_of(task: Task) -> Path:
    """Where the task's folder belongs: in its project's tasks/, or the
    everyday files' own when it is in no project (or its project has no
    folder yet)."""
    project = task.project
    if project is not None and project.folder:
        return everyday.projects_dir() / project.folder / "tasks" / folder_name(task)
    return everyday.tasks_dir() / folder_name(task)


def _parents() -> list[Path]:
    """Every folder a task's folder may be in: the everyday files' tasks/,
    and each project's."""
    out = [everyday.tasks_dir()]
    projects = everyday.projects_dir()
    if projects.is_dir():
        out += sorted(p / "tasks" for p in projects.iterdir() if p.is_dir())
    return out


def folders_of(task_id: int) -> list[Path]:
    """Every folder the task has, wherever it is (one, but for a moment)."""
    found = []
    for parent in _parents():
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            if child.is_dir() and documents.task_id_of(child.name) == task_id:
                found.append(child)
    return found


def all_folders() -> dict[int, list[Path]]:
    """Every task folder there is, by its task's id."""
    out: dict[int, list[Path]] = {}
    for parent in _parents():
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            task_id = documents.task_id_of(child.name) if child.is_dir() else None
            if task_id is not None:
                out.setdefault(task_id, []).append(child)
    return out


def folder_of(task_id: int) -> Path | None:
    """The task's folder, if it has one: the one holding its task.md, when
    it has two."""
    found = folders_of(task_id)
    return next((f for f in found if (f / TASK_FILE).is_file()), found[0] if found else None)


def arrange(task: Task, found: list[Path] | None = None) -> Path:
    """The task's folder put where it belongs (home_of), made when it has
    none, and any second folder of it merged in. A folder Windows will not
    move stays where it is, to be moved the next time: its path is answered."""
    home = home_of(task)
    found = folders_of(task.id) if found is None else found
    if not found:
        home.mkdir(parents=True, exist_ok=True)
        return home
    main = next((f for f in found if f == home), None)
    if main is None:
        main = next((f for f in found if (f / TASK_FILE).is_file()), found[0])
        try:
            home.parent.mkdir(parents=True, exist_ok=True)
            if home.exists():
                _merge(main, home)
            else:
                main.rename(home)
            log.info("Task %s's folder moved to %s", task.id, home)
            main = home
        except OSError as exc:
            log.warning("Task %s's folder stays at %s for now: %s", task.id, main, exc)
    for other in found:
        if other != main and other.exists():
            try:
                _merge(other, main)
            except OSError as exc:
                log.warning("Task %s's folder %s is merged later: %s", task.id, other, exc)
    return main


def _merge(source: Path, target: Path) -> None:
    """What a folder holds moved into another, then the folder gone: a file
    the other has with other words kept beside it, numbered ("notes (2).md")."""
    for path in sorted(source.rglob("*"), key=lambda p: -len(p.parts)):
        if not path.is_file():
            continue
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if dest.read_bytes() == path.read_bytes():
                path.unlink()
                continue
            n = 2
            while (candidate := dest.with_name(f"{dest.stem} ({n}){dest.suffix}")).exists():
                n += 1
            dest = candidate
        path.replace(dest)
    shutil.rmtree(source)


def trash(task_id: int) -> None:
    """A deleted task's folders moved to the everyday files' .trash/, so
    nothing written there is lost."""
    for folder in folders_of(task_id):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = everyday.trash_dir() / f"{folder.name}-{stamp}"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            folder.rename(dest)
        except OSError as exc:
            log.warning("Task %s's folder %s could not go to the trash: %s", task_id, folder, exc)


# ---- its files ----


def _visible(path: Path) -> bool:
    return not path.name.startswith(".")


def tree(task_id: int) -> list[dict[str, Any]]:
    """What the task's folder holds, but its task.md, level by level: its
    folders by name, then its Markdown files by name, each with its path in
    the folder (a folder with what it holds). Hidden ones (a name starting
    with a dot) are left out."""
    folder = folder_of(task_id)
    if folder is None:
        return []

    def level(here: Path) -> list[dict[str, Any]]:
        entries = sorted((p for p in here.iterdir() if _visible(p)), key=lambda p: p.name.lower())
        folders = [
            {
                "kind": "folder",
                "name": p.name,
                "path": p.relative_to(folder).as_posix(),
                "children": level(p),
            }
            for p in entries
            if p.is_dir()
        ]
        files = [
            {"kind": "file", "name": p.name, "path": p.relative_to(folder).as_posix()}
            for p in entries
            if p.is_file()
            and p.name.lower().endswith(everyday.DOC_SUFFIX)
            and not (here == folder and p.name.lower() == TASK_FILE)
        ]
        return folders + files

    return level(folder)


def paths(task_id: int) -> list[str]:
    """Every file's path, folders first as the tree has them."""
    out: list[str] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if node["kind"] == "folder":
                walk(node["children"])
            else:
                out.append(node["path"])

    walk(tree(task_id))
    return out


def _parts(path: str) -> list[str]:
    """A path's names, each one Windows allows, the last a Markdown file's."""
    pure = PurePosixPath(path.replace("\\", "/").strip().strip("/"))
    names = [part for part in pure.parts if part not in ("", ".")]
    if not names or ".." in names:
        raise DomainError("A file's path stays in its task's folder")
    names = [everyday.folder_file_name(n) for n in names[:-1]] + [
        everyday.doc_file_name(names[-1])
    ]
    if len(names) == 1 and names[0].lower() == TASK_FILE:
        raise DomainError(f"{TASK_FILE} is the task itself: write its description instead")
    return names


def _at(task_id: int, path: str) -> tuple[Path, str]:
    """The file a path names, and the path as written in full."""
    folder = folder_of(task_id)
    if folder is None:
        raise DomainError("The task has no files")
    names = _parts(path)
    target = folder.joinpath(*names)
    if not target.resolve().is_relative_to(folder.resolve()):
        raise DomainError("A file's path stays in its task's folder")
    return target, "/".join(names)


def _place(task_id: int, full: str) -> documents.Place:
    return documents.Place(f"task:{task_id}", full)


def read(task_id: int, path: str) -> tuple[str, str]:
    """A file's words, and its path as written in full."""
    target, full = _at(task_id, path)
    if not target.is_file():
        raise DomainError(f"No file {full}: it may have been deleted")
    return everyday.read_text(target), full


def create(db: Session, task: Task, path: str) -> str:
    """A new, empty file at `path` (".md" added when not written; its
    folders made): its path as written in full."""
    arrange(task)
    target, full = _at(task.id, path)
    if target.exists():
        raise DomainError(f"The task has {full} already")
    everyday.write_text(target, "")
    documents.indexed(db, target, "", _place(task.id, full))
    return full


def write(db: Session, task_id: int, path: str, body: str, base: str | None = None) -> str:
    """A file's words written whole, over the copy of version `base`
    (FileChanged when the file has moved on since): its version now."""
    target, full = _at(task_id, path)
    if not target.is_file():
        raise DomainError(f"No file {full}: it may have been deleted")
    now = everyday.read_text(target)
    if base is not None and everyday.version(now) != base:
        raise FileChanged(full, now)
    body = everyday.plain(body)
    if body != now:
        documents.before_writing(db, _place(task_id, full), target, now)
    everyday.write_text(target, body)
    documents.record(db, _place(task_id, full), body, documents.actor(db))
    documents.indexed(db, target, body, _place(task_id, full))
    return everyday.version(body)


def rename(db: Session, task_id: int, path: str, name: str) -> str:
    """A file given another name in its folder: its path now."""
    target, full = _at(task_id, path)
    if not target.is_file():
        raise DomainError("No such file: it may have been deleted")
    folder = folder_of(task_id)
    assert folder is not None
    new_name = everyday.doc_file_name(name)
    if new_name == target.name:
        return target.relative_to(folder).as_posix()
    moved = target.with_name(new_name)
    if moved.parent == folder and new_name.lower() == TASK_FILE:
        raise DomainError(f"{TASK_FILE} is the task itself")
    # Windows tells names apart without their case: only the case changing is a rename too.
    if moved.exists() and moved.name.lower() != target.name.lower():
        raise DomainError(f"Its folder has {new_name} already")
    target.rename(moved)
    new = moved.relative_to(folder).as_posix()
    documents.moved(db, f"task:{task_id}", full, new)
    documents.unindexed(db, everyday.relative(target))
    documents.indexed(db, moved, place=_place(task_id, new))
    return new


def delete(db: Session, task_id: int, path: str) -> None:
    """A file deleted; the folders it leaves empty go too, up to the task's."""
    target, full = _at(task_id, path)
    folder = folder_of(task_id)
    if not target.is_file():
        raise DomainError(f"No file {full}: it may have been moved or deleted")
    target.unlink()
    documents.unindexed(db, everyday.relative(target))
    here = target.parent
    while here != folder and here.is_dir() and not any(here.iterdir()):
        shutil.rmtree(here)
        here = here.parent
