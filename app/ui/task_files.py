"""A task's files on its page (app.services.task_files): one opened in the
page's document, written there and saved as it is written (doc-editor.js),
renamed and deleted from its heading; one added from the map."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.db import DbSession
from app.models import Task
from app.services import DomainError, everyday, task_files
from app.ui.task_map_view import map_ctx
from app.ui.task_run_view import run_ctx
from app.ui.views import sheet_ctx, templates

router = APIRouter(include_in_schema=False)


def file_href(task_id: int, path: str) -> str:
    return f"/tasks/{task_id}/files/{quote(path)}"


def _task(db: DbSession, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "No such task: it may have been deleted")
    return task


def _read(task: Task, path: str) -> tuple[str, str]:
    try:
        return task_files.read(task.id, path)
    except DomainError as exc:
        raise HTTPException(404, "No such file: it may have been deleted") from exc


@router.get("/tasks/{task_id}/files/{path:path}")
def task_file_page(request: Request, db: DbSession, task_id: int, path: str):
    """A file of the task's, on the task's page in place of its description:
    its map, its sidebar, and the file written as it reads."""
    task = _task(db, task_id)
    body, full = _read(task, path)
    today = date.today()
    folder = task_files.folder_of(task.id)
    return templates.TemplateResponse(
        request,
        "task.html",
        {
            "request": request,
            "active": "task",
            "today": today,
            "sheet": sheet_ctx(db, task, today),
            "back": {"href": f"/tasks/{task.id}", "label": task.title},
            "run": run_ctx(task, today),
            "map": map_ctx(task, today, open_file=full),
            "file": {
                "path": full,
                "name": full.rpartition("/")[2],
                "body": body,
                "version": everyday.version(body),
                "on_disk": str(folder.joinpath(*full.split("/"))) if folder else "",
            },
        },
    )


@router.post("/ui/tasks/{task_id}/files")
def add_file(db: DbSession, task_id: int, path: Annotated[str, Form()]) -> Response:
    """A new file (a path names folders for it), opened to be written."""
    full = task_files.create(_task(db, task_id), path)
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = file_href(task_id, full)
    return response


@router.post("/ui/tasks/{task_id}/file")
def save_file(
    db: DbSession,
    task_id: int,
    path: Annotated[str, Form()],
    body: Annotated[str | None, Form()] = None,
    name: Annotated[str | None, Form()] = None,
    base: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    """A file saved as it is written (doc-editor.js), its words written over
    the copy of version `base`, or renamed from its heading: answered with
    its version, name and page now, or 409 with the file's version when it
    was written elsewhere since."""
    task = _task(db, task_id)
    try:
        if body is not None:
            task_files.write(task.id, path, body, base)
    except task_files.FileChanged as exc:
        return JSONResponse({"detail": str(exc), "version": exc.version}, status_code=409)
    if name:
        path = task_files.rename(task.id, path, name)
    words, full = task_files.read(task.id, path)
    return JSONResponse(
        {
            "version": everyday.version(words),
            "name": full.rpartition("/")[2],
            "path": full,
            "href": file_href(task.id, full),
        }
    )


@router.get("/ui/tasks/{task_id}/file")
def latest_file(db: DbSession, task_id: int, path: str) -> JSONResponse:
    """The file as it is now, for its page to show a version written
    elsewhere (doc-editor.js)."""
    words, full = _read(_task(db, task_id), path)
    return JSONResponse(
        {"version": everyday.version(words), "name": full.rpartition("/")[2], "body": words}
    )


@router.post("/ui/tasks/{task_id}/file/delete")
def delete_file(db: DbSession, task_id: int, path: Annotated[str, Form()]) -> Response:
    """A file deleted; the page goes back to the task's description."""
    task_files.delete(_task(db, task_id).id, path)
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = f"/tasks/{task_id}"
    return response
