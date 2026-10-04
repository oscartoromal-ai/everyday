"""A project's own pages: its page (the project, its repositories and its
context, AGENTS.md first), its Tasks, each document of its context on a page
of its own, and the edits made on them. Its Gantt is app.ui.gantt's."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response

from app.db import DbSession
from app.models import ProjectDocFolder, ProjectStatus
from app.services import DomainError
from app.services import projects as projects_svc
from app.ui.project_view import (
    context_ctx,
    doc_page_ctx,
    glance_ctx,
    head_ctx,
    project_page_ctx,
    repo_options_ctx,
    repos_ctx,
)
from app.ui.views import project_tasks_ctx, templates

router = APIRouter(include_in_schema=False)


def _project(db: DbSession, project_id: int):  # noqa: ANN202
    try:
        return projects_svc.get_project(db, project_id)
    except DomainError:
        raise HTTPException(404, "No such project") from None


@router.get("/projects/{project_id}")
def project_page(request: Request, db: DbSession, project_id: int):
    project = _project(db, project_id)
    return templates.TemplateResponse(
        request,
        "project.html",
        {
            "request": request,
            "active": "project",
            "today": date.today(),
            **project_page_ctx(db, project, date.today()),
        },
    )


@router.get("/projects/{project_id}/tasks")
def project_tasks_page(request: Request, db: DbSession, project_id: int):
    """Its Tasks tab: where its tasks are planned, a list a workstream."""
    project = _project(db, project_id)
    return templates.TemplateResponse(
        request,
        "project_tasks.html",
        {
            "request": request,
            "active": "project",
            "today": date.today(),
            **head_ctx(db, project),
            "tab": "tasks",
            **project_tasks_ctx(db, project, datetime.now()),
        },
    )


@router.post("/ui/projects/{project_id}/about")
def save_about(
    request: Request,
    db: DbSession,
    project_id: int,
    name: Annotated[str | None, Form()] = None,
    status: Annotated[ProjectStatus | None, Form()] = None,
    color: Annotated[int | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
):
    """The project itself, written on its page, a card at a time (its
    details, its description): each posts only its own fields. Answered
    with its header, which names it, and the glance, which its status
    changes; the sidebar hears of it too."""
    projects_svc.update_project(
        db,
        project_id,
        name=name,
        status=status,
        color=color,
        notes=None if notes is None else notes.strip(),
    )
    db.commit()
    project = projects_svc.get_project(db, project_id)
    response = templates.TemplateResponse(
        request,
        "partials/project_about.html",
        {
            "request": request,
            "tab": "overview",
            **head_ctx(db, project),
            **glance_ctx(db, project, date.today()),
        },
    )
    response.headers["HX-Trigger"] = "projects:changed"
    return response


def _repos(request: Request, db: DbSession, project_id: int, added: bool = False) -> Response:
    """Its repositories drawn again, and the header's count with them; just
    after one is added, its line to add one quiet as the focus comes back
    to it, rather than offering more at once."""
    project = projects_svc.get_project(db, project_id)
    db.refresh(project, ["repos"])
    return templates.TemplateResponse(
        request,
        "partials/project_repos.html",
        {
            "request": request,
            "oob_head": True,
            "added": added,
            "tab": "overview",
            **head_ctx(db, project),
            **repos_ctx(project),
        },
    )


@router.post("/ui/projects/{project_id}/repos")
def add_repo(request: Request, db: DbSession, project_id: int, location: Annotated[str, Form()]):
    projects_svc.add_repo(db, project_id=project_id, location=location)
    db.commit()
    return _repos(request, db, project_id, added=True)


@router.get("/ui/projects/{project_id}/repo-options")
def repo_options(request: Request, db: DbSession, project_id: int, location: str = ""):
    """The GitHub repositories the line to add one offers, as it is written on."""
    project = _project(db, project_id)
    return templates.TemplateResponse(
        request,
        "partials/project_repo_options.html",
        {"request": request, **repo_options_ctx(db, project, location, datetime.now())},
    )


@router.post("/ui/repos/{repo_id}")
def save_repo(request: Request, db: DbSession, repo_id: int, location: Annotated[str, Form()]):
    repo = projects_svc.update_repo(db, repo_id, location=location)
    db.commit()
    return _repos(request, db, repo.project_id)


@router.post("/ui/repos/{repo_id}/delete")
def delete_repo(request: Request, db: DbSession, repo_id: int):
    project_id = projects_svc.get_repo(db, repo_id).project_id
    projects_svc.delete_repo(db, repo_id)
    db.commit()
    return _repos(request, db, project_id)


def _folder(value: str | None) -> int | None:
    """A folder posted as where something goes: its id, or "top" for the
    context's top (an empty value reads as none posted). Not posted at all,
    it stays where it is."""
    if value is None:
        return projects_svc.KEEP
    return None if value.strip() in ("", "top") else int(value)


def _context(request: Request, db: DbSession, project_id: int) -> Response:
    """Its context drawn again, and the header's count with it."""
    project = projects_svc.get_project(db, project_id)
    db.refresh(project, ["docs", "doc_folders"])
    return templates.TemplateResponse(
        request,
        "partials/project_context.html",
        {
            "request": request,
            "oob_head": True,
            "tab": "overview",
            **head_ctx(db, project),
            **context_ctx(project, date.today()),
        },
    )


