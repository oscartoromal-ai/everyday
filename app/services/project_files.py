"""A project's folder in the everyday files' projects/ (SPEC.md, Files
first): project.md (app.services.project_md), project.toml (its id and its
repositories, which are the file's), AGENTS.md and the project's other
documents, in folders and subfolders, and tasks/, a folder for each of its
tasks (app.services.task_files).

The documents are files and nothing else: the database keeps no copy of
them. The project's page reads its folder (tree), and writes it (create,
save, place, delete), each document by its path in the folder, "/" between
its folders ("decisions/adr/0001.md"); their history is in
document_revisions (app.services.documents). What shows folded on the page
is the app's to remember (a setting).

The folder follows the database (Oscar's call on 2026-10-11): named after
the project, renamed with it; a folder made in projects/ without a
project.toml is a new project, named after it; a folder renamed by hand is
followed by the id in its project.toml, then named after its project again.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AGENTS_DOC, Document, Project, ProjectRepo, Setting
from app.services import DomainError, documents, everyday

log = logging.getLogger(__name__)

# What a project's folder holds at its top that is not a document of its
# context: the project itself, its link to the app, and its tasks.
RESERVED = {documents.PROJECT_FILE, everyday.MANIFEST, "tasks"}
FOLDED_SETTING = "context_folded"
KEEP: Any = ...


held = documents.held


def folder_path(project: Project) -> Path | None:
    return everyday.projects_dir() / project.folder if project.folder else None


def _owner(project: Project) -> str:
    return f"project:{project.id}"


# ---- the project's folder ----


def _follows(folder: str, name: str, taken: set[str]) -> bool:
    """A folder named after the project: its name as written, or the name
    made a folder's ("Personal Calendar" is personal-calendar), numbered on
    only while another folder has it (`taken`, in lower case, its own left
    out), so a project that took "-2" takes its name once it is free."""
    return folder.lower() in (name.lower(), everyday.folder_name(name, taken))


def _folders() -> list[Path]:
    root = everyday.projects_dir()
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name.lower(),
    )


def folder_of(db: Session, project: Project) -> Path:
    """The project's folder: named after it (renamed when it was renamed),
    made when it has none (a new project) or it is gone, with its
    project.toml and AGENTS.md."""
    kept = {
        f.lower()
        for f in db.scalars(
            select(Project.folder).where(Project.folder.is_not(None), Project.id != project.id)
        )
    }
    taken = kept | {p.name.lower() for p in _folders()}
    path = folder_path(project)
    if path is None:
        own = everyday.folder_name(project.name, set())
        if own not in kept and _unclaimed(db, project, everyday.projects_dir() / own):
            # A folder named after it, made by hand and no other project's: its own.
            project.folder = own
        else:
            project.folder = everyday.folder_name(project.name, taken)
        db.flush()
        path = folder_path(project)
        assert path is not None
    elif path.is_dir() and not _follows(
        project.folder or "", project.name, others := taken - {(project.folder or "").lower()}
    ):
        new = everyday.folder_name(project.name, others)
        try:
            path.rename(path.with_name(new))
            log.info("%s's folder is now %s", project.name, new)
            project.folder = new
            db.flush()
            path = path.with_name(new)
        except OSError as exc:
            log.warning("%s's folder stays %s for now: %s", project.name, path, exc)
    if not path.is_dir():
        _write_whole(db, project, path)
    _keep_agents(db, project, path)
    try:
        manifest = everyday.read_manifest(path)
    except everyday.UnreadableManifest:
        manifest = everyday.Manifest(id=project.id)
    if manifest is None or manifest.id != project.id:
        write_manifest(project, path)
    return path


def _unclaimed(db: Session, project: Project, path: Path) -> bool:
    """A folder there, whose project.toml names no other project."""
    if not path.is_dir():
        return False
    try:
        manifest = everyday.read_manifest(path)
    except everyday.UnreadableManifest:
        return False
    if manifest is None or manifest.id in (None, project.id):
        return True
    return db.get(Project, manifest.id) is None


def _write_whole(db: Session, project: Project, path: Path) -> None:
    """The project's folder made: its project.toml, and every document its
    index last knew of, as its history last had it (a folder deleted by
    hand comes back as it was)."""
    path.mkdir(parents=True, exist_ok=True)
    write_manifest(project, path)
    names = set(
        db.scalars(select(Document.name).where(Document.owner == _owner(project)))
    ) - {documents.PROJECT_FILE}
    for name in sorted(names):
        last = documents.history(db, _owner(project), name)
        if last and not name.startswith("tasks/"):
            everyday.write_text(path.joinpath(*name.split("/")), last[0].body)
    log.info("Wrote the folder of %s at %s", project.name, path)


def _keep_agents(db: Session, project: Project, path: Path) -> None:
    """AGENTS.md, which every project keeps: written back when deleted, as
    its history last had it."""
    agents = path / AGENTS_DOC
    if agents.is_file():
        return
    last = documents.history(db, _owner(project), AGENTS_DOC)
    everyday.write_text(agents, last[0].body if last else "")


def write_manifest(project: Project, path: Path | None = None) -> None:
    path = path or folder_path(project)
    assert path is not None
    everyday.write_manifest(
        path, everyday.Manifest(id=project.id, repos=[r.location for r in project.repos])
    )


def sync_project(db: Session, project: Project) -> None:
    """The project's repositories made its project.toml's, and its folder
    and AGENTS.md there."""
    path = folder_of(db, project)
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
    db.flush()


def refresh(db: Session, project: Project) -> None:
    """The project read again from its folder (sync_project), held."""
    with held(db):
        sync_project(db, project)


def sync_all(db: Session) -> None:
    """Every project's folder found, and made its project's. A folder is its
    project's by the id in its project.toml, else by the name the database
    keeps for it; a project with neither gets its folder written, and a
    folder no project has is a new project, named after it."""
    with documents.LOCK:
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
            name = (project.folder or everyday.folder_name(project.name, set())).lower()
            if project.id in by_id:
                path = by_id[project.id]
            elif name in by_name:
                path = by_name.pop(name)
                adoptable.discard(path)
            else:
                # Its folder is gone (or it has none yet): written again.
                sync_project(db, project)
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
    sync_project(db, project)
    log.info("A new project from its folder: %s", path)
    return project


# ---- its context: the documents ----


def _order(name: str) -> list[Any]:
    """A name's place among its neighbours: by its words in any case, its
    numbers as numbers ("2 Plan" before "10 Plan")."""
    return [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", name)]


@dataclass
class ContextDoc:
    """A document of the project's context, as its file has it."""

    path: str
    name: str
    body: str
    updated_at: datetime

    @property
    def is_agents(self) -> bool:
        return self.path == AGENTS_DOC

    @property
    def folder_path(self) -> str:
        """The folder it is in, "" at the top."""
        return self.path.rpartition("/")[0]


