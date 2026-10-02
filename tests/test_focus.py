"""Today's focus card: the block running now, with the time left, its
sub-tasks and Completed; else the next block today."""

from datetime import date, datetime, time, timedelta

from app.services import blocks as blocks_svc
from app.services import tasks as tasks_svc
from app.ui.views import focus_ctx

TODAY = date.today()


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(TODAY, time(hour, minute))


def test_the_block_running_now_and_the_time_left(db) -> None:
    task = tasks_svc.create_task(db, title="Write the report", notes="- outline\n- draft")
    blocks_svc.schedule_block(db, task_id=task.id, start=at(9), end=at(10, 30))
    focus = focus_ctx(db, at(9, 50))
    assert focus["now"] and focus["left"] == "40m"
    assert focus["block"].task.title == "Write the report"


def test_else_the_next_today_and_none_once_the_day_is_done(db) -> None:
    task = tasks_svc.create_task(db, title="Review")
    later = blocks_svc.schedule_block(db, task_id=task.id, start=at(15), end=at(16))
    tomorrow = datetime.combine(TODAY + timedelta(days=1), time(9))
    blocks_svc.schedule_block(
        db, task_id=task.id, start=tomorrow, end=tomorrow + timedelta(hours=1),
    )
    focus = focus_ctx(db, at(13, 30))
    assert not focus["now"] and focus["until"] == "1h 30m" and focus["block"] is later
    blocks_svc.complete_block(db, later.id)
    assert focus_ctx(db, at(13, 30)) is None  # tomorrow's is tomorrow's


def test_today_draws_it_with_the_page_and_refreshes_it(client, db) -> None:
    now = datetime.now()
    task = tasks_svc.create_task(db, title="Deep work", notes="- read\n- write")
    blocks_svc.schedule_block(
        db, task_id=task.id, start=now - timedelta(minutes=5), end=now + timedelta(minutes=55),
    )
    page = client.get("/today").text
    card = page.split('id="focus-card"')[1].split("</section>")[0]
    assert "Deep work" in card and "left, until" in card and "Sub-tasks" in card
    assert "every 60s, calendar:refresh from:body" in page
    assert "Deep work" in client.get("/ui/today/focus").text
    # Another day's page has none.
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    assert 'id="focus-card"' not in client.get(f"/day/{yesterday}").text
