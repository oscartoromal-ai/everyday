"""The everyday files' Markdown, indexed (SPEC.md, Files first): every file
in projects/, tasks/ and notebook/ a row of `documents` (whose it is, its
path, its words' version, its size and time) and its words a row of
documents_fts, SQLite's full-text index, for search; and each file's
history, `document_revisions`, but for a task's task.md, whose words are in
the task's own history.

Whose a file is (its owner) is read from where it is:

    projects/<folder>/tasks/<id>-<words>/<name>   "task:<id>"
    tasks/<id>-<words>/<name>                     "task:<id>"
    projects/<folder>/<name>                      "project:<id>", by the folder
    notebook/<name>                               "notebook"

The files are the master copy: this is their index, read again from them
(rescan) and as the app writes them (indexed).
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models import DOCUMENTS_FTS, Document, DocumentRevision, Project
from app.services import everyday

log = logging.getLogger(__name__)

# Held by whatever reads or writes the everyday files and their rows, taken
# before the database is touched (app.services.settling): the app's writes
# and the watcher's reading never interleave.
LOCK = threading.RLock()


@contextmanager
def held(db: Session) -> Generator[None, None, None]:
    """LOCK held, and what was done committed before it is let go, so the
    watcher never reads the files between a write and its rows. Taken before
    the session writes anything, as the watcher takes it before it does."""
    with LOCK:
        yield
        db.commit()

# Edits in a row to one file by the same hand, each within this long of the
# last, are one step of its history (as a task's description is).
WRITING_SPELL = timedelta(minutes=10)

# Who changed a file from outside the app: an editor, or an agent.
FILE = "file"

TASK_FILE = "task.md"
PROJECT_FILE = "project.md"
# A task's folder: its id, then its title's words.
TASK_FOLDER = re.compile(r"^(\d+)(?:-|$)")
# The folders of everyday files the index reads.
INDEXED = ("projects", "tasks", "notebook")


def actor(db: Session) -> str:
    """Who the session acts for: oscar (the pages), claude (MCP), agent, system."""
    return db.info.get("actor", "oscar")


@dataclass(frozen=True)
class Place:
    """Whose a file is, and its path in its owner's folder."""

    owner: str
    name: str

    @property
    def is_task_file(self) -> bool:
        """A task's own task.md: its history is the task's."""
        return self.owner.startswith("task:") and self.name == TASK_FILE


def task_id_of(folder_name: str) -> int | None:
    """The task a folder is, by its name ("12-fix-it" is 12's)."""
    found = TASK_FOLDER.match(folder_name)
    return int(found[1]) if found else None


def place_of(db: Session, path: str, folders: dict[str, int] | None = None) -> Place | None:
    """Whose a file is, by its path from the everyday files' folder; None for
    one the index does not keep. `folders` maps a project's folder (in lower
    case) to its id, read from the database when not given."""
    parts = path.split("/")
    if len(parts) < 2 or any(p.startswith(".") for p in parts):
        return None
    top = parts[0]
    if top == "notebook":
        return Place("notebook", "/".join(parts[1:]))
    if top == "tasks":
        task_id = task_id_of(parts[1])
        if task_id is None or len(parts) < 3:
            return None
        return Place(f"task:{task_id}", "/".join(parts[2:]))
    if top == "projects" and len(parts) >= 3:
        if parts[2] == "tasks":
            if len(parts) < 5:
                return None
            task_id = task_id_of(parts[3])
            return None if task_id is None else Place(f"task:{task_id}", "/".join(parts[4:]))
        if folders is None:
            folders = project_folders(db)
        project_id = folders.get(parts[1].lower())
        if project_id is None:
            return None
        return Place(f"project:{project_id}", "/".join(parts[2:]))
    return None


def project_folders(db: Session) -> dict[str, int]:
    """Each project's folder, in lower case, and the project's id."""
    rows = db.execute(select(Project.folder, Project.id).where(Project.folder.is_not(None)))
    return {folder.lower(): project_id for folder, project_id in rows}