@dataclass
class ContextFolder:
    """A folder of the project's context, and what it holds."""

    path: str
    name: str
    folded: bool = False
    folders: list[ContextFolder] = field(default_factory=list)
    docs: list[ContextDoc] = field(default_factory=list)

    @property
    def key(self) -> str:
        """A name for it in a page's element ids."""
        return hashlib.sha1(self.path.lower().encode()).hexdigest()[:10]

    def all_docs(self) -> list[ContextDoc]:
        return [d for f in self.folders for d in f.all_docs()] + self.docs

    def all_folders(self) -> list[ContextFolder]:
        return [g for f in self.folders for g in (f, *f.all_folders())]


def folded_paths(db: Session, project: Project) -> set[str]:
    setting = db.get(Setting, FOLDED_SETTING)
    value = setting.value if setting else {}
    return {p.lower() for p in value.get(str(project.id), [])}


def set_folded(db: Session, project: Project, path: str, folded: bool) -> None:
    """A folder of the context folded on the page, or opened."""
    setting = db.get(Setting, FOLDED_SETTING)
    if setting is None:
        setting = Setting(key=FOLDED_SETTING, value={})
        db.add(setting)
    value = {k: list(v) for k, v in (setting.value or {}).items()}
    paths = [p for p in value.get(str(project.id), []) if p.lower() != path.lower()]
    if folded:
        paths.append(path)
    value[str(project.id)] = sorted(paths)
    setting.value = value
    db.flush()


