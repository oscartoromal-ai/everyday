"""A day's page around its notes: the day's tasks it offers to write in
them, and the glance under its date (what is on now and next, and how
Oscar came into the day)."""

from datetime import date, datetime, timedelta

from app.models import GarminDay, TaskOwner, TaskStatus
from app.services import blocks as blocks_svc
from app.services import events as events_svc
from app.services import notebook as notebook_svc
from app.services import tasks as tasks_svc
from app.ui.views import day_glance_ctx, day_tasks_ctx

DAY = date(2026, 10, 2)
NOW = datetime(2026, 10, 2, 9, 30)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def titles(tasks) -> list[str]:  # noqa: ANN001
    return [t.title if hasattr(t, "title") else t["title"] for t in tasks]


# ---- the day's tasks ----


def test_todays_tasks_are_those_planned_or_due_by_today_deadlines_first(db) -> None:
    yesterday, tomorrow = DAY - timedelta(days=1), DAY + timedelta(days=1)
    tasks_svc.create_task(db, title="planned today", planned_for=DAY)
    tasks_svc.create_task(db, title="slipped", planned_for=yesterday)
    tasks_svc.create_task(db, title="due today", due=DAY)
    tasks_svc.create_task(db, title="was due", due=yesterday, planned_for=tomorrow)
    tasks_svc.create_task(db, title="tomorrow's", planned_for=tomorrow)
    tasks_svc.create_task(db, title="undated")
    tasks_svc.create_task(db, title="done", planned_for=DAY, status=TaskStatus.done)
    tasks_svc.create_task(db, title="Claude's", planned_for=DAY, owner=TaskOwner.claude)

    assert titles(tasks_svc.for_day(db, DAY, DAY)) == [
        "was due", "due today", "slipped", "planned today",
    ]
    # Another day's are its own: planned for it or due on it, nothing overdue
    # (one planned for it that was due before, deadline first all the same).
    assert titles(tasks_svc.for_day(db, tomorrow, DAY)) == ["was due", "tomorrow's"]
    assert titles(tasks_svc.for_day(db, tomorrow + timedelta(days=1), DAY)) == []
    # The past's work was its own.
    assert tasks_svc.for_day(db, yesterday, DAY) == []


def test_todays_list_takes_in_what_the_last_page_left_open_once(db) -> None:
    friday = DAY - timedelta(days=3)
    slipped = tasks_svc.create_task(db, title="slipped", planned_for=friday)
    undated = tasks_svc.create_task(db, title="undated")
    tasks_svc.create_task(db, title="due today", due=DAY)
    notebook_svc.save_page(db, friday, [{
        "kind": "text", "text": "- [ ] slipped\n- [ ] undated",
        "links": {"0": slipped.id, "1": undated.id},
    }], version=0)

    offered = day_tasks_ctx(db, DAY, DAY)
    assert offered["label"] == "For today"
    assert titles(offered["tasks"]) == ["due today", "slipped", "undated"]
    due, *_ = offered["tasks"]
    assert due["due"] == "due today"
    # Brought here, each is done this day.
    assert all(t["moves"] for t in offered["tasks"])
    assert {t["fields"]["planned_for"] for t in offered["tasks"]} == {DAY.isoformat()}

    tomorrow = day_tasks_ctx(db, DAY + timedelta(days=1), DAY)
    assert tomorrow == {"label": "For tomorrow", "tasks": []}


# ---- the glance ----


def test_the_glance_reads_how_the_body_came_into_the_day(db) -> None:
    db.add(GarminDay(
        day=DAY, readiness=91, readiness_level="HIGH", sleep_seconds=27060, sleep_score=87,
        body_battery_high=77,
    ))
    db.add(GarminDay(day=DAY - timedelta(days=1), readiness=31, readiness_level="LOW"))
    db.flush()

    glance = day_glance_ctx(db, DAY, NOW)
    assert [(f["label"], f["value"], f["detail"]) for f in glance["body"]] == [
        ("Readiness", "91", "high"), ("Sleep", "7h 31m", "score 87"), ("Body battery", "77", ""),
    ]
    # A low readiness asks for a light day; a past day has its body alone.
    before = day_glance_ctx(db, DAY - timedelta(days=1), NOW)
    assert before["body"] == [{
        "label": "Readiness", "value": "31", "detail": "low, keep the day light", "over": True,
    }]
    assert not before["live"] and before["on"] == []


def test_the_glance_names_the_events_on_now_and_next(db) -> None:
    events_svc.create_event(db, title="Deep work", start=at(9), end=at(11))
    events_svc.create_event(
        db, title="Weekly review", start=at(9, 55), end=at(10, 30),
        location="https://example.zoom.us/j/123?pwd=x",
    )
    events_svc.create_event(db, title="Canceled: Lunch", start=at(9, 40), end=at(10))
    # A task's block is the focus card's, not the glance's.
    block_task = tasks_svc.create_task(db, title="Write", planned_for=DAY)
    blocks_svc.schedule_block(db, task_id=block_task.id, start=at(9, 45), end=at(10))
    db.flush()

    on_now, on_next = day_glance_ctx(db, DAY, NOW)["on"]
    assert on_now == {
        "title": "Deep work", "now": True, "span": "09:00–11:00", "when": "till 11:00",
        "link": "", "link_host": "",
    }
    assert on_next == {
        "title": "Weekly review", "now": False, "span": "09:55–10:30", "when": "in 25m",
        "link": "https://example.zoom.us/j/123?pwd=x", "link_host": "zoom.us",
    }
    # Nothing on and nothing after: no names.
    assert day_glance_ctx(db, DAY, at(12))["on"] == []


def test_todays_page_draws_its_glance_and_redraws_it(client, db) -> None:
    today = date.today()
    db.add(GarminDay(day=today, readiness=91, readiness_level="HIGH"))
    db.flush()
    page = client.get("/today").text
    header = page.split('class="day-header"')[1].split("</header>")[0]
    assert 'id="day-glance"' in header and 'hx-get="/today/glance"' in header
    assert "<dt>Readiness</dt>" in header

    glance = client.get("/today/glance").text
    assert 'id="day-glance"' in glance
    assert "<dt>Readiness</dt>" in glance

    # Another day's glance stays as it is drawn.
    other = client.get(f"/day/{(today - timedelta(days=1)).isoformat()}").text
    assert 'hx-get="/today/glance"' not in other
