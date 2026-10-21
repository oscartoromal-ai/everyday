"""A project's own pages: its page (the project, its repositories and its
context, AGENTS.md first), its Tasks, each document of its context on a page
of its own, and the edits made on them. Its Gantt is app.ui.gantt's."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.db import DbSession
from app.models import Project, ProjectStatus
from app.services import DomainError, everyday, project_files
from app.services import projects as projects_svc
from app.services.project_files import ContextDoc
from app.ui.project_view import (
    context_ctx,
    doc_file,
    doc_href,
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
    project_files.refresh(db, project)
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
def repo_options(
    request: Request, db: DbSession, project_id: int, location: str = "", box: str = "repo-options"
):
    """The GitHub repositories the line to add one offers, as it is written on."""
    project = _project(db, project_id)
    return _repo_options(request, db, project, location, box)


@router.get("/ui/repo-options")
def new_repo_options(
    request: Request, db: DbSession, location: str = "", box: str = "repo-options"
):
    """Those the new project window's line offers: none taken yet, as the
    project is not made yet."""
    return _repo_options(request, db, None, location, box)


def _repo_options(
    request: Request, db: DbSession, project: Project | None, location: str, box: str
) -> Response:
    return templates.TemplateResponse(
        request,
        "partials/project_repo_options.html",
        {"request": request, **repo_options_ctx(db, project, location, datetime.now(), box)},
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


def _folder(value: str | None) -> str | None:
    """A folder posted as where something goes: its path, "/" for the
    context's top (an empty value reads as none posted). Not posted at all,
    it stays where it is."""
    if value is None:
        return project_files.KEEP
    return value.strip().strip("/")


def _context(request: Request, db: DbSession, project: Project) -> Response:
    """Its context drawn again, and the header's count with it."""
    return templates.TemplateResponse(
        request,
        "partials/project_context.html",
        {
            "request": request,
            "oob_head": True,
            "tab": "overview",
            **head_ctx(db, project),
            **context_ctx(db, project, date.today()),
        },
    )


@router.post("/ui/projects/{project_id}/docs")
def add_doc(
    db: DbSession,
    project_id: int,
    name: Annotated[str, Form()],
    folder: Annotated[str, Form()] = "",
):
    """A new document, in the folder it was written in (a path names
    folders under it), opened on its own page to be written."""
    project = _project(db, project_id)
    with project_files.held(db):
        doc = project_files.create_doc(db, project, name, _folder(folder) or None)
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = doc_href(project, doc.path)
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
    project = _project(db, project_id)
    with project_files.held(db):
        project_files.create_folder(db, project, name, _folder(folder) or None)
    return _context(request, db, project)


@router.post("/ui/projects/{project_id}/context/place")
def place_in_context(
    request: Request,
    db: DbSession,
    project_id: int,
    path: Annotated[str, Form()],
    name: Annotated[str | None, Form()] = None,
    folder: Annotated[str | None, Form()] = None,
):
    """A document or folder renamed on the tree, or dragged into a folder
    (or out to the top)."""
    project = _project(db, project_id)
    with project_files.held(db):
        project_files.place(db, project, path, name=name, folder=_folder(folder))
    return _context(request, db, project)


@router.post("/ui/projects/{project_id}/context/fold", status_code=204)
def fold_folder(
    db: DbSession, project_id: int, path: Annotated[str, Form()],
    folded: Annotated[bool, Form()],
) -> None:
    """A folder folded or opened on the tree, which has drawn it so already."""
    project_files.set_folded(db, _project(db, project_id), path, folded)
    db.commit()


@router.post("/ui/projects/{project_id}/context/delete")
def delete_in_context(
    request: Request,
    db: DbSession,
    project_id: int,
    path: Annotated[str, Form()],
    tree: bool = False,
):
    """A document, or a folder with everything in it, gone. Deleted on the
    tree, the tree is drawn again; on a document's own page, the page goes
    with it: back to its project's."""
    project = _project(db, project_id)
    with project_files.held(db):
        project_files.delete(db, project, path)
    if tree:
        return _context(request, db, project)
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = f"/projects/{project_id}"
    return response


def _doc(db: DbSession, project: Project, path: str) -> ContextDoc:
    """The document, as its file has it: 404 when there is no such file."""
    try:
        return project_files.read(project, path)
    except DomainError:
        raise HTTPException(404, "No such document: it may have been deleted") from None


@router.get("/projects/{project_id}/docs/{path:path}")
def doc_page(request: Request, db: DbSession, project_id: int, path: str):
    project = _project(db, project_id)
    project_files.refresh(db, project)
    doc = _doc(db, project, path)
    return templates.TemplateResponse(
        request,
        "project_doc.html",
        {
            "request": request,
            "active": "project",
            "today": date.today(),
            **doc_page_ctx(project, doc, date.today()),
        },
    )


@router.post("/ui/projects/{project_id}/doc")
def save_doc(
    db: DbSession,
    project_id: int,
    path: Annotated[str, Form()],
    body: Annotated[str | None, Form()] = None,
    name: Annotated[str | None, Form()] = None,
    folder: Annotated[str | None, Form()] = None,
    base: Annotated[str | None, Form()] = None,
) -> Response:
    """A document saved as it is written (doc-editor.js), its words written
    over the copy of version `base`, or renamed from its heading: answered
    with its version, name and path now, or 409 with its file's version when
    that was written elsewhere since. Moved into another folder from its
    page, the page goes where it now is."""
    project = _project(db, project_id)
    with project_files.held(db):
        try:
            if body is not None:
                project_files.save(db, project, path, everyday.plain(body), base)
        except project_files.DocChanged as exc:
            return JSONResponse({"detail": str(exc), "version": exc.version}, status_code=409)
        if name is not None or folder is not None:
            path = project_files.place(db, project, path, name=name, folder=_folder(folder))
    doc = _doc(db, project, path)
    if folder is not None:
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = doc_href(project, doc.path)
        return response
    return JSONResponse(
        {
            "version": everyday.version(doc.body),
            "name": doc.name,
            "path": doc.path,
            "href": doc_href(project, doc.path),
            "file": doc_file(project, doc),
        }
    )


@router.get("/ui/projects/{project_id}/doc")
def latest_doc(db: DbSession, project_id: int, path: str) -> JSONResponse:
    """The document as its file has it now, for its page to show a version
    written elsewhere (doc-editor.js)."""
    doc = _doc(db, _project(db, project_id), path)
    return JSONResponse({"version": everyday.version(doc.body), "name": doc.name, "body": doc.body})