def _unfold(db: Session, project: Project, path: str) -> None:
    """A folder and those it is in opened, so what was just put there shows."""
    folded = folded_paths(db, project)
    while path:
        if path.lower() in folded:
            set_folded(db, project, path, False)
        path = path.rpartition("/")[0]


def tree(project: Project, folded: set[str] | None = None) -> ContextFolder:
    """The project's context as its folder has it: at each level its folders
    and its documents by name, AGENTS.md first at the top, the folders whose
    paths (in lower case) `folded` holds folded. Hidden ones (a name
    starting with a dot), and what at the top is not the context's
    (project.md, project.toml, tasks/), are left out."""
    root = folder_path(project)
    folded = folded or set()
    top = ContextFolder(path="", name="")
    if root is None or not root.is_dir():
        return top

    def level(here: Path, into: ContextFolder) -> None:
        for p in sorted(here.iterdir(), key=lambda p: _order(p.name)):
            if p.name.startswith(".") or (here == root and p.name.lower() in RESERVED):
                continue
            rel = p.relative_to(root).as_posix()
            if p.is_dir():
                folder = ContextFolder(path=rel, name=p.name, folded=rel.lower() in folded)
                level(p, folder)
                into.folders.append(folder)
            elif p.is_file() and p.name.lower().endswith(everyday.DOC_SUFFIX):
                into.docs.append(_doc(p, rel))

    level(root, top)
    top.docs.sort(key=lambda d: (not d.is_agents, _order(d.name)))
    return top


def _doc(path: Path, rel: str) -> ContextDoc:
    return ContextDoc(
        path=rel,
        name=path.name,
        body=everyday.read_text(path),
        updated_at=datetime.fromtimestamp(path.stat().st_mtime),
    )


def docs_of(project: Project) -> list[ContextDoc]:
    """A project's documents in the order its tree reads them: AGENTS.md,
    then each folder's (its subfolders' first), then the rest at the top."""
    top = tree(project)
    agents = [d for d in top.docs if d.is_agents]
    return agents + [d for f in top.folders for d in f.all_docs()] + [
        d for d in top.docs if not d.is_agents
    ]


def folders_of(project: Project) -> list[ContextFolder]:
    """Every folder of the project's context, each followed by its subfolders."""
    return tree(project).all_folders()


def _parts(path: str) -> list[str]:
    pure = PurePosixPath(path.replace("\\", "/").strip().strip("/"))
    names = [" ".join(part.split()) for part in pure.parts if part not in ("", ".")]
    if not names or ".." in names or not all(names):
        raise DomainError("A path stays in the project's folder")
    return names


def _at(project: Project, path: str) -> Path:
    """Where a path of the context is on disk; refused when it leaves the
    folder, or names what is not the context's."""
    root = folder_path(project)
    if root is None:
        raise DomainError(f"{project.name} has no folder yet")
    names = _parts(path)
    if names[0].lower() in RESERVED:
        raise DomainError(f"{names[0]} is not one of the context's documents")
    target = root.joinpath(*names)
    if not target.resolve().is_relative_to(root.resolve()):
        raise DomainError("A path stays in the project's folder")
    return target


def _rel(project: Project, target: Path) -> str:
    root = folder_path(project)
    assert root is not None
    return target.relative_to(root).as_posix()


