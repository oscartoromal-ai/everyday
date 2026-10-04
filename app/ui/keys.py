"""Keyboard: every action a key does and its keys (app/services/keys.py),
each changed, taken away or put back to its default here, kept in keys.toml.
The same, as JSON, for anything else that sets them: GET /ui/keys, and PUT
or DELETE /ui/keys/<action>."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.services import keys as keys_svc
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


def _state() -> dict:
    keymap = keys_svc.load()
    return {**keys_svc.listing(keymap), "map": keys_svc.client_map(keymap)}


@router.get("/keys")
def keys_page(request: Request):
    return templates.TemplateResponse(
        request,
        "keys.html",
        {"request": request, "active": "keys", "today": date.today(), "listing": _state()},
    )


@router.get("/ui/keys")
def keys_json() -> dict:
    """Every action by scope, its keys, its defaults and any clash; the file
    they are kept in, and what in it could not be used."""
    return _state()


@router.get("/ui/keys/list")
def keys_list(request: Request):
    """Keyboard's list drawn again, after a change."""
    return templates.TemplateResponse(
        request, "partials/keys_list.html", {"request": request, "listing": _state()}
    )


class Keys(BaseModel):
    keys: list[str]


@router.put("/ui/keys/{action_id}")
def set_keys(action_id: str, body: Keys) -> dict:
    """An action's keys, all of them ([] for none)."""
    keys_svc.save(action_id, body.keys)
    return _state()


@router.delete("/ui/keys/{action_id}")
def reset_keys(action_id: str) -> dict:
    """An action's keys back to its defaults."""
    keys_svc.save(action_id, None)
    return _state()


@router.delete("/ui/keys")
def reset_every_key() -> dict:
    keys_svc.reset_all()
    return _state()
