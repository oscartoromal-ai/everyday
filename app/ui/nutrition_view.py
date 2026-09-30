"""View-models for Nutrition: a day's log read from its file, against the
plan's targets, and the day's chat with Claude."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from markupsafe import Markup, escape
from sqlalchemy.orm import Session

from app.models import NutritionRole
from app.services import nutrition as nutrition_svc
from app.services import nutrition_chat as chat_svc
from app.services.nutrition import NUTRIENTS, NutritionFileError, Target


def amount(value: float, unit: str) -> str:
    """A nutrient's figure as read: kcal whole, with thousands; grams whole,
    or to a tenth under 10 when it has one."""
    if unit == "kcal" or value >= 10 or value == int(value):
        return f"{round(value):,}"
    return f"{value:.1f}"


def _total_row(key: str, eaten: float, with_planned: float, target: Target | None) -> dict:
    label, unit = NUTRIENTS[key]
    planned = with_planned - eaten
    row: dict[str, Any] = {
        "key": key, "label": label, "unit": unit,
        "eaten": amount(eaten, unit),
        "planned": amount(planned, unit) if planned > 0 else None,
        "target": None, "badge": None, "eaten_pct": 0, "planned_pct": 0,
    }
    if target is None:
        return row
    words = {"aim": "of", "min": "of at least", "max": "of at most"}[target.kind]
    row["target"] = f"{words} {amount(target.value, unit)} {unit}"
    # The meter: the target is its full width; what is eaten fills it in
    # ink, and what is planned follows on in steel.
    row["eaten_pct"] = min(100.0, round(100 * eaten / target.value, 1))
    row["planned_pct"] = min(100.0 - row["eaten_pct"], round(100 * planned / target.value, 1))
    if target.kind == "max" and with_planned > target.value:
        row["badge"] = ("err", "Over") if eaten > target.value else ("warn", "Over, with planned")
    return row


# The meals' columns, named short.
COLUMNS = {"kcal": "kcal", "protein_g": "protein", "fat_g": "fat", "sat_fat_g": "sat fat",
           "carbs_g": "carbs", "fibre_g": "fibre"}

# A body line: a list item ("- words"), or a table row ("| a | b |").
_BULLET = re.compile(r"^\s*[-*]\s+")


def _sections(body: str) -> list[dict]:
    """The log's Markdown as the sheet draws it: a group per "## " section
    (what comes before the first, "Notes"), a row per line, since the files
    keep one sentence to a line. A list item is a bulleted row; a table,
    lines together, is one row."""
    sections: list[dict] = []
    current: dict | None = None
    table: list[str] = []

    def close_table() -> None:
        if table and current is not None:
            html = Markup(nutrition_svc.render_markdown("\n".join(table)))
            current["rows"].append({"kind": "block", "html": html})
        table.clear()

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            if current is None:
                current = {"title": "Notes", "rows": []}
                sections.append(current)
            table.append(stripped)
            continue
        close_table()
        if not stripped:
            continue
        if stripped.startswith("#"):
            current = {"title": stripped.lstrip("#").strip() or "Notes", "rows": []}
            sections.append(current)
            continue
        if current is None:
            current = {"title": "Notes", "rows": []}
            sections.append(current)
        kind = "bullet" if _BULLET.match(stripped) else "text"
        text = _BULLET.sub("", stripped) if kind == "bullet" else stripped
        current["rows"].append({"kind": kind, "html": Markup(nutrition_svc.render_inline(text))})
    close_table()
    return [s for s in sections if s["rows"]]


def log_ctx(folder: Path, day: date) -> dict[str, Any]:
    """A day's log as the sheet draws it: the day's totals against the
    plan's targets, its meals item by item, and its notes; or why its file
    cannot be read."""
    ctx: dict[str, Any] = {
        "file": f"log/{day.isoformat()}.md", "error": None, "targets_error": None,
        "log": None, "totals": [], "meals": [], "sections": [],
        "columns": list(COLUMNS.values()),
    }
    try:
        targets = nutrition_svc.read_targets(folder)
    except NutritionFileError as exc:
        targets, ctx["targets_error"] = {}, str(exc)
    try:
        log = nutrition_svc.read_day(folder, day)
    except NutritionFileError as exc:
        ctx["error"] = str(exc)
        return ctx
    if log is None:
        return ctx
    ctx["log"] = log
    eaten, with_planned = log.totals(planned=False), log.totals(planned=True)
    ctx["totals"] = [
        _total_row(key, eaten[key], with_planned[key], targets.get(key)) for key in NUTRIENTS
    ]
    for meal in log.meals:
        sums = dict.fromkeys(NUTRIENTS, 0.0)
        items = []
        for item in meal.items:
            for key in NUTRIENTS:
                sums[key] += getattr(item, key)
            items.append({
                "food": item.food, "amount": item.amount, "assumed": item.assumed,
                "cells": [amount(getattr(item, key), unit) for key, (_, unit) in NUTRIENTS.items()],
            })
        ctx["meals"].append({
            "name": meal.name, "planned": meal.status == "planned", "entries": items,
            "cells": [amount(sums[key], unit) for key, (_, unit) in NUTRIENTS.items()],
        })
    ctx["sections"] = _sections(log.body)
    return ctx


def _message_html(text: str, role: NutritionRole) -> Markup:
    if role == NutritionRole.claude:
        return Markup(nutrition_svc.render_markdown(text))
    # Oscar's words as he wrote them, his line breaks kept.
    lines = Markup("<br>").join(escape(line) for line in text.splitlines())
    return Markup("<p>") + lines + Markup("</p>")


def chat_ctx(db: Session, day: date) -> dict[str, Any]:
    """The day's chat, and the answer still being written, if one is."""
    run = chat_svc.running(day)
    pending = None
    if run is not None:
        statuses = [e["text"] for e in run.events if e["type"] == "status"]
        said = "".join(e["text"] for e in run.events if e["type"] == "text")
        pending = {"status": statuses[-1] if statuses else "Thinking", "text": said}
    return {
        "messages": [
            {
                "role": m.role.value, "time": m.created_at.strftime("%H:%M"), "failed": m.failed,
                "html": _message_html(m.text, m.role),
            }
            for m in chat_svc.messages(db, day)
        ],
        "pending": pending,
    }


def nutrition_page_ctx(db: Session, folder: Path, day: date, today: date) -> dict[str, Any]:
    return {
        "day": day,
        "is_today": day == today,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "nutrition": log_ctx(folder, day),
        "chat": chat_ctx(db, day),
    }