def _check_free(project: Project, target: Path, renaming: Path | None = None) -> None:
    """Nothing beside it in its folder has its name (in any case)."""
    if not target.parent.is_dir():
        return
    lower = target.name.lower()
    for sibling in target.parent.iterdir():
        if sibling.name.lower() == lower and sibling != renaming:
            where = _rel(project, target.parent) if target.parent != folder_path(project) else ""
            place = f"{project.name}'s {where}" if where else project.name
            raise DomainError(f"{place} already has {sibling.name}")
    reserved = RESERVED | {AGENTS_DOC.lower()}
    if (
        target.parent == folder_path(project)
        and lower in reserved
        and (renaming is None or renaming.name.lower() != lower)
    ):
        raise DomainError(f"{target.name} is kept for the project itself")


def read(project: Project, path: str) -> ContextDoc:
    target = _at(project, path)
    if not target.is_file():
        raise DomainError("No such document: it may have been deleted")
    return _doc(target, _rel(project, target))


def _place_name(folder: str | None, name: str) -> list[str]:
    """Where a name written to add one goes: in the folder it was written in,
    or, written as a path ("decisions/adr/0001.md"), in the folders it names
    under it."""
    if re.search(r"(^|[/\\])\.\.?($|[/\\])", name.strip()):
        raise DomainError("A name can't hold . or .. as a folder")
    parts = [p for p in re.split(r"[/\\]", name) if p.strip()]
    if not parts:
        raise DomainError("A document needs a name")
    return ([*folder.split("/")] if folder else []) + parts


def create_doc(
    db: Session, project: Project, name: str, folder: str | None = None, body: str = ""
) -> ContextDoc:
    """A new document, in a folder or at the top; written as a path
    ("decisions/0001.md"), in the folders it names, made as they are
    missing."""
    folder_of(db, project)
    *parents, last = _place_name(folder, name)
    parents = _as_on_disk(project, [everyday.folder_file_name(p) for p in parents])
    target = _at(project, "/".join([*parents, everyday.doc_file_name(last)]))
    _check_parents(project, target)
    _check_free(project, target)
    everyday.write_text(target, body)
    rel = _rel(project, target)
    place = documents.Place(_owner(project), rel)
    documents.record(db, place, body, documents.actor(db))
    documents.indexed(db, target, body, place)
    _unfold(db, project, rel.rpartition("/")[0])
    return _doc(target, rel)


def _as_on_disk(project: Project, names: list[str]) -> list[str]:
    """Folders' names as the folders already there have them (Windows tells
    names apart without their case: "Decisions" is the decisions there)."""
    here = folder_path(project)
    out = []
    for name in names:
        found = None
        if here is not None and here.is_dir():
            found = next((c.name for c in here.iterdir() if c.name.lower() == name.lower()), None)
        out.append(found or name)
        here = here / out[-1] if here is not None else None
    return out


def _check_parents(project: Project, target: Path) -> None:
    """Each folder on the way a folder, not a document of that name."""
    root = folder_path(project)
    here = target.parent
    while here != root:
        if here.exists() and not here.is_dir():
            raise DomainError(f"{here.name} is a document, not a folder")
        here = here.parent


def create_folder(db: Session, project: Project, name: str, folder: str | None = None) -> str:
    """A new folder, in a folder or at the top; written as a path, the
    folders it names under it too. Answers its path."""
    folder_of(db, project)
    parts = _as_on_disk(project, [everyday.folder_file_name(p) for p in _place_name(folder, name)])
    target = _at(project, "/".join(parts))
    _check_parents(project, target)
    _check_free(project, target)
    target.mkdir(parents=True)
    rel = _rel(project, target)
    _unfold(db, project, rel)
    return rel


class DocChanged(DomainError):
    """A document saved from a copy older than its file: written elsewhere
    (an editor, an agent) since the copy was read. Its version is the file's."""

    def __init__(self, name: str, body: str) -> None:
        super().__init__(f"{name} was changed elsewhere since this copy was read")
        self.version = everyday.version(body)


