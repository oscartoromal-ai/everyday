"""A project's own pages: its page (the project, its repositories and its
context, AGENTS.md first), each document of its context on a page of its
own, and the edits made on them. Its Gantt is app.ui.gantt's."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response

from app.db import DbSession
from app.models import ProjectStatus
from app.services import DomainError
from app.services import projects as projects_svc
from app.ui.project_view import doc_page_ctx, head_ctx, project_page_ctx, repos_ctx
from app.ui.views import templates

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


@router.post("/ui/projects/{project_id}/about")
def save_about(
    request: Request,
    db: DbSession,
    project_id: int,
    name: Annotated[str, Form()],
    status: Annotated[ProjectStatus, Form()],
    color: Annotated[int, Form()],
    notes: Annotated[str, Form()] = "",
):
    """The project itself, written on its page: answered with its header,
    which names it; the sidebar hears of it too."""
    projects_svc.update_project(
        db, project_id, name=name, status=status, color=color, notes=notes.strip()
    )
    db.commit()
    project = projects_svc.get_project(db, project_id)
    response = templates.TemplateResponse(
        request,
        "partials/project_head.html",
        {"request": request, "tab": "overview", **head_ctx(db, project)},
    )
    response.headers["HX-Trigger"] = "projects:changed"
    return response


def _repos(request: Request, db: DbSession, project_id: int) -> Response:
    """Its repositories drawn again, and the header's count with them."""
    project = projects_svc.get_project(db, project_id)
    db.refresh(project, ["repos"])
    return templates.TemplateResponse(
        request,
        "partials/project_repos.html",
        {
            "request": request,
            "oob_head": True,
            "tab": "overview",
            **head_ctx(db, project),
            **repos_ctx(project),
        },
    )


@router.post("/ui/projects/{project_id}/repos")
def add_repo(request: Request, db: DbSession, project_id: int, location: Annotated[str, Form()]):
    projects_svc.add_repo(db, project_id=project_id, location=location)
    db.commit()
    return _repos(request, db, project_id)


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


@router.post("/ui/projects/{project_id}/docs")
def add_doc(db: DbSession, project_id: int, name: Annotated[str, Form()]):
    """A new document, opened on its own page to be written."""
    doc = projects_svc.create_doc(db, project_id=project_id, name=name)
    db.commit()
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = f"/projects/{project_id}/docs/{doc.id}"
    return response


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
) -> None:
    """A document saved as it is written (doc-editor.js)."""
    projects_svc.update_doc(
        db, doc_id, name=name, body=None if body is None else body.replace("\r\n", "\n")
    )
    db.commit()


@router.post("/ui/docs/{doc_id}/delete")
def delete_doc(db: DbSession, doc_id: int):
    """A document gone, and its page with it: back to its project's."""
    project_id = projects_svc.get_doc(db, doc_id).project_id
    projects_svc.delete_doc(db, doc_id)
    db.commit()
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = f"/projects/{project_id}"
    return response
