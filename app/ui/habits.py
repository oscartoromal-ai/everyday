"""Habits' routes: the Habits page and a habit's own, and what Today's
habits pane and those pages write: a new habit, a day ticked or its
comment, a habit's days, its file's words (doc-editor.js), its name, and
its deletion."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.db import DbSession
from app.models import Habit
from app.services import documents, everyday, habit_md, settling
from app.services import habits as habits_svc
from app.ui.habits_view import file_of, href, index_ctx, page_ctx, pane_entry
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


@router.get("/habits")
def habits_page(request: Request, db: DbSession):
    return templates.TemplateResponse(
        request,
        "habits.html",
        {
            "request": request,
            "active": "habits",
            "today": date.today(),
            **index_ctx(db, date.today()),
        },
    )


@router.get("/habits/{slug}")
def habit_page(request: Request, db: DbSession, slug: str):
    habit = habits_svc.find(db, slug.lower())
    if habit is None:
        raise HTTPException(404, f"No habit {slug}")
    return templates.TemplateResponse(
        request,
        "habit.html",
        {
            "request": request,
            "active": "habits",
            "today": date.today(),
            **page_ctx(db, habit, date.today()),
        },
    )


def _entry(db: DbSession, habit: Habit, on: date | None) -> JSONResponse:
    """The habit as Today's pane draws it on its day (`on`)."""
    today = date.today()
    return JSONResponse({"habit": pane_entry(db, habit, on or today, today)})


@router.post("/ui/habits")
def new_habit(
    request: Request,
    db: DbSession,
    name: Annotated[str, Form()],
    on: Annotated[date | None, Form()] = None,
):
    """A new habit, from Today's pane (answered with it, as the pane draws
    it) or the Habits page (which goes to its page, to say what it is)."""
    habit = habits_svc.create(db, name)
    db.commit()
    if request.headers.get("HX-Request"):
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = href(habit)
        return response
    return _entry(db, habit, on)


@router.post("/ui/habits/{habit_id}/done")
def tick_habit(
    db: DbSession,
    habit_id: int,
    day: Annotated[date, Form()],
    done: Annotated[bool, Form()],
    on: Annotated[date | None, Form()] = None,
):
    """A day ticked, or not (its comment stays: unticked, the day skipped)."""
    habit = habits_svc.get(db, habit_id)
    habits_svc.set_done(db, habit, day, done)
    db.commit()
    return _entry(db, habit, on)


@router.post("/ui/habits/{habit_id}/note")
def comment_habit(
    db: DbSession,
    habit_id: int,
    day: Annotated[date, Form()],
    note: Annotated[str, Form()] = "",
    on: Annotated[date | None, Form()] = None,
):
    """A day's comment, its entry in the habit's log."""
    habit = habits_svc.get(db, habit_id)
    with documents.held(db):
        # What the file says now first: a comment written there meanwhile.
        settling.settle_habit(db, habit)
        habits_svc.set_note(db, habit, day, note)
    return _entry(db, habit, on)


@router.post("/ui/habits/{habit_id}/days")
def set_habit_days(db: DbSession, habit_id: int, days: Annotated[str, Form()] = ""):
    """A habit's days, from its repeat icon: the weekdays it is due, Monday
    0 to Sunday 6, or "" for any day."""
    habit = habits_svc.get(db, habit_id)
    habit.days = habits_svc.clean_days(days)
    db.commit()
    return JSONResponse(
        {"id": habit.id, "days": habit.days, "label": habit_md.days_label(habit.days)}
    )


def _words(db: DbSession, habit: Habit) -> str:
    return habit_md.body(habit.notes, habits_svc.log_of(db, habit))


def _file_answer(db: DbSession, habit: Habit) -> JSONResponse:
    return JSONResponse(
        {
            "version": everyday.version(_words(db, habit)),
            "name": habit.slug,
            "path": habit.slug,
            "href": href(habit),
            "file": file_of(habit),
        }
    )


@router.post("/ui/habits/{habit_id}/file")
def save_habit_file(
    db: DbSession,
    habit_id: int,
    body: Annotated[str | None, Form()] = None,
    name: Annotated[str | None, Form()] = None,
    base: Annotated[str | None, Form()] = None,
    path: Annotated[str | None, Form()] = None,  # noqa: ARG001  (doc-editor.js sends it)
) -> Response:
    """The habit's words saved as they are written on its page (doc-editor.js):
    what it is and its log, written over the copy of version `base`, or 409
    with the version its file has now when that was written elsewhere since;
    or its name, from its heading. Answered as a document is."""
    habit = habits_svc.get(db, habit_id)
    with documents.held(db):
        settling.settle_habit(db, habit)
        if body is not None:
            now = _words(db, habit)
            if base is not None and base != everyday.version(now):
                return JSONResponse(
                    {
                        "detail": "This habit's file was changed elsewhere since.",
                        "version": everyday.version(now),
                    },
                    status_code=409,
                )
            words = habit_md.parse(everyday.plain(body))
            habit.notes = words.notes
            habits_svc.take_log(db, habit, words.log)
        if name is not None:
            habits_svc.rename(db, habit.id, name)
        db.flush()
    return _file_answer(db, habit)


@router.get("/ui/habits/{habit_id}/file")
def latest_habit_file(db: DbSession, habit_id: int) -> JSONResponse:
    """The habit's words as its file has them now (doc-editor.js)."""
    habit = habits_svc.get(db, habit_id)
    with documents.held(db):
        settling.settle_habit(db, habit)
    words = _words(db, habit)
    return JSONResponse({"version": everyday.version(words), "name": habit.slug, "body": words})


@router.get("/ui/habits/{habit_id}/year")
def habit_year(request: Request, db: DbSession, habit_id: int):
    """A habit's half year drawn again (its log written on its page)."""
    habit = habits_svc.get(db, habit_id)
    return templates.TemplateResponse(
        request,
        "partials/habit_year.html",
        {"request": request, **page_ctx(db, habit, date.today())},
    )


@router.post("/ui/habits/{habit_id}/delete")
def delete_habit(db: DbSession, habit_id: int) -> Response:
    """The habit gone, with every day it was ticked; its file to the trash."""
    habits_svc.delete(db, habit_id)
    db.commit()
    response = Response(status_code=204)
    response.headers["HX-Redirect"] = "/habits"
    return response