def _unfold(folder: ProjectDocFolder | None) -> None:
    """A folder and those it is in opened, so what was just put in it shows."""
    while folder is not None:
        folder.folded = False
        folder = folder.parent


@router.post("/ui/projects/{project_id}/docs")
def add_doc(
    db: DbSession,
    project_id: int,
    name: Annotated[str, Form()],
    folder: Annotated[str, Form()] = "",
):
    """A new document, in the folder it was written in (a path names
    folders under it), opened on its own page to be written."""
    doc = projects_svc.create_doc(db, project_id=project_id, name=name, folder_id=_folder(folder))
    _unfold(doc.folder)
    db.commit()
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = f"/projects/{project_id}/docs/{doc.id}"
    return response


@router.post("/ui/projects/{project_id}/folders")
def add_folder(
    request: Request,
    db: DbSession,
    project_id: int,
    name: Annotated[str, Form()],
    folder: Annotated[str, Form()] = "",
):
    """A new folder, in the folder it was written in, or at the top."""
    made = projects_svc.create_folder(
        db, project_id=project_id, name=name, parent_id=_folder(folder)
    )
    _unfold(made.parent)
    db.commit()
    return _context(request, db, project_id)


@router.post("/ui/folders/{folder_id}/place")
def place_folder(
    request: Request,
    db: DbSession,
    folder_id: int,
    name: Annotated[str | None, Form()] = None,
    folder: Annotated[str | None, Form()] = None,
):
    """A folder renamed on the tree, or dragged into another."""
    moved = projects_svc.update_folder(db, folder_id, name=name, parent_id=_folder(folder))
    _unfold(moved.parent)
    db.commit()
    return _context(request, db, moved.project_id)


@router.post("/ui/folders/{folder_id}/fold", status_code=204)
def fold_folder(db: DbSession, folder_id: int, folded: Annotated[bool, Form()]) -> None:
    """A folder folded or opened on the tree, which has drawn it so already."""
    projects_svc.update_folder(db, folder_id, folded=folded)
    db.commit()


@router.post("/ui/folders/{folder_id}/delete")
def delete_folder(request: Request, db: DbSession, folder_id: int):
    """A folder gone, with everything in it."""
    project_id = projects_svc.get_folder(db, folder_id).project_id
    projects_svc.delete_folder(db, folder_id)
    db.commit()
    return _context(request, db, project_id)


@router.post("/ui/docs/{doc_id}/place")
def place_doc(
    request: Request,
    db: DbSession,
    doc_id: int,
    name: Annotated[str | None, Form()] = None,
    folder: Annotated[str | None, Form()] = None,
):
    """A document renamed on the tree, or dragged into a folder."""
    doc = projects_svc.update_doc(db, doc_id, name=name, folder_id=_folder(folder))
    _unfold(doc.folder)
    db.commit()
    return _context(request, db, doc.project_id)


@router.get("/projects/{project_id}/docs/{doc_id}")
def doc_page(request: Request, db: DbSession, project_id: int, doc_id: int):
    try:
        doc = projects_svc.get_doc(db, doc_id)
    except DomainError:
        doc = None
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "No such document: it may have been deleted")
    return templates.TemplateResponse(
        request,
        "project_doc.html",
        {
            "request": request,
            "active": "project",
            "today": date.today(),
            **doc_page_ctx(doc, date.today()),
        },
    )


@router.post("/ui/docs/{doc_id}", status_code=204)
def save_doc(
    db: DbSession,
    doc_id: int,
    body: Annotated[str | None, Form()] = None,
    name: Annotated[str | None, Form()] = None,
    folder: Annotated[str | None, Form()] = None,
) -> None:
    """A document saved as it is written (doc-editor.js), or moved into
    another folder from its page."""
    doc = projects_svc.update_doc(
        db,
        doc_id,
        name=name,
        body=None if body is None else body.replace("\r\n", "\n"),
        folder_id=_folder(folder),
    )
    if folder is not None:
        _unfold(doc.folder)
    db.commit()


@router.post("/ui/docs/{doc_id}/delete")
def delete_doc(request: Request, db: DbSession, doc_id: int, tree: bool = False):
    """A document gone. Deleted on the tree, the tree is drawn again; on its
    own page, the page goes with it: back to its project's."""
    project_id = projects_svc.get_doc(db, doc_id).project_id
    projects_svc.delete_doc(db, doc_id)
    db.commit()
    if tree:
        return _context(request, db, project_id)
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = f"/projects/{project_id}"
    return response