def title_of(body: str, name: str) -> str:
    """What a document is called, for search: its first heading, else its
    file's name."""
    _, words = everyday.split_front_matter(body)
    for line in words.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return name.rpartition("/")[2].removesuffix(everyday.DOC_SUFFIX)


# ---- the index ----


def indexed(db: Session, path: Path, body: str | None = None, place: Place | None = None) -> None:
    """A file's row and words made what it now holds: read when `body` is
    not given. A file that is gone, or not the index's, leaves it."""
    rel = everyday.relative(path)
    place = place or place_of(db, rel)
    try:
        stat = path.stat()
        if body is None:
            body = everyday.read_text(path)
    except OSError:
        unindexed(db, rel)
        return
    if place is None:
        unindexed(db, rel)
        return
    version = everyday.version(body)
    doc = db.scalar(select(Document).where(Document.path == rel))
    if doc is None:
        doc = Document(path=rel)
        db.add(doc)
    elif doc.version == version and doc.owner == place.owner:
        doc.size, doc.mtime_ns = stat.st_size, stat.st_mtime_ns
        db.flush()
        return
    doc.owner, doc.name, doc.version = place.owner, place.name, version
    doc.size, doc.mtime_ns, doc.indexed_at = stat.st_size, stat.st_mtime_ns, datetime.now()
    db.flush()
    _, words = everyday.split_front_matter(body)
    db.execute(text(f"DELETE FROM {DOCUMENTS_FTS} WHERE rowid = :id"), {"id": doc.id})
    db.execute(
        text(f"INSERT INTO {DOCUMENTS_FTS} (rowid, title, body) VALUES (:id, :title, :body)"),
        {"id": doc.id, "title": title_of(body, place.name), "body": words},
    )


def unindexed(db: Session, rel: str) -> None:
    """A file's row and words gone from the index (it was deleted, or moved)."""
    doc = db.scalar(select(Document).where(Document.path == rel))
    if doc is None:
        return
    db.execute(text(f"DELETE FROM {DOCUMENTS_FTS} WHERE rowid = :id"), {"id": doc.id})
    db.delete(doc)
    db.flush()


def unindexed_under(db: Session, rel: str) -> None:
    """Every file under a folder gone from the index."""
    prefix = rel.rstrip("/") + "/"
    for doc in db.scalars(select(Document).where(Document.path.startswith(prefix))):
        unindexed(db, doc.path)


def _walk() -> dict[str, Path]:
    """Every Markdown file the index keeps, by its path from the everyday
    files' folder. Hidden ones (a name starting with a dot) are left out."""
    root = everyday.root()
    out: dict[str, Path] = {}
    for top in INDEXED:
        base = root / top
        if not base.is_dir():
            continue
        for here, subdirs, names in os.walk(base):
            subdirs[:] = [d for d in subdirs if not d.startswith(".")]
            for name in names:
                if not name.startswith(".") and name.lower().endswith(everyday.DOC_SUFFIX):
                    path = Path(here) / name
                    out[everyday.relative(path)] = path
    return out


def rescan(db: Session) -> list[tuple[Place, Path, str]]:
    """The index made the files': each file new or changed since it was last
    read (by its size and time) indexed again, and each gone taken out. A
    file whose words changed outside the app is a step of its history, by
    the file's hand. Answers those whose words changed: (whose, file, words)."""
    files = _walk()
    folders = project_folders(db)
    known = {d.path: d for d in db.scalars(select(Document))}
    changed: list[tuple[Place, Path, str]] = []
    for rel, path in files.items():
        place = place_of(db, rel, folders)
        doc = known.get(rel)
        try:
            stat = path.stat()
        except OSError:
            continue
        if (
            doc is not None
            and place is not None
            and doc.owner == place.owner
            and doc.size == stat.st_size
            and doc.mtime_ns == stat.st_mtime_ns
        ):
            continue
        try:
            body = everyday.read_text(path)
        except OSError:
            continue
        if place is not None and (doc is None or doc.version != everyday.version(body)):
            changed.append((place, path, body))
            if not place.is_task_file:
                record(db, place, body, FILE)
        indexed(db, path, body, place)
    for rel in set(known) - set(files):
        unindexed(db, rel)
    return changed


