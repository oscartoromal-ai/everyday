"""A task's files (Oscar's call on 2026-10-11: a task is Markdown, and may
spawn several files): a folder of the everyday files' tasks/ for each task
that has any, named by its id and the words of its title when the folder was
made ("tasks/66-changes-inside-task-screen"), holding Markdown documents in
folders and subfolders. Oscar writes them on the task's page, and the agents
working the task write them where they are; the files are the master copy,
and nothing of them is in the database. The task's description stays its
own, in the database, its files beside it.

A task's folder is found by its id alone, so it stays where it is as the
task is renamed or moves to another project or workstream. A file is named
by its path in the folder, "/" between its folders ("research/trees.md");
a path that leaves the folder is refused.
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from app.models import Task
from app.services import DomainError, everyday


class FileChanged(DomainError):
    """A file saved from a copy older than the file: written elsewhere (an
    editor, an agent) since the copy was read. Its version is the file's."""

    def __init__(self, path: str, body: str) -> None:
        super().__init__(f"{path} was changed elsewhere since this copy was read")
        self.version = everyday.version(body)


def folder_of(task_id: int) -> Path | None:
    """The task's folder, if it has one."""
    root = everyday.tasks_dir()
    if not root.is_dir():
        return None
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child.name == str(task_id) or child.name.startswith(f"{task_id}-")):
            return child
    return None


def folder_for(task: Task) -> Path:
    """The task's folder, made when it has none."""
    found = folder_of(task.id)
    if found is not None:
        return found
    folder = everyday.tasks_dir() / f"{task.id}-{everyday.words(task.title)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _visible(path: Path) -> bool:
    return not path.name.startswith(".")


def tree(task_id: int) -> list[dict[str, Any]]:
    """What the task's folder holds, level by level: its folders by name,
    then its Markdown files by name, each with its path in the folder (a
    folder with what it holds). Hidden ones (a name starting with a dot)
    are left out."""
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
            if p.is_file() and p.name.lower().endswith(everyday.DOC_SUFFIX)
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
    return [everyday.folder_file_name(n) for n in names[:-1]] + [
        everyday.doc_file_name(names[-1])
    ]


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


def read(task_id: int, path: str) -> tuple[str, str]:
    """A file's words, and its path as written in full."""
    target, full = _at(task_id, path)
    if not target.is_file():
        raise DomainError(f"No file {full}: it may have been deleted")
    return everyday.read_text(target), full


def create(task: Task, path: str) -> str:
    """A new, empty file at `path` (".md" added when not written; its
    folders made): its path as written in full."""
    folder_for(task)
    target, full = _at(task.id, path)
    if target.exists():
        raise DomainError(f"The task has {full} already")
    everyday.write_text(target, "")
    return full


def write(task_id: int, path: str, body: str, base: str | None = None) -> str:
    """A file's words written whole, over the copy of version `base`
    (FileChanged when the file has moved on since): its version now."""
    target, full = _at(task_id, path)
    if not target.is_file():
        raise DomainError(f"No file {full}: it may have been deleted")
    if base is not None:
        now = everyday.read_text(target)
        if everyday.version(now) != base:
            raise FileChanged(full, now)
    body = everyday.plain(body)
    everyday.write_text(target, body)
    return everyday.version(body)


def rename(task_id: int, path: str, name: str) -> str:
    """A file given another name in its folder: its path now."""
    target, _ = _at(task_id, path)
    if not target.is_file():
        raise DomainError("No such file: it may have been deleted")
    new_name = everyday.doc_file_name(name)
    if new_name == target.name:
        return target.relative_to(folder_of(task_id)).as_posix()
    moved = target.with_name(new_name)
    # Windows tells names apart without their case: only the case changing is a rename too.
    if moved.exists() and moved.name.lower() != target.name.lower():
        raise DomainError(f"Its folder has {new_name} already")
    target.rename(moved)
    return moved.relative_to(folder_of(task_id)).as_posix()


def delete(task_id: int, path: str) -> None:
    """A file deleted; the folders it leaves empty go too, up to the task's."""
    target, _ = _at(task_id, path)
    folder = folder_of(task_id)
    target.unlink(missing_ok=True)
    here = target.parent
    while here != folder and here.is_dir() and not any(here.iterdir()):
        shutil.rmtree(here)
        here = here.parent
