"""A project as its file, project.md, in its folder of the everyday files
(SPEC.md, Files first): front matter the database's (its id, name, status
and workstreams), written by the app and written back over an edit made in
the file; then the project's about, its notes, the file's.
"""

from __future__ import annotations

from typing import Any

from app import checklist
from app.models import Project
from app.services import everyday

NOTE = (
    "Personal Calendar keeps these fields: an edit here is put back. Change them in the app,\n"
    "over its API (README.md at the everyday files' top) or through Claude's tools.\n"
    "The words below, what the project is and what done looks like, are this file's."
)


def fields(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "status": project.status.value,
        "workstreams": [
            {"name": w.name, "status": w.status.value} for w in project.workstreams
        ],
        "repos": [r.location for r in project.repos],
    }


def render(project: Project) -> str:
    out = everyday.front_matter(NOTE, fields(project))
    if project.notes.strip():
        out += "\n" + project.notes.strip("\n") + "\n"
    return out


def parse(text: str) -> str:
    """The project's notes, as its file has them."""
    _, body = everyday.split_front_matter(everyday.plain(text))
    return checklist.normalize(body)
