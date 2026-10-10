import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.jobs import scheduler as jobs
from app.models import Event, EventSource
from app.services import work_calendar as work_svc
from app.sources import ExternalEvent
from app.sources.ics import IcsWorkCalendarSource, WorkCalendarUnreachable

FIXTURE = Path(__file__).parent / "fixtures" / "work.ics"
TODAY = date(2026, 8, 30)


class FileSource(IcsWorkCalendarSource):
    def __init__(self, path: Path) -> None:
        super().__init__("http://unused.example/")
        self._path = path

    def _download(self) -> bytes:
        return self._path.read_bytes()


class ListSource:
    def __init__(self, events: list[ExternalEvent]) -> None:
        self._events = events

    def fetch(self, window_start, window_end):  # noqa: ANN001
        return [e for e in self._events if window_start <= e.start < window_end]


def test_ics_source_expands_recurrence_and_exdates(db) -> None:
    source = FileSource(FIXTURE)
    events = source.fetch(datetime(2026, 8, 30), datetime(2026, 9, 6))

    standups = [e for e in events if e.title == "Daily standup"]
    standup_days = {e.start.date() for e in standups}
    # Mon 31.8 through Fri 4.9, minus the EXDATE on Wed 2.9
    assert date(2026, 8, 31) in standup_days
    assert date(2026, 9, 2) not in standup_days
    assert len(standups) == 4
    assert all(e.location == "Teams" for e in standups)

    offsite = next(e for e in events if e.title == "Team offsite")
    assert offsite.all_day

    review = next(e for e in events if e.title == "Quarterly review")
    assert review.location == "Room 4.01"
    assert review.end - review.start == timedelta(minutes=90)


def test_sync_upserts_and_deletes_cancellations(db) -> None:
    base = datetime.combine(TODAY, datetime.min.time()) + timedelta(days=1, hours=9)
    ev = ExternalEvent(
        external_id="a:1", title="Standup", start=base, end=base + timedelta(minutes=15),
        all_day=False, location="Teams",
    )
    other = ExternalEvent(
        external_id="b:1", title="1:1", start=base + timedelta(hours=2),
        end=base + timedelta(hours=3), all_day=False, location="",
    )
    stats = work_svc.sync(db, ListSource([ev, other]), today=TODAY)
    assert stats == {"created": 2, "updated": 0, "deleted": 0}
    rows = list(db.scalars(select(Event).where(Event.source == EventSource.work)))
    assert all(r.read_only for r in rows)

    # Retitled meeting updates in place; cancelled meeting disappears.
    retitled = ExternalEvent(
        external_id="a:1", title="Standup (moved)", start=base,
        end=base + timedelta(minutes=15), all_day=False, location="Teams",
    )
    stats = work_svc.sync(db, ListSource([retitled]), today=TODAY)
    assert stats == {"created": 0, "updated": 1, "deleted": 1}
    row = db.scalars(select(Event).where(Event.source == EventSource.work)).one()
    assert row.title == "Standup (moved)"

    # Idempotent on a no-change run.
    stats = work_svc.sync(db, ListSource([retitled]), today=TODAY)
    assert stats == {"created": 0, "updated": 0, "deleted": 0}


def test_an_unreachable_feed_says_so(monkeypatch) -> None:
    # As on waking, before the network is back: the name does not resolve.
    def offline(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    monkeypatch.setattr(httpx, "get", offline)
    source = IcsWorkCalendarSource("https://calendar.example/work.ics")
    with pytest.raises(WorkCalendarUnreachable):
        source.fetch(datetime(2026, 8, 30), datetime(2026, 9, 6))


POLLS = ["06:30", "12:30", "16:30"]


def test_a_poll_is_due_once_its_time_has_passed() -> None:
    assert work_svc.poll_due(POLLS, None, datetime(2026, 10, 10, 9, 0))
    morning = datetime(2026, 10, 10, 6, 31)
    assert not work_svc.poll_due(POLLS, morning, datetime(2026, 10, 10, 12, 29))
    assert work_svc.poll_due(POLLS, morning, datetime(2026, 10, 10, 12, 30))
    # Asleep through the day's polls: one poll on waking, not one for each.
    woke = datetime(2026, 10, 10, 19, 40)
    assert work_svc.poll_due(POLLS, datetime(2026, 10, 9, 16, 31), woke)
    assert not work_svc.poll_due(POLLS, woke, woke + timedelta(minutes=5))
    # Past midnight, yesterday's last poll still counts.
    assert work_svc.poll_due(POLLS, datetime(2026, 10, 9, 12, 31), datetime(2026, 10, 10, 1, 0))
    assert not work_svc.poll_due([], None, datetime(2026, 10, 10, 9, 0))


@pytest.fixture
def work_feed(tmp_path, monkeypatch):  # noqa: ANN201
    """A work calendar configured, its feed served from the fixture unless
    `offline` is set, and the job's last poll forgotten."""
    url_file = tmp_path / "ics-url.txt"
    url_file.write_text("https://calendar.example/work.ics", encoding="utf-8")
    monkeypatch.setattr(get_settings().work_calendar, "ics_url_file", str(url_file))
    monkeypatch.setattr(jobs, "_work_calendar_polled", None)
    feed = {"offline": False, "gets": 0}

    def get(url, **kwargs):  # noqa: ANN001, ANN003, ANN202
        feed["gets"] += 1
        if feed["offline"]:
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")
        return httpx.Response(200, content=FIXTURE.read_bytes(), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    return feed


def test_a_poll_on_waking_offline_is_tried_again_once_back(app_db, work_feed, caplog) -> None:
    work_feed["offline"] = True
    jobs.run_work_calendar_sync()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("not reached" in r.getMessage() for r in caplog.records)

    work_feed["offline"] = False
    jobs.run_work_calendar_sync()
    with app_db() as db:
        assert db.scalars(select(Event).where(Event.source == EventSource.work)).first()

    # Reached, it waits for the next poll time.
    jobs.run_work_calendar_sync()
    assert work_feed["gets"] == 2
