"""What Today's stay pane writes (stays.js): an item of the day's stay set,
added or taken away, the last stay taken again, the day's stay carried on
to the days after it, and days put back as they were (Undo). Each answers
the day's stay as the pane draws it (stays.standing)."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from app.db import DbSession
from app.services import DomainError
from app.services import stays as stays_svc

router = APIRouter(include_in_schema=False)


def _answer(db: DbSession, day: date, **more: object) -> JSONResponse:
    db.commit()
    return JSONResponse({"stay": stays_svc.standing(db, day), **more})


@router.post("/ui/stays/{day}/item")
def set_stay_item(
    db: DbSession,
    day: date,
    name: Annotated[str, Form()],
    value: Annotated[str | None, Form()] = None,
    done: Annotated[bool | None, Form()] = None,
):
    """An item's value, or whether it is sorted (a day with no stay gets one)."""
    stays_svc.set_item(db, day, name, value=value, done=done)
    return _answer(db, day)


@router.post("/ui/stays/{day}/add")
def add_stay_item(db: DbSession, day: date, name: Annotated[str, Form()]):
    """A new item, at the stay's end."""
    stays_svc.add_item(db, day, name)
    return _answer(db, day)


@router.post("/ui/stays/{day}/remove")
def remove_stay_item(db: DbSession, day: date, name: Annotated[str, Form()]):
    """An item taken away (its last gone, the day has no stay)."""
    stays_svc.remove_item(db, day, name)
    return _answer(db, day)


@router.post("/ui/stays/{day}/same")
def same_stay(db: DbSession, day: date):
    """The last stay before the day, taken again."""
    stays_svc.same_as_before(db, day)
    return _answer(db, day)


@router.post("/ui/stays/{day}/fill")
def fill_stay(db: DbSession, day: date, until: Annotated[date, Form()]):
    """The day's stay carried on to every day after it up to `until`; with
    what those days had before, for Undo to put back."""
    was = stays_svc.fill(db, day, until)
    return _answer(db, day, days=len(was), was={d.isoformat(): items for d, items in was.items()})


@router.post("/ui/stays/{day}/put")
def put_stays(db: DbSession, day: date, stays: Annotated[str, Form()]):
    """Days put back as they were, {day: [items]} as JSON (Undo); answers
    the page's day's stay."""
    try:
        given = json.loads(stays)
        if not isinstance(given, dict):
            raise ValueError
        days = {date.fromisoformat(d): items for d, items in given.items()}
    except ValueError as exc:
        raise DomainError("Expected {day: [items]}") from exc
    stays_svc.put(db, days)
    return _answer(db, day)
