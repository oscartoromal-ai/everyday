"""Models as the page draws it: each provider as last checked (its CLI,
who it is signed in as, the models it offers, or what to do), the model
each use runs on, and when it was all last checked."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services import llm as llm_svc
from app.sources.llm import BY_KEY, PROVIDERS, Model, Provider, Status
from app.ui.repositories_view import synced

# A provider's state as its chip says it, and the chip's colour.
STATES = {
    "ready": ("Signed in", "ok"),
    "signed_out": ("Not signed in", "warn"),
    "missing": ("Not installed", "neutral"),
    "failed": ("Needs attention", "err"),
    None: ("Not checked yet", "neutral"),
}


def provider_ctx(
    db: Session, provider: Provider, status: Status | None, error: str = ""
) -> dict[str, Any]:
    label, tone = STATES[status.state if status else None]
    return {
        "key": provider.key,
        "name": provider.name,
        "program": provider.program,
        "command": provider.command,
        "install": provider.install,
        "sign_in": provider.sign_in,
        "state": status.state if status else None,
        "label": label,
        "tone": tone,
        "version": status.version if status else "",
        "account": status.account if status else "",
        "message": status.message if status else "",
        "models": list(status.models) if status else [],
        "configured": llm_svc.cli(db, provider.key),
        # Where it was found, when it was found by itself (the field's hint).
        "found": status.cli if status and status.cli else "",
        "error": error,
    }


def _option(provider: Provider, model: Model) -> dict[str, str]:
    return {"value": f"{provider.key}:{model.id}", "label": model.name}


def use_ctx(db: Session, use: llm_svc.Use, found: dict[str, Status | None]) -> dict[str, Any]:
    """A use's row: the models it can run on, a group a provider, the one
    chosen, and the efforts that model takes."""
    chosen = llm_svc.choice(db, use.key)
    groups = []
    for key in use.providers:
        provider, status = BY_KEY[key], found.get(key)
        default = status.default_model if status else None
        options = [{
            "value": f"{key}:",
            "label": f"Default · {default.name}" if default else "Default",
        }]
        options += [_option(provider, m) for m in (status.models if status else ())]
        # A model chosen that the last check did not list stays shown.
        if key == chosen.provider and chosen.model and not any(
            o["value"] == f"{key}:{chosen.model}" for o in options
        ):
            options.append({
                "value": f"{key}:{chosen.model}", "label": f"{chosen.model} (not listed)",
            })
        groups.append({"name": provider.name, "options": options})
    status = found.get(chosen.provider)
    model = None
    if status is not None:
        model = status.model(chosen.model) if chosen.model else status.default_model
    takes = model.efforts if model else ()
    efforts = [{"value": e, "label": llm_svc.effort_label(e)} for e in takes]
    own = llm_svc.effort_label(model.default_effort) if model and model.default_effort else ""
    return {
        "key": use.key,
        "label": use.label,
        "hint": use.hint,
        "groups": groups,
        "single": len(groups) == 1,
        "selected": f"{chosen.provider}:{chosen.model or ''}",
        "efforts": efforts,
        "effort": chosen.effort or "",
        "effort_default": f"Default effort ({own})" if own else "Default effort",
    }


def body_ctx(
    db: Session, now: datetime, errors: dict[str, str] | None = None
) -> dict[str, Any]:
    found = llm_svc.statuses(db)
    errors = errors or {}
    checked = [s.checked_at for s in found.values() if s is not None]
    return {
        "providers": [provider_ctx(db, p, found[p.key], errors.get(p.key, "")) for p in PROVIDERS],
        "uses": [use_ctx(db, u, found) for u in llm_svc.uses()],
        "checking": llm_svc.checking.running,
        "checked": synced(min(checked), now) if len(checked) == len(found) else "",
    }


def summary(db: Session | None) -> list[dict[str, str]]:
    """Each provider in a word, for Settings: "Claude", "Signed in"."""
    found = llm_svc.statuses(db) if db is not None else {}
    rows = []
    for provider in PROVIDERS:
        status = found.get(provider.key)
        label, tone = STATES[status.state if status else None]
        rows.append({"name": provider.name, "label": label, "tone": tone})
    return rows