# ---- history ----


def record(db: Session, place: Place, body: str, who: str) -> None:
    """A step in a file's history, its words as they now are; folded into the
    last when that was by the same hand within WRITING_SPELL, and none when
    its words are the last step's."""
    now = datetime.now()
    last = db.scalar(
        select(DocumentRevision)
        .where(DocumentRevision.owner == place.owner, DocumentRevision.name == place.name)
        .order_by(DocumentRevision.at.desc(), DocumentRevision.id.desc())
        .limit(1)
    )
    if last is not None and last.body == body:
        return
    if last is not None and last.actor == who and now - last.at <= WRITING_SPELL:
        last.body, last.at = body, now
    else:
        db.add(DocumentRevision(owner=place.owner, name=place.name, at=now, actor=who, body=body))
    db.flush()


def before_writing(db: Session, place: Place, path: Path, now: str) -> None:
    """A file about to be written over: its words a step of its history by
    the file's hand first, when they were written outside the app since the
    index read it (so an agent's edit is never lost to a save over it)."""
    if not now.strip():
        return
    doc = db.scalar(select(Document).where(Document.path == everyday.relative(path)))
    if doc is None or doc.version != everyday.version(now):
        record(db, place, now, FILE)


def history(db: Session, owner: str, name: str) -> list[DocumentRevision]:
    """A file's history, newest first."""
    return list(
        db.scalars(
            select(DocumentRevision)
            .where(DocumentRevision.owner == owner, DocumentRevision.name == name)
            .order_by(DocumentRevision.at.desc(), DocumentRevision.id.desc())
        )
    )


def moved(db: Session, owner: str, old: str, new: str) -> None:
    """A file's (or a folder's) history following it to another path in its
    owner's folder."""
    for rev in db.scalars(select(DocumentRevision).where(DocumentRevision.owner == owner)):
        if rev.name == old:
            rev.name = new
        elif rev.name.startswith(old + "/"):
            rev.name = new + rev.name[len(old):]
    db.flush()


def forget_owner(db: Session, owner: str) -> None:
    """The index's rows of an owner gone (its history stays)."""
    for doc in db.scalars(select(Document).where(Document.owner == owner)):
        unindexed(db, doc.path)


# ---- search ----


def _match(query: str) -> str:
    """A query as FTS5 reads it: each word a prefix to match, all of them."""
    words = re.findall(r"\w+", query.lower())
    return " ".join(f'"{w}"*' for w in words)


def search(
    db: Session, query: str, *, limit: int = 20, owners: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """The documents whose words hold every word of `query` (each as a
    word's start), the best first: each its path, whose it is, its name
    there, its title and a snippet around what matched. `owners` keeps those
    of owners starting so ("task:", "project:", "notebook")."""
    match = _match(query)
    if not match:
        return []
    rows = db.execute(
        text(
            f"SELECT d.path, d.owner, d.name, f.title, "
            f"snippet({DOCUMENTS_FTS}, 1, '', '', '…', 12) "
            f"FROM {DOCUMENTS_FTS} f JOIN documents d ON d.id = f.rowid "
            f"WHERE {DOCUMENTS_FTS} MATCH :match ORDER BY bm25({DOCUMENTS_FTS}) LIMIT :limit"
        ),
        {"match": match, "limit": limit * 4 if owners else limit},
    )
    out = []
    for path, owner, name, title, snippet in rows:
        if owners and not owner.startswith(owners):
            continue
        out.append({
            "path": path, "owner": owner, "name": name, "title": title,
            "snippet": " ".join(snippet.split()),
        })
        if len(out) == limit:
            break
    return out


def clear(db: Session) -> None:
    """The whole index gone (its history stays): read again by rescan."""
    db.execute(text(f"DELETE FROM {DOCUMENTS_FTS}"))
    db.execute(delete(Document))
    db.flush()
