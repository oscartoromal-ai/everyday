"""View-model for a project's own pages: its page (project.html), the
project at a glance, itself, its repositories and its context; and a
document of its context on a page of its own (project_doc.html)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dates import short_date, upper_first
from app.models import AGENTS_DOC, Project, Task, TaskStatus
from app.services import everyday, project_files
from app.services import github as github_svc
from app.services import projects as projects_svc
from app.services.project_files import ContextDoc, ContextFolder
from app.ui.repositories_view import repo_row
from app.ui.views import project_glance

OPEN = (TaskStatus.todo, TaskStatus.in_progress, TaskStatus.blocked, TaskStatus.needs_review)
STATUS_WORDS = {"active": "Active", "paused": "Paused", "done": "Done"}


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def head_ctx(db: Session, project: Project) -> dict[str, Any]:
    """The header every page of the project shares: its name, and under it
    its status, open tasks, repositories and documents, counted."""
    open_count = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.project_id == project.id, Task.status.in_(OPEN))
        )
        or 0
    )
    rest = [
        STATUS_WORDS[project.status.value],
        _count(open_count, "task open", "tasks open") if open_count else "nothing open",
    ]
    if project.repos:
        rest.append(_count(len(project.repos), "repository", "repositories"))
    rest.append(_count(project_files.count_docs(project), "document", "documents"))
    return {"project": project, "head_rest": " · ".join(rest)}


def summary(body: str) -> str:
    """A document's first line of words, its heading marks gone: what it is
    about, as its row on the project's page shows it."""
    for line in body.splitlines():
        words = line.strip().lstrip("#").strip()
        if words:
            return words
    return ""


def edited(doc: ContextDoc, today: date) -> str:
    """When it was last written: '14:02' today, else its day ('Sat 3 Oct')."""
    when = doc.updated_at
    if when.date() == today:
        return f"{when:%H:%M}"
    return upper_first(short_date(when.date(), today))


def doc_href(project: Project, path: str) -> str:
    return f"/projects/{project.id}/docs/{quote(path)}"


def doc_row(doc: ContextDoc, project: Project, today: date) -> dict[str, Any]:
    """A document's row on its project's page: its name, what it is about,
    and how long it is and when it was last written, once it is written."""
    lines = _count(len(doc.body.splitlines()), "line", "lines")
    return {
        "doc": doc,
        "href": doc_href(project, doc.path),
        "summary": summary(doc.body),
        "meta": f"{lines} · {edited(doc, today)}" if doc.body.strip() else "",
    }


def glance_ctx(db: Session, project: Project, today: date) -> dict[str, Any]:
    """The project at a glance, over its page: its health, its progress,
    its next deadline and its span, with how long the span is."""
    glance = project_glance(db, project, today)
    first, last = glance["first"], glance["last"]
    length = ""
    if first and last:
        days = (last - first).days + 1
        length = (
            _count(round(days / 7), "week", "weeks") if days >= 14 else _count(days, "day", "days")
        )
    # Each day of the span kept on one line: '5 Oct to / 23 Oct', never '23 / Oct'.
    span = " to ".join(day.replace(" ", " ") for day in glance["span_label"].split(" to "))
    return {"glance": {**glance, "span_label": span, "length": length}}


def project_page_ctx(db: Session, project: Project, today: date) -> dict[str, Any]:
    return {
        **head_ctx(db, project),
        **glance_ctx(db, project, today),
        "tab": "overview",
        "status_words": STATUS_WORDS,
        "repos": repos_ctx(project)["repos"],
        **context_ctx(db, project, today),
    }


def context_tree(
    project: Project, today: date, folded: set[str] | None = None
) -> list[dict[str, Any]]:
    """The project's context as its tree: at each level its folders, by
    name, then its documents (AGENTS.md first at the top). A folder carries
    what it holds, and how many documents that is, however deep."""

    def level(here: ContextFolder, top: bool) -> list[dict[str, Any]]:
        docs = [{"kind": "doc", **doc_row(d, project, today)} for d in here.docs]
        folders = []
        for f in here.folders:
            docs_inside = f.all_docs()
            folders.append(
                {
                    "kind": "folder",
                    "folder": f,
                    "children": level(f, False),
                    "count": len(docs_inside),
                    "meta": (
                        _count(len(docs_inside), "document", "documents")
                        if docs_inside
                        else "No documents"
                        if f.folders
                        else "Empty"
                    ),
                }
            )
        if top and docs and docs[0]["doc"].is_agents:
            return [docs[0], *folders, *docs[1:]]
        return folders + docs

    return level(project_files.tree(project, folded), True)


def context_ctx(db: Session, project: Project, today: date) -> dict[str, Any]:
    folder = project_files.folder_path(project)
    return {
        "project": project,
        "tree": context_tree(project, today, project_files.folded_paths(db, project)),
        # Where its context's files are, the master copy.
        "files_folder": str(folder) if folder else None,
    }


def repos_ctx(project: Project) -> dict[str, Any]:
    return {
        "project": project,
        "repos": [{"repo": r, "name": projects_svc.repo_name(r.location)} for r in project.repos],
    }


# The most GitHub repositories the line to add one offers at once.
REPO_OPTIONS = 8


def repo_options_ctx(
    db: Session, project: Project | None, query: str, now: datetime, box: str = "repo-options"
) -> dict[str, Any]:
    """The GitHub repositories the line to add one offers as it is written
    on, those already the project's left out (none, for a project not made
    yet): the active ones last pushed first, before a word is written; then
    those holding its words, the archived ones too, or the one its GitHub
    URL names. `box` is the id of the box they are drawn in, its list's and
    options' ids named after it, so two lines on a page never cross: the
    project card's repo-options, repo-listbox and repo-option-1."""
    query = query.strip()
    repos = project.repos if project else []
    taken = {name for r in repos if (name := github_svc.full_name_of(r.location))}
    named = github_svc.full_name_of(query)
    if named:
        found = [r for r in github_svc.repositories(db) if r.full_name.lower() == named]
    else:
        found = github_svc.repositories(db, query, archived=None if query else False)
    found = [r for r in found if r.full_name.lower() not in taken]
    found.sort(key=lambda r: r.archived)  # stable: the active ones first
    links = github_svc.links(db)
    first = links[0] if links else None
    return {
        "box": box,
        "stem": box.removesuffix("-options"),
        "query": query,
        "options": [
            {**repo_row(r, first, now), "archived": r.archived}
            for r in found[:REPO_OPTIONS]
        ],
        "more": max(0, len(found) - REPO_OPTIONS),
        "linked": bool(links),
    }


def doc_file(project: Project, doc: ContextDoc) -> str | None:
    """Where its file is, from the everyday files' folder:
    projects/app/decisions/0001.md."""
    if not project.folder:
        return None
    return f"projects/{project.folder}/{doc.path}"


def doc_page_ctx(project: Project, doc: ContextDoc, today: date) -> dict[str, Any]:
    return {
        "project": project,
        "doc": doc,
        # Every folder it could be moved to, in the tree's order.
        "folders": project_files.folders_of(project),
        "edited": edited(doc, today),
        "version": everyday.version(doc.body),
        # Where its file is, from the everyday files' folder: projects/app/AGENTS.md.
        "file": doc_file(project, doc),
        "placeholder": (
            f"What an agent should know before working on {project.name}: how to build, "
            "run and test it, its conventions, and what to leave alone."
            if doc.name == AGENTS_DOC
            else "Write it in Markdown."
        ),
    }
