"""Health > Garmin: what Oscar's Garmin measures, kept by day.

Connecting signs in to Garmin Connect (sources/garmin.py) and records the
link. A sync then fetches each day of a window, today's included, and keeps
its figures (GarminDay) and its activities (GarminActivity): the first sync
reaches `backfill_days` back, and each later one goes from the day before
its last sync, so yesterday settles and a gap while the app was off is
caught up. Figures are read from Garmin's own payloads here, each
optional: a figure Garmin does not have stays None.

The source is anything shaped as GarminSource, so tests stand in a fake.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import GarminActivity, GarminDay, GarminLink
from app.sources.garmin import GarminError, GarminSignedOut

log = logging.getLogger(__name__)

# Measured energy: the average of the last this many full days worn...
ENERGY_DAYS = 14
# ...once there are at least this many. A day he barely wore it is left out.
ENERGY_MIN_DAYS = 7
WORN_STEPS = 1000


class GarminSource(Protocol):
    def fetch_day(self, day: date) -> dict[str, Any]: ...
    def fetch_activities(self, start: date, end: date) -> list[dict[str, Any]]: ...


# ---- the link ----


def link(db: Session) -> GarminLink | None:
    return db.scalars(select(GarminLink).order_by(GarminLink.id)).first()


def connect(db: Session, full_name: str, now: datetime | None = None) -> GarminLink:
    """Record the link once signed in; a second sign-in replaces the first."""
    db.execute(delete(GarminLink))
    row = GarminLink(full_name=full_name, connected_at=now or datetime.now())
    db.add(row)
    db.flush()
    return row


def disconnect(db: Session) -> None:
    """Forget the link. The days synced stay: they are his history."""
    db.execute(delete(GarminLink))
    db.flush()


# ---- reading Garmin's payloads ----


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _dig(payload: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(payload, dict):
            return None
        payload = payload.get(key)
    return payload


def day_figures(raw: dict[str, Any]) -> dict[str, Any]:
    """A GarminDay's columns from a day's raw parts (source.fetch_day). Only
    the parts present are read, so a part that failed leaves its columns as
    they were."""
    figures: dict[str, Any] = {}
    if "summary" in raw:
        s = raw["summary"] or {}
        figures |= {
            "steps": _int(s.get("totalSteps")),
            "step_goal": _int(s.get("dailyStepGoal")),
            "distance_m": _float(s.get("totalDistanceMeters")),
            "total_kcal": _int(s.get("totalKilocalories")),
            "active_kcal": _int(s.get("activeKilocalories")),
            "moderate_minutes": _int(s.get("moderateIntensityMinutes")),
            "vigorous_minutes": _int(s.get("vigorousIntensityMinutes")),
            "resting_hr": _int(s.get("restingHeartRate")),
            # Garmin writes -1 and -2 for "not enough data".
            "stress_avg": _int(s.get("averageStressLevel")),
            "body_battery_high": _int(s.get("bodyBatteryHighestValue")),
            "body_battery_low": _int(s.get("bodyBatteryLowestValue")),
        }
        if figures["stress_avg"] is not None and figures["stress_avg"] < 0:
            figures["stress_avg"] = None
    if "sleep" in raw:
        dto = _dig(raw["sleep"], "dailySleepDTO") or {}
        overall = _dig(dto, "sleepScores", "overall") or {}
        figures |= {
            "sleep_seconds": _int(dto.get("sleepTimeSeconds")),
            "deep_seconds": _int(dto.get("deepSleepSeconds")),
            "light_seconds": _int(dto.get("lightSleepSeconds")),
            "rem_seconds": _int(dto.get("remSleepSeconds")),
            "awake_seconds": _int(dto.get("awakeSleepSeconds")),
            "sleep_score": _int(overall.get("value")),
            "sleep_quality": overall.get("qualifierKey") or None,
        }
    if "hrv" in raw:
        summary = _dig(raw["hrv"], "hrvSummary") or {}
        figures |= {
            "hrv_ms": _int(summary.get("lastNightAvg")),
            "hrv_week_ms": _int(summary.get("weeklyAvg")),
            "hrv_status": summary.get("status") or None,
        }
    if "readiness" in raw:
        ready = raw["readiness"]
        if isinstance(ready, list):  # a day's snapshots: the first is the morning's
            ready = ready[0] if ready else None
        ready = ready or {}
        figures |= {
            "readiness": _int(ready.get("score")),
            "readiness_level": ready.get("level") or None,
        }
    return figures


def activity_fields(raw: dict[str, Any]) -> dict[str, Any] | None:
    """A GarminActivity's columns from Garmin's activity, or None when it
    has no id or start to keep it by."""
    garmin_id = _int(raw.get("activityId"))
    started = raw.get("startTimeLocal")
    if garmin_id is None or not started:
        return None
    try:
        start = datetime.fromisoformat(str(started)).replace(microsecond=0)
    except ValueError:
        return None
    return {
        "garmin_id": garmin_id,
        "day": start.date(),
        "start": start,
        "name": (raw.get("activityName") or "").strip(),
        "kind": _dig(raw, "activityType", "typeKey") or "",
        "duration_s": _int(raw.get("duration")),
        "distance_m": _float(raw.get("distance")) or None,
        "kcal": _int(raw.get("calories")),
        "avg_hr": _int(raw.get("averageHR")),
        "max_hr": _int(raw.get("maxHR")),
    }


# ---- syncing ----


def window(db: Session, today: date, backfill_days: int) -> tuple[date, date]:
    """The days a sync fetches: from the day before the last sync (the day
    before yesterday at least, so yesterday settles and last night's sleep
    lands), or `backfill_days` back the first time; never further back."""
    earliest = today - timedelta(days=backfill_days - 1)
    row = link(db)
    if row is None or row.synced_at is None:
        return earliest, today
    start = min(row.synced_at.date(), today) - timedelta(days=1)
    return max(earliest, min(start, today - timedelta(days=1))), today


def keep_day(db: Session, day: date, raw: dict[str, Any], now: datetime) -> GarminDay:
    row = db.scalars(select(GarminDay).where(GarminDay.day == day)).first()
    if row is None:
        row = GarminDay(day=day)
        db.add(row)
    for name, value in day_figures(raw).items():
        setattr(row, name, value)
    row.synced_at = now
    db.flush()
    return row


def keep_activities(db: Session, start: date, end: date, found: list[dict[str, Any]]) -> None:
    """The window's activities as Garmin has them now: new ones added,
    changed ones updated, and ones deleted on Garmin deleted here."""
    wanted = {}
    for raw in found:
        fields = activity_fields(raw)
        if fields and start <= fields["day"] <= end:
            wanted[fields["garmin_id"]] = fields
    kept = db.scalars(
        select(GarminActivity).where(GarminActivity.day >= start, GarminActivity.day <= end)
    ).all()
    for row in kept:
        if row.garmin_id not in wanted:
            db.delete(row)
    by_id = {
        row.garmin_id: row
        for row in db.scalars(
            select(GarminActivity).where(GarminActivity.garmin_id.in_(list(wanted)))
        )
    }
    for garmin_id, fields in wanted.items():
        row = by_id.get(garmin_id)
        if row is None:
            db.add(GarminActivity(**fields))
        else:
            for name, value in fields.items():
                setattr(row, name, value)
    db.flush()


def sync(
    db: Session, source: GarminSource, today: date, *, backfill_days: int,
    now: datetime | None = None,
) -> tuple[date, date]:
    """Fetch the window's days and activities and keep them; the link notes
    how it went. Returns the window. A Garmin error is recorded on the link
    (and raised), what was kept before it staying kept."""
    now = now or datetime.now()
    start, end = window(db, today, backfill_days)
    row = link(db)
    try:
        day = start
        while day <= end:
            keep_day(db, day, source.fetch_day(day), now)
            day += timedelta(days=1)
        keep_activities(db, start, end, source.fetch_activities(start, end))
    except GarminError as exc:
        if row is not None:
            row.sync_error = str(exc)
            db.flush()
        raise
    if row is not None:
        row.synced_at, row.sync_error = now, ""
        db.flush()
    return start, end


class Syncing:
    """The sync running in the background, one at a time: the scheduler's,
    or one asked for from the page."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, work: Callable[[], None]) -> bool:
        """Run `work` in its own thread unless a sync already runs."""
        with self._lock:
            if self.running:
                return False
            self._thread = threading.Thread(target=work, name="garmin-sync", daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        """Until the sync running in its own thread, if any, is done."""
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def run_here(self, work: Callable[[], None]) -> bool:
        """Run `work` on this thread (the scheduler's) unless one runs."""
        with self._lock:
            if self.running:
                return False
            self._thread = threading.current_thread()
        try:
            work()
        finally:
            with self._lock:
                self._thread = None
        return True


syncing = Syncing()


def run_sync(
    factory: Callable[[], Session], source: GarminSource, today: date, backfill_days: int
) -> None:
    """A whole sync in its own session, committed as it went: for a thread."""
    with factory() as db:
        if link(db) is None:
            return
        try:
            start, end = sync(db, source, today, backfill_days=backfill_days)
            log.info("Garmin sync: %s to %s", start, end)
        except GarminSignedOut as exc:
            log.warning("Garmin sync: %s", exc)
        except GarminError as exc:
            log.warning("Garmin sync failed: %s", exc)
        except Exception:
            log.exception("Garmin sync crashed")
            db.rollback()
            row = link(db)
            if row is not None:
                row.sync_error = "The sync stopped on an error. It is in the app's log."
        db.commit()


# ---- reading ----


def day(db: Session, on: date) -> GarminDay | None:
    return db.scalars(select(GarminDay).where(GarminDay.day == on)).first()


def has_days(db: Session) -> bool:
    return db.scalars(select(GarminDay.id).limit(1)).first() is not None


def days(db: Session, start: date, end: date) -> list[GarminDay]:
    """The days kept from `start` to `end`, oldest first."""
    return list(db.scalars(
        select(GarminDay).where(GarminDay.day >= start, GarminDay.day <= end)
        .order_by(GarminDay.day)
    ))


def activities(db: Session, start: date, end: date) -> list[GarminActivity]:
    """The activities from `start` to `end`, in the order he did them."""
    return list(db.scalars(
        select(GarminActivity)
        .where(GarminActivity.day >= start, GarminActivity.day <= end)
        .order_by(GarminActivity.start)
    ))


def measured_energy(db: Session, today: date) -> dict[str, Any] | None:
    """What he burns a day, as his Garmin measured it: the average total
    energy of his last ENERGY_DAYS full days worn (today is not full yet),
    once there are ENERGY_MIN_DAYS of them. None until then."""
    worn = [
        d for d in days(db, today - timedelta(days=ENERGY_DAYS), today - timedelta(days=1))
        if d.total_kcal and (d.steps or 0) >= WORN_STEPS
    ]
    if len(worn) < ENERGY_MIN_DAYS:
        return None
    return {
        "kcal": int(round(sum(d.total_kcal for d in worn) / len(worn), -1)),
        "days": len(worn),
    }


DAY_FIELDS = (
    "steps", "step_goal", "distance_m", "total_kcal", "active_kcal", "moderate_minutes",
    "vigorous_minutes", "resting_hr", "stress_avg", "body_battery_high", "body_battery_low",
    "sleep_seconds", "deep_seconds", "light_seconds", "rem_seconds", "awake_seconds",
    "sleep_score", "sleep_quality", "hrv_ms", "hrv_week_ms", "hrv_status", "readiness",
    "readiness_level",
)


def activity_dict(a: GarminActivity) -> dict[str, Any]:
    return {
        "start": a.start.isoformat(timespec="minutes"), "name": a.name, "kind": a.kind,
        "duration_min": round(a.duration_s / 60) if a.duration_s is not None else None,
        "distance_km": round(a.distance_m / 1000, 2) if a.distance_m else None,
        "kcal": a.kcal, "avg_hr": a.avg_hr, "max_hr": a.max_hr,
    }


def report(db: Session, start: date, end: date) -> list[dict[str, Any]]:
    """Each day kept from `start` to `end`, oldest first, as Claude reads it:
    its figures (sleep is the night that ended that morning) and its
    activities. A day with neither is left out."""
    by_day: dict[date, dict[str, Any]] = {}
    for d in days(db, start, end):
        figures = {name: getattr(d, name) for name in DAY_FIELDS}
        if any(value is not None for value in figures.values()):
            by_day[d.day] = figures
    acts: dict[date, list[dict[str, Any]]] = {}
    for a in activities(db, start, end):
        acts.setdefault(a.day, []).append(activity_dict(a))
    return [
        {"day": on.isoformat(), **by_day.get(on, {}), "activities": acts.get(on, [])}
        for on in sorted(set(by_day) | set(acts))
    ]
