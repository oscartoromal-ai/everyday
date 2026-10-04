"""The everyday files (SPEC.md, Agent runs): the folder for agentic work,
C:\\everyday-files unless Setup chose another ([everyday_files] dir).

    repos/       each repository's main clone, once
    projects/    a folder a project: its context's documents, and project.toml
    work/        the folders runs work in

This module is the files alone: where they are, what a document's file is
named, project.toml read and written, and a file written whole or not at all.
What they mean to the database is app.services.project_files'.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.services import DomainError

log = logging.getLogger(__name__)

MANIFEST = "project.toml"
DOC_SUFFIX = ".md"

# What Windows refuses in a file's name, and the names it keeps for devices.
_REFUSED = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}


def root() -> Path:
    return get_settings().everyday_dir


def repos_dir() -> Path:
    return root() / "repos"


def projects_dir() -> Path:
    return root() / "projects"


def work_dir() -> Path:
    return root() / "work"


def ensure() -> None:
    """The three folders, made where missing."""
    for folder in (repos_dir(), projects_dir(), work_dir()):
        folder.mkdir(parents=True, exist_ok=True)


# ---- names ----


def doc_file_name(name: str) -> str:
    """A document's name as its file's: its words with their spaces made
    single, ending in .md (added when not written), and a name Windows
    allows for a file. Raises DomainError for one it does not."""
    name = " ".join(name.split()).rstrip(". ")
    if not name:
        raise DomainError("A document needs a name")
    if not name.lower().endswith(DOC_SUFFIX):
        name += DOC_SUFFIX
    if len(name) > 200:
        raise DomainError("A document's name is 200 characters at most")
    if _REFUSED.search(name):
        raise DomainError('A document\'s name cannot hold < > : " / \\ | ? or *')
    if name.split(".")[0].strip().upper() in _DEVICES:
        raise DomainError(f"Windows keeps the name {name.split('.')[0]} for itself")
    return name


def folder_file_name(name: str) -> str:
    """A folder's name of a project's context, its folder's on disk: its
    words with their spaces made single, and a name Windows allows for a
    folder. Raises DomainError for one it does not."""
    name = " ".join(name.split()).rstrip(". ")
    if not name:
        raise DomainError("A folder needs a name")
    if len(name) > 200:
        raise DomainError("A folder's name is 200 characters at most")
    if _REFUSED.search(name):
        raise DomainError('A folder\'s name cannot hold < > : " / \\ | ? or *')
    if name.split(".")[0].strip().upper() in _DEVICES:
        raise DomainError(f"Windows keeps the name {name.split('.')[0]} for itself")
    return name


def safe_folder_file_name(name: str, taken: set[str]) -> str:
    """A folder's name from before folders were on disk, made one Windows
    allows (what it refuses made hyphens), numbered on when `taken` (in lower
    case) has it."""
    try:
        name = folder_file_name(name)
    except DomainError:
        try:
            name = folder_file_name(_REFUSED.sub("-", name))
        except DomainError:
            name = "Folder"
    candidate, n = name, 1
    while candidate.lower() in taken:
        n += 1
        candidate = f"{name} ({n})"
    return candidate


def safe_doc_file_name(name: str, taken: set[str]) -> str:
    """A file's name for a document named before documents were files: as
    doc_file_name makes it, what Windows refuses made hyphens, and numbered
    on ("Notes (2).md") when another of `taken` (in lower case) has it."""
    try:
        name = doc_file_name(name)
    except DomainError:
        try:
            name = doc_file_name(_REFUSED.sub("-", name))
        except DomainError:
            name = "Document.md"
    stem, n, candidate = name[: -len(DOC_SUFFIX)], 1, name
    while candidate.lower() in taken:
        n += 1
        candidate = f"{stem} ({n}){DOC_SUFFIX}"
    return candidate


def folder_name(name: str, taken: set[str]) -> str:
    """A new project's folder: its name in lower case, words joined by
    hyphens ("Personal Calendar" is personal-calendar), numbered on when a
    folder has it already (in any case)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80].strip("-") or "project"
    taken = {t.lower() for t in taken}
    candidate, n = slug, 1
    while candidate in taken or candidate.upper() in _DEVICES:
        n += 1
        candidate = f"{slug}-{n}"
    return candidate


# ---- a document's words ----


def plain(text: str) -> str:
    """A file's words as the app keeps them: lines ended by \\n alone."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def version(body: str) -> str:
    """A document's version: its words' hash, which a save names to show
    the copy it was made from."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def read_text(path: Path) -> str:
    return plain(path.read_bytes().decode("utf-8", errors="replace").removeprefix("\ufeff"))


def write_text(path: Path, text: str) -> None:
    """The file written whole or not at all: to a file beside it, then put
    in its place, so an editor or agent reading it never sees half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_bytes(text.encode("utf-8"))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


# ---- project.toml ----


@dataclass
class Manifest:
    """A project folder's project.toml: the project it is (its id, None for
    a folder no project has yet) and its repositories' locations."""

    id: int | None = None
    repos: list[str] = field(default_factory=list)


class UnreadableManifest(Exception):
    """A project.toml that is not TOML, or not one the app wrote: left as it
    is, for whoever wrote it to put right."""


def read_manifest(folder: Path) -> Manifest | None:
    """The folder's project.toml, or None when it has none. Raises
    UnreadableManifest for one that cannot be read."""
    path = folder / MANIFEST
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(read_text(path))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise UnreadableManifest(f"{path}: {exc}") from exc
    project_id, repos = data.get("id"), data.get("repos", [])
    if (project_id is not None and not isinstance(project_id, int)) or not (
        isinstance(repos, list) and all(isinstance(r, str) for r in repos)
    ):
        raise UnreadableManifest(f"{path}: id is a number and repos a list of strings")
    # Each once, in the order written.
    return Manifest(id=project_id, repos=list(dict.fromkeys(r.strip() for r in repos if r.strip())))


MANIFEST_HEAD = (
    "# Personal Calendar's link to this project (id) and where its code is (repos):\n"
    "# local paths or URLs, one a line. Edit repos freely; the app keeps the id.\n"
)


def write_manifest(folder: Path, manifest: Manifest) -> None:
    # A JSON string is a TOML basic string, its escapes included.
    lines = "".join(f"    {json.dumps(r, ensure_ascii=False)},\n" for r in manifest.repos)
    repos = f"[\n{lines}]" if lines else "[]"
    write_text(folder / MANIFEST, f"{MANIFEST_HEAD}id = {manifest.id}\nrepos = {repos}\n")
