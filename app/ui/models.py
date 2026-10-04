"""Models' routes: the page, checking the providers again (asked for, or
when the last check is old), where a provider's CLI is, and the model each
use runs on."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session, sessionmaker

from app.db import DbSession
from app.services import DomainError
from app.services import llm as llm_svc
from app.sources import llm
from app.sources.llm import Probe
from app.ui.models_view import body_ctx
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


def get_probe() -> Probe:
    """How a provider is checked, or a stand-in under test."""
    return llm.probe


Prober = Annotated[Probe, Depends(get_probe)]


def _start_check(db: Session, probe: Probe) -> None:
    """The check, in its own thread and session, on the request's database."""
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    llm_svc.checking.start(lambda: llm_svc.run_check(factory, probe))


def _body(request: Request, db: Session, errors: dict[str, str] | None = None):
    ctx = {"request": request, **body_ctx(db, datetime.now(), errors)}
    return templates.TemplateResponse(request, "partials/models_body.html", ctx)


@router.get("/models")
def models_page(request: Request, db: DbSession, probe: Prober):
    if llm_svc.stale(db):
        _start_check(db, probe)
    ctx = {
        "request": request, "active": "models", "today": date.today(),
        **body_ctx(db, datetime.now()),
    }
    return templates.TemplateResponse(request, "models.html", ctx)


@router.get("/ui/models")
def models_body(request: Request, db: DbSession):
    # Polled while a check runs.
    return _body(request, db)


@router.post("/ui/models/check")
def models_check(request: Request, db: DbSession, probe: Prober):
    _start_check(db, probe)
    return _body(request, db)


@router.post("/ui/models/cli")
def models_cli(
    request: Request, db: DbSession, probe: Prober,
    provider: Annotated[str, Form()], path: Annotated[str, Form()] = "",
):
    try:
        llm_svc.set_cli(db, provider, path)
    except DomainError as exc:
        db.rollback()
        return _body(request, db, {provider: str(exc)})
    db.commit()
    _start_check(db, probe)
    return _body(request, db)


@router.post("/ui/models/use")
def models_use(
    request: Request, db: DbSession,
    use: Annotated[str, Form()], model: Annotated[str, Form()], effort: Annotated[str, Form()] = "",
):
    provider, _, model_id = model.partition(":")
    llm_svc.choose(db, use, provider, model_id, effort)
    db.commit()
    return _body(request, db)
