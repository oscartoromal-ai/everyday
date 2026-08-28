from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.models import Event, EventSource
from app.services import work_calendar as work_svc
from app.sources import ExternalEvent
from app.sources.ics import IcsWorkCalendarSource

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
