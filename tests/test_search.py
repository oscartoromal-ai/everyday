"""The command menu's search (app.services.search): tasks, projects, events
and the days' notes whose words hold what was typed."""

from datetime import date, datetime, time, timedelta

from app.models import Event, EventSource, TaskStatus
from app.services import notebook as notebook_svc
from app.services import projects as projects_svc
from app.services import search as search_svc
from app.services import tasks as tasks_svc

TODAY = date.today()
NOW = datetime.combine(TODAY, time(12))


def test_short_words_find_nothing(db) -> None:
    tasks_svc.create_task(db, title="Taxes")
    assert search_svc.search(db, "t", NOW)["tasks"] == []


def test_tasks_open_first_and_by_their_words_or_description(db) -> None:
    done = tasks_svc.create_task(db, title="Plan my taxes")
    tasks_svc.set_status(db, done.id, TaskStatus.done)
    open_task = tasks_svc.create_task(db, title="Taxes", due=TODAY + timedelta(days=3))
    noted = tasks_svc.create_task(db, title="Paperwork", notes="- send the TAX form")
    gone = tasks_svc.create_task(db, title="Tax refund")
    tasks_svc.set_status(db, gone.id, TaskStatus.cancelled)
    found = search_svc.search(db, "tax", NOW)["tasks"]
    assert {t["id"] for t in found[:2]} == {open_task.id, noted.id}
    assert found[-1] == {"id": done.id, "title": "Plan my taxes", "meta": "done", "done": True}
    assert gone.id not in [t["id"] for t in found]
    assert next(t for t in found if t["id"] == open_task.id)["meta"].startswith("due ")


def test_a_percent_or_underscore_is_only_itself(db) -> None:
    tasks_svc.create_task(db, title="Raise 5% for rent")
    tasks_svc.create_task(db, title="Raise 50 for rent")
    assert [t["title"] for t in search_svc.search(db, "5%", NOW)["tasks"]] == ["Raise 5% for rent"]


def test_projects_by_name(db) -> None:
    projects_svc.create_project(db, name="Garden Planner")
    projects_svc.create_project(db, name="Home")
    [project] = search_svc.search(db, "planner", NOW)["projects"]
    assert project["name"] == "Garden Planner"


def test_a_series_shows_once_at_its_next_meeting(db) -> None:
    for days in (-7, 3, 10):
        start = NOW + timedelta(days=days)
        db.add(Event(
            title="Design review - Huddle", start=start, end=start + timedelta(hours=1),
            source=EventSource.work, read_only=True, external_id=f"h{days}",
        ))
    db.add(Event(
        title="Canceled: Huddle retro", start=NOW, end=NOW + timedelta(hours=1),
        source=EventSource.work, read_only=True, external_id="r",
    ))
    db.flush()
    events = search_svc.search(db, "huddle", NOW)["events"]
    huddle = next(e for e in events if e["title"] == "Design review - Huddle")
    assert huddle["day"] == (TODAY + timedelta(days=3)).isoformat()
    assert len([e for e in events if e["title"] == "Design review - Huddle"]) == 1
    retro = next(e for e in events if e["title"] == "Huddle retro")
    assert retro["cancelled"]
    # Its day as words, the month in capitals ("Mon 5 Oct", never "Mon 5 oct").
    assert huddle["when"][:1].isupper() and huddle["when"].endswith(f", {NOW:%H:%M}")


def test_notes_by_their_words_without_their_marks(db) -> None:
    day = TODAY - timedelta(days=2)
    text = "Slow morning, then errands.\n- [x] Plan my taxes\nJust need to add it to my tasks."
    notebook_svc.save_page(db, day, [{"kind": "text", "text": text}], version=0)
    [note] = search_svc.search(db, "taxes", NOW)["notes"]
    assert note["day"] == day.isoformat()
    assert "[x]" not in note["snippet"] and "Plan my taxes" in note["snippet"]
    assert note["label"][:1].isupper()


def test_the_menu_asks_by_its_endpoint(client, db) -> None:
    tasks_svc.create_task(db, title="Taxes")
    found = client.get("/ui/search?q=tax").json()
    assert [t["title"] for t in found["tasks"]] == ["Taxes"]
    assert set(found) == {"tasks", "projects", "events", "notes"}
