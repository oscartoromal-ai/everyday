import threading
from datetime import date, datetime, timedelta

import pytest
from apscheduler.job import Job

from app.config import get_settings
from app.jobs import scheduler as jobs
from app.services import backup as backup_svc


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):  # noqa: ANN201
    """The backups written to a throwaway folder."""
    monkeypatch.setattr(get_settings().backup, "dir", str(tmp_path / "backups"))
    return get_settings().backup_dir


@pytest.fixture
def ran(monkeypatch):  # noqa: ANN201
    """Each job's run recorded instead of done, by its function's name."""
    runs: dict[str, threading.Event] = {}
    for name in [n for n in vars(jobs) if n.startswith("run_")]:
        runs[name] = threading.Event()
        monkeypatch.setattr(jobs, name, runs[name].set)
    return runs


def test_a_run_missed_while_the_machine_slept_runs_on_waking(ran, backup_dir) -> None:
    # Today's snapshot is there, so only the 03:30 run is due: two hours
    # late, as when the machine slept through it.
    backup_dir.mkdir(parents=True)
    backup_svc.snapshot_path(backup_dir, date.today()).touch()
    scheduler = jobs.create_scheduler()
    scheduler.start(paused=True)
    try:
        for job in scheduler.get_jobs():
            job.modify(next_run_time=datetime.now().astimezone() + timedelta(days=1))
        scheduler.get_job("daily_backup").modify(
            next_run_time=datetime.now().astimezone() - timedelta(hours=2)
        )
        scheduler.resume()
        assert ran["run_daily_backup"].wait(5)
    finally:
        scheduler.shutdown(wait=False)


def started(job_id: str) -> Job:
    """The job as a scheduler started now holds it."""
    scheduler = jobs.create_scheduler()
    scheduler.start(paused=True)
    try:
        return scheduler.get_job(job_id)
    finally:
        scheduler.shutdown(wait=False)


def next_backup() -> datetime:
    """When a scheduler started now would first take a snapshot."""
    return started("daily_backup").next_run_time


def test_a_day_without_its_snapshot_takes_one_soon_after_starting(backup_dir) -> None:
    assert next_backup() <= datetime.now().astimezone() + timedelta(minutes=5)


def test_a_day_with_its_snapshot_waits_for_the_night(backup_dir) -> None:
    backup_dir.mkdir(parents=True)
    backup_svc.snapshot_path(backup_dir, date.today()).touch()
    assert (next_backup().hour, next_backup().minute) == (3, 30)


def test_the_morning_digest_is_not_sent_in_the_afternoon() -> None:
    # Woken late, the digest is dropped rather than sent hours after the
    # morning it was for.
    job = started("morning_digest")
    assert job.misfire_grace_time is not None
    assert job.misfire_grace_time <= 3 * 60 * 60