def save(db: Session, project: Project, path: str, body: str, base: str | None = None) -> str:
    """A document's words written whole, over the copy of version `base`
    (DocChanged when the file has moved on from it; without one, over
    whatever is there): its version now."""
    with documents.LOCK:
        target = _at(project, path)
        if not target.is_file():
            raise DomainError("No such document: it may have been deleted")
        now = everyday.read_text(target)
        if base is not None and base != everyday.version(now):
            raise DocChanged(target.name, now)
        body = everyday.plain(body)
        rel = _rel(project, target)
        place = documents.Place(_owner(project), rel)
        if body != now:
            documents.before_writing(db, place, target, now)
            everyday.write_text(target, body)
            documents.record(db, place, body, documents.actor(db))
        documents.indexed(db, target, body, place)
        return everyday.version(body)


def place(
    db: Session, project: Project, path: str, *, name: str | None = None, folder: Any = KEEP
) -> str:
    """A document or folder renamed, or moved into another folder ("": to
    the top), on disk with all it holds: its path now. AGENTS.md keeps its
    name and its place."""
    with documents.LOCK:
        source = _at(project, path)
        if not source.exists():
            raise DomainError("Not in the project's folder any more: it was moved or deleted there")
        rel = _rel(project, source)
        if rel == AGENTS_DOC:
            raise DomainError(f"{AGENTS_DOC} keeps its name and its place")
        is_folder = source.is_dir()
        if name is not None and re.search(r"[/\\]", name):
            raise DomainError("A name can't hold a slash")
        new_name = source.name if name is None else (
            everyday.folder_file_name(name) if is_folder else everyday.doc_file_name(name)
        )
        parent = source.parent if folder is KEEP else (
            folder_path(project) if not folder else _at(project, folder)  # type: ignore[assignment]
        )
        assert parent is not None
        if is_folder and (parent == source or parent.resolve().is_relative_to(source.resolve())):
            raise DomainError(f"{source.name} can't go inside itself")
        if not parent.is_dir():
            raise DomainError("No such folder: it may have been deleted")
        target = parent / new_name
        if str(target) == str(source):  # a change of case alone is a rename too
            return rel
        _check_free(project, target, renaming=source)
        source.rename(target)
        new = _rel(project, target)
        documents.moved(db, _owner(project), rel, new)
        if is_folder:
            documents.unindexed_under(db, everyday.relative(source))
            for file in target.rglob(f"*{everyday.DOC_SUFFIX}"):
                owned = documents.Place(_owner(project), _rel(project, file))
                documents.indexed(db, file, place=owned)
            _move_folded(db, project, rel, new)
        else:
            documents.unindexed(db, everyday.relative(source))
            documents.indexed(db, target, place=documents.Place(_owner(project), new))
        _unfold(db, project, new.rpartition("/")[0])
        return new


def _move_folded(db: Session, project: Project, old: str, new: str) -> None:
    folded = folded_paths(db, project)
    for path in list(folded):
        if path == old.lower() or path.startswith(old.lower() + "/"):
            set_folded(db, project, path, False)
            set_folded(db, project, new + path[len(old):], True)


def delete(db: Session, project: Project, path: str) -> None:
    """A document, or a folder with everything in it, deleted (its history
    stays). AGENTS.md is every project's, and stays."""
    with documents.LOCK:
        target = _at(project, path)
        if _rel(project, target) == AGENTS_DOC:
            raise DomainError(f"Every project keeps its {AGENTS_DOC}")
        if target.is_dir():
            documents.unindexed_under(db, everyday.relative(target))
            shutil.rmtree(target)
        elif target.exists():
            documents.unindexed(db, everyday.relative(target))
            target.unlink()
        else:
            raise DomainError("Not in the project's folder any more: it was moved or deleted there")


def count_docs(project: Project) -> int:
    """How many documents the project's context holds."""
    root = folder_path(project)
    if root is None or not root.is_dir():
        return 0
    return sum(
        1
        for p in root.rglob(f"*{everyday.DOC_SUFFIX}")
        if not any(part.startswith(".") for part in p.relative_to(root).parts)
        and p.relative_to(root).parts[0].lower() not in RESERVED
    )
