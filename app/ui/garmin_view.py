"""Health > Garmin as the page draws it: a day's figures in words, its
sleep, its activities, the fortnight ending on it, and the account."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import GarminActivity, GarminDay
from app.services import garmin as garmin_svc
from app.sources.garmin import GarminConnect

TREND_DAYS = 14


def number(value: int | None) -> str:
    return f"{value:,}" if value is not None else ""


def duration(seconds: int | None) -> str:
    """7 h 32 min, 45 min, 2 h."""
    if seconds is None:
        return ""
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def clock(seconds: int | None) -> str:
    """7:32, for a column."""
    if seconds is None:
        return ""
    hours, minutes = divmod(int(round(seconds / 60)), 60)
    return f"{hours}:{minutes:02d}"


def distance(meters: float | None) -> str:
    if not meters:
        return ""
    if meters < 1000:
        return f"{meters:.0f} m"
    return f"{meters / 1000:.2f}".rstrip("0").rstrip(".") + " km"


def word(key: str | None) -> str:
    """Garmin's key in words: BALANCED -> Balanced, HIGH_STRESS -> High stress."""
    return key.replace("_", " ").capitalize() if key else ""


def when(moment: datetime | None, today: date) -> str:
    if moment is None:
        return ""
    if moment.date() == today:
        return f"{moment:%H:%M} today"
    if moment.date() == today - timedelta(days=1):
        return f"{moment:%H:%M} yesterday"
    return f"{moment:%H:%M}, {moment.day} {moment:%b}"


def _row(label: str, value: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"label": label, "value": value, "detail": detail, "meter": None, "aside": "", **extra}


def figures(d: GarminDay) -> list[dict[str, Any]]:
    """The day's rows, those Garmin had a figure for."""
    rows = []
    if d.steps is not None:
        meter = None
        if d.step_goal:
            meter = min(100, round(100 * d.steps / d.step_goal))
        of = f"of {number(d.step_goal)}" if d.step_goal else ""
        extra = distance(d.distance_m)
        rows.append(_row("Steps", number(d.steps), of, meter=meter, aside=extra))
    if d.total_kcal is not None:
        active = f"{number(d.active_kcal)} active" if d.active_kcal is not None else ""
        rows.append(_row("Energy burned", f"{number(d.total_kcal)} kcal", active))
    if d.moderate_minutes is not None or d.vigorous_minutes is not None:
        moderate, vigorous = d.moderate_minutes or 0, d.vigorous_minutes or 0
        # As Garmin counts them toward its weekly goal: vigorous minutes twice.
        parts = [f"{n} {what}" for n, what in ((moderate, "moderate"), (vigorous, "vigorous")) if n]
        rows.append(_row("Intensity", f"{moderate + 2 * vigorous} min", " · ".join(parts)))
    if d.resting_hr is not None:
        rows.append(_row("Resting HR", f"{d.resting_hr} bpm"))
    if d.stress_avg is not None:
        rows.append(_row("Stress", str(d.stress_avg), "average, of 100"))
    if d.body_battery_high is not None:
        detail = "highest"
        if d.body_battery_low is not None:
            detail += f" · lowest {d.body_battery_low}"
        rows.append(_row("Body battery", str(d.body_battery_high), detail))
    return rows


def sleep(d: GarminDay) -> list[dict[str, Any]]:
    rows = []
    if d.sleep_seconds:
        score = ""
        if d.sleep_score is not None:
            score = f"score {d.sleep_score}"
            if d.sleep_quality:
                score += f" · {word(d.sleep_quality)}"
        rows.append(_row("Slept", duration(d.sleep_seconds), score))
        stages = [
            f"{what} {duration(seconds)}"
            for what, seconds in (
                ("deep", d.deep_seconds), ("light", d.light_seconds),
                ("REM", d.rem_seconds), ("awake", d.awake_seconds),
            )
            if seconds
        ]
        if stages:
            line = " · ".join(stages)
            rows.append(_row("Stages", "", line[0].upper() + line[1:]))
    if d.hrv_ms is not None:
        detail = [word(d.hrv_status)] if d.hrv_status else []
        if d.hrv_week_ms is not None:
            detail.append(f"week's average {d.hrv_week_ms} ms")
        rows.append(_row("HRV", f"{d.hrv_ms} ms", " · ".join(detail)))
    if d.readiness is not None:
        rows.append(_row("Readiness", str(d.readiness), word(d.readiness_level)))
    return rows


def activity(a: GarminActivity) -> dict[str, Any]:
    parts = [
        duration(a.duration_s), distance(a.distance_m),
        f"{number(a.kcal)} kcal" if a.kcal is not None else "",
        f"average {a.avg_hr} bpm" if a.avg_hr else "",
    ]
    return {
        "time": f"{a.start:%H:%M}",
        "name": a.name or word(a.kind) or "Activity",
        "detail": " · ".join(p for p in parts if p),
    }


def trend(db: Session, day: date, today: date) -> list[dict[str, Any]]:
    """The fortnight ending on the day, newest first, a row a day; a day
    with nothing kept keeps its row, empty."""
    first = day - timedelta(days=TREND_DAYS - 1)
    kept = {d.day: d for d in garmin_svc.days(db, first, day)}
    rows = []
    for offset in range(TREND_DAYS):
        on = day - timedelta(days=offset)
        d = kept.get(on)
        rows.append({
            "day": on,
            "label": "Today" if on == today else f"{on:%a} {on.day}",
            "current": on == day,
            "cells": [
                number(d.steps) if d else "",
                number(d.total_kcal) if d else "",
                clock(d.sleep_seconds) if d else "",
                str(d.sleep_score) if d and d.sleep_score is not None else "",
                str(d.resting_hr) if d and d.resting_hr is not None else "",
                str(d.hrv_ms) if d and d.hrv_ms is not None else "",
                str(d.body_battery_high) if d and d.body_battery_high is not None else "",
            ],
        })
    return rows


TREND_COLUMNS = ["steps", "kcal", "sleep", "score", "rest HR", "HRV", "battery"]


def account_ctx(db: Session, account: GarminConnect, today: date) -> dict[str, Any]:
    """The account group: connected (its name, how the last sync went) or
    not (the sign-in, or its code step)."""
    link = garmin_svc.link(db)
    connected = link is not None and account.has_token()
    return {
        "link": link,
        "connected": connected,
        "code_step": not connected and account.waiting_for_code(),
        "running": garmin_svc.syncing.running,
        "synced": when(link.synced_at, today) if link else "",
        # Signed out by Garmin since: why the sign-in is back.
        "signed_out": link is not None and not connected,
    }


def garmin_page_ctx(
    db: Session, account: GarminConnect, day: date, today: date
) -> dict[str, Any]:
    ctx = account_ctx(db, account, today)
    d = garmin_svc.day(db, day)
    has_history = ctx["link"] is not None or garmin_svc.has_days(db)
    return {
        **ctx,
        "day": day,
        "today": today,
        "is_today": day == today,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "has_history": has_history,
        "figures": figures(d) if d else [],
        "sleep": sleep(d) if d else [],
        "activities": [activity(a) for a in garmin_svc.activities(db, day, day)],
        "trend": trend(db, day, today) if has_history else [],
        "trend_columns": TREND_COLUMNS,
    }
