"""Health > Garmin's routes: a day's page and its sheet, connecting (email
and password, then Garmin's code when it asks for one), syncing, and
disconnecting."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import DbSession
from app.services import garmin as garmin_svc
from app.sources.garmin import GarminConnect, GarminError, account
from app.ui.garmin_view import account_ctx, garmin_page_ctx
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


def get_garmin() -> GarminConnect:
    """Oscar's Garmin Connect account, or a stand-in under test."""
    return account()


Garmin = Annotated[GarminConnect, Depends(get_garmin)]


@router.get("/garmin")
def garmin_today(request: Request, db: DbSession, garmin: Garmin):
    return _page(request, db, garmin, date.today())


@router.get("/garmin/{day}")
def garmin_day(request: Request, db: DbSession, garmin: Garmin, day: date):
    if day == date.today():
        return RedirectResponse("/garmin", status_code=303)
    return _page(request, db, garmin, day)


def _page(request: Request, db: Session, garmin: GarminConnect, day: date) -> Response:
    ctx = garmin_page_ctx(db, garmin, day, date.today())
    return templates.TemplateResponse(
        request, "garmin.html", {"request": request, "active": "garmin", **ctx}
    )


@router.get("/ui/garmin/{day}/sheet")
def garmin_sheet(request: Request, db: DbSession, garmin: Garmin, day: date):
    ctx = garmin_page_ctx(db, garmin, day, date.today())
    return templates.TemplateResponse(
        request, "partials/garmin_sheet.html", {"request": request, **ctx}
    )


def _account(
    request: Request, db: Session, garmin: GarminConnect, error: str = "", email: str = ""
) -> Response:
    ctx = {
        "request": request, **account_ctx(db, garmin, date.today()), "error": error,
        "email": email,
    }
    return templates.TemplateResponse(request, "partials/garmin_account.html", ctx)


def _start_sync(db: Session, garmin: GarminConnect) -> None:
    """The sync, in its own thread and session, on the request's database."""
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    backfill = get_settings().garmin.backfill_days
    garmin_svc.syncing.start(
        lambda: garmin_svc.run_sync(factory, garmin, date.today(), backfill)
    )


def _connected(db: Session, garmin: GarminConnect, full_name: str) -> Response:
    """Signed in: the link recorded, the first sync begun, the page drawn
    again around it."""
    garmin_svc.connect(db, full_name)
    db.commit()
    _start_sync(db, garmin)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/ui/garmin/connect")
def garmin_connect(
    request: Request,
    db: DbSession,
    garmin: Garmin,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    try:
        full_name = garmin.sign_in(email, password)
    except GarminError as exc:
        return _account(request, db, garmin, str(exc), email=email)
    if full_name is None:  # Garmin sent a code
        return _account(request, db, garmin)
    return _connected(db, garmin, full_name)


@router.post("/ui/garmin/verify")
def garmin_verify(
    request: Request, db: DbSession, garmin: Garmin, code: Annotated[str, Form()]
):
    try:
        full_name = garmin.verify(code)
    except GarminError as exc:
        return _account(request, db, garmin, str(exc))
    return _connected(db, garmin, full_name)


@router.post("/ui/garmin/cancel")
def garmin_cancel(request: Request, db: DbSession, garmin: Garmin):
    garmin.cancel()
    return _account(request, db, garmin)


@router.post("/ui/garmin/sync")
def garmin_sync(request: Request, db: DbSession, garmin: Garmin):
    if garmin.has_token() and garmin_svc.link(db) is not None:
        _start_sync(db, garmin)
    return _account(request, db, garmin)


@router.get("/ui/garmin/account")
def garmin_account(request: Request, db: DbSession, garmin: Garmin):
    response = _account(request, db, garmin)
    # Asked after a sync (its poll): once it is done, the day is drawn again.
    if request.headers.get("HX-Trigger") == "garmin-account" and not garmin_svc.syncing.running:
        response.headers["HX-Trigger"] = "garmin:synced"
    return response


@router.post("/ui/garmin/disconnect")
def garmin_disconnect(db: DbSession, garmin: Garmin):
    garmin.forget()
    garmin_svc.disconnect(db)
    db.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})
