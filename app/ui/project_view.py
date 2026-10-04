"""View-model for a project's own pages: its page (project.html), the
project at a glance, itself, its repositories and its context; and a
document of its context on a page of its own (project_doc.html)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dates import short_date, upper_first
from app.models import AGENTS_DOC, Project, ProjectDoc, Task, TaskStatus
from app.services import github as github_svc
from app.services import projects as projects_svc
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
    rest.append(_count(len(project.docs), "document", "documents"))
    return {"project": project, "head_rest": " · ".join(rest)}


def summary(body: str) -> str:
    """A document's first line of words, its heading marks gone: what it is
    about, as its row on the project's page shows it."""
    for line in body.splitlines():
        words = line.strip().lstrip("#").strip()
        if words:
            return words
    return ""


def edited(doc: ProjectDoc, today: date) -> str:
    """When it was last written: '14:02' today, else its day ('Sat 3 Oct')."""
    when = doc.updated_at
    if when.date() == today:
        return f"{when:%H:%M}"
    return upper_first(short_date(when.date(), today))


def doc_row(doc: ProjectDoc, project: Project, today: date) -> dict[str, Any]:
    """A document's row on its project's page: its name, what it is about,
    and how long it is and when it was last written, once it is written."""
    lines = _count(len(doc.body.splitlines()), "line", "lines")
    return {
        "doc": doc,
        "href": f"/projects/{project.id}/docs/{doc.id}",
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
        "docs": [doc_row(d, project, today) for d in projects_svc.docs_of(project)],
    }


def repos_ctx(project: Project) -> dict[str, Any]:
    return {
        "project": project,
        "repos": [{"repo": r, "name": projects_svc.repo_name(r.location)} for r in project.repos],
    }


# The most GitHub repositories the line to add one offers at once.
REPO_OPTIONS = 8


def repo_options_ctx(db: Session, project: Project, query: str, now: datetime) -> dict[str, Any]:
    """The GitHub repositories the line to add one offers as it is written
    on, those already the project's left out: the active ones last pushed
    first, before a word is written; then those holding its words, the
    archived ones too, or the one its GitHub URL names."""
    query = query.strip()
    taken = {name for r in project.repos if (name := github_svc.full_name_of(r.location))}
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
        "query": query,
        "options": [
            {**repo_row(r, first, now), "archived": r.archived}
            for r in found[:REPO_OPTIONS]
        ],
        "more": max(0, len(found) - REPO_OPTIONS),
        "linked": bool(links),
    }


def doc_page_ctx(doc: ProjectDoc, today: date) -> dict[str, Any]:
    project = doc.project
    return {
        "project": project,
        "doc": doc,
        "edited": edited(doc, today),
        "placeholder": (
            f"What an agent should know before working on {project.name}: how to build, "
            "run and test it, its conventions, and what to leave alone."
            if doc.name == AGENTS_DOC
            else "Write it in Markdown."
        ),
    }
