"""Health > Me's routes: its page, the context health advice needs, and its
form and weigh-ins, saved as they change."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.db import DbSession
from app.services import DomainError
from app.services import health as health_svc
from app.ui.views import me_ctx, templates

router = APIRouter(include_in_schema=False)


@router.get("/me")
def me_page(request: Request, db: DbSession):
    ctx = me_ctx(db, date.today())
    db.commit()  # the profile, begun empty the first time
    return templates.TemplateResponse(
        request, "me.html", {"request": request, "active": "me", "today": date.today(), **ctx}
    )


def _number(value: str, what: str) -> float | None:
    value = value.strip().replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise DomainError(f"{what} should be a number") from None


def _me_partial(request: Request, db: DbSession, template: str) -> HTMLResponse:
    ctx = me_ctx(db, date.today())
    return templates.TemplateResponse(request, template, {"request": request, **ctx})


@router.post("/ui/me")
def save_me(
    request: Request,
    db: DbSession,
    height_cm: Annotated[str, Form()] = "",
    birth_date: Annotated[str, Form()] = "",
    sex: Annotated[str, Form()] = "",
    activity: Annotated[str, Form()] = "",
    goal: Annotated[str, Form()] = "",
    target_weight_kg: Annotated[str, Form()] = "",
    diet: Annotated[str, Form()] = "",
    allergies: Annotated[str, Form()] = "",
    avoids: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    """Me's form, saved whole on each change; answers with what follows from it."""
    try:
        born = date.fromisoformat(birth_date) if birth_date else None
    except ValueError:
        raise DomainError("A birth date is a date") from None
    health_svc.update_profile(
        db,
        height_cm=_number(height_cm, "Height (cm)"),
        birth_date=born,
        sex=sex or None,
        activity=activity or None,
        goal=goal or None,
        target_weight_kg=_number(target_weight_kg, "Target weight (kg)"),
        diet=diet, allergies=allergies, avoids=avoids, notes=notes,
    )
    db.commit()
    return _me_partial(request, db, "partials/me_context.html")


@router.get("/ui/me/context")
def me_context(request: Request, db: DbSession):
    return _me_partial(request, db, "partials/me_context.html")


@router.post("/ui/me/weight")
def log_weight(
    request: Request,
    db: DbSession,
    weight_kg: Annotated[str, Form()],
    day: Annotated[str, Form()] = "",
):
    """A weigh-in (today's unless a day is given); the day's last one is kept."""
    weight = _number(weight_kg, "Weight (kg)")
    if weight is None:
        raise DomainError("Write your weight in kg")
    health_svc.log_weight(db, date.fromisoformat(day) if day else date.today(), weight)
    db.commit()
    response = _me_partial(request, db, "partials/me_weights.html")
    response.headers["HX-Trigger"] = "me:changed"
    return response


@router.post("/ui/me/weight/{day}/delete")
def delete_weight(request: Request, db: DbSession, day: date):
    health_svc.delete_weight(db, day)
    db.commit()
    response = _me_partial(request, db, "partials/me_weights.html")
    response.headers["HX-Trigger"] = "me:changed"
    return response
