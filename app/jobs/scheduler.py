"""APScheduler wiring: background jobs share app code and database sessions.

Jobs land here as their milestones arrive: missed blocks (M4), recurrence
materialization (M5), work-calendar poll (M6), nudges and digest (M7),
backups (M8).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db import get_session_factory, session_scope
from app.models import NudgeType
from app.services import backup as backup_svc
from app.services import blocks as blocks_svc
from app.services import garmin as garmin_svc
from app.services import nudges as nudges_svc
from app.services import push as push_svc
from app.services import recurrence as recurrence_svc
from app.services import work_calendar as work_calendar_svc

log = logging.getLogger(__name__)

# Only genuinely time-sensitive nudge types break through during the day.
BREAK_THROUGH_TYPES = {NudgeType.missed_block}


def run_mark_missed_blocks() -> None:
    with session_scope() as db:
        missed = blocks_svc.mark_missed_blocks(db, datetime.now())
        if missed:
            log.info("Marked %d block(s) missed", len(missed))


def run_materialize_recurrence() -> None:
    with session_scope() as db:
        created = recurrence_svc.materialize_all(db)
        if created:
            log.info("Materialized %d recurrence occurrence(s)", created)


def run_work_calendar_sync() -> None:
    url = get_settings().ics_url
    if not url:
        log.info("Work-calendar sync skipped: no ICS URL configured")
        return
    from app.sources.ics import IcsWorkCalendarSource

    with session_scope() as db:
        stats = work_calendar_svc.sync(db, IcsWorkCalendarSource(url))
        log.info("Work-calendar sync: %s", stats)


def run_nudge_evaluation() -> None:
    now = datetime.now()
    with session_scope() as db:
        created = nudges_svc.evaluate(db, now)
    if not created:
        return
    log.info("Raised %d nudge(s)", len(created))
    if push_svc.in_quiet_hours(now):
        return
    for nudge in created:
        if nudge.type in BREAK_THROUGH_TYPES:
            push_svc.send_push("Personal Calendar", nudge.message)


def run_morning_digest() -> None:
    now = datetime.now()
    with session_scope() as db:
        digest = nudges_svc.build_morning_digest(db, now)
    push_svc.send_push("Morning digest", digest)


def run_daily_backup() -> None:
    settings = get_settings()
    path = backup_svc.run_backup(settings.db_path, settings.backup_dir, settings.backup.retain)
    log.info("Backup snapshot written: %s", path)


def run_garmin_sync() -> None:
    """Fetch the days since the last sync from Garmin Connect, while connected."""
    from app.sources.garmin import account

    garmin = account()
    if not garmin.has_token():
        return
    backfill = get_settings().garmin.backfill_days
    garmin_svc.syncing.run_here(
        lambda: garmin_svc.run_sync(get_session_factory(), garmin, date.today(), backfill)
    )


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_mark_missed_blocks,
        IntervalTrigger(minutes=5),
        id="mark_missed_blocks",
        next_run_time=datetime.now(),  # also run at startup
    )
    scheduler.add_job(
        run_materialize_recurrence,
        CronTrigger(hour=4, minute=0),
        id="materialize_recurrence",
        next_run_time=datetime.now(),  # catch up at startup too
    )
    for poll_time in get_settings().work_calendar.poll_times:
        hour, minute = poll_time.split(":")
        scheduler.add_job(
            run_work_calendar_sync,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id=f"work_calendar_sync_{poll_time.replace(':', '')}",
        )
    scheduler.add_job(
        run_nudge_evaluation,
        IntervalTrigger(minutes=15),
        id="nudge_evaluation",
        next_run_time=datetime.now() + timedelta(seconds=30),  # after the missed-block pass
    )
    digest_hour, digest_minute = get_settings().push.digest_time.split(":")
    scheduler.add_job(
        run_morning_digest,
        CronTrigger(hour=int(digest_hour), minute=int(digest_minute)),
        id="morning_digest",
    )
    scheduler.add_job(
        run_garmin_sync,
        IntervalTrigger(minutes=get_settings().garmin.sync_minutes),
        id="garmin_sync",
        next_run_time=datetime.now() + timedelta(seconds=45),  # catch up at startup too
    )
    scheduler.add_job(
        run_daily_backup,
        CronTrigger(hour=3, minute=30),
        id="daily_backup",
    )
    return scheduler
