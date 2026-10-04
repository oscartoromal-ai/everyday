"""Calendar's sheet: the days as rows (where Oscar stays, the day's plan, a
column per habit), and what writing in it does to the day's notes and tasks."""

from datetime import date, datetime, time, timedelta

from app.models import HabitCheck, Task, TaskStatus
from app.services import events as events_svc
from app.services import habits as habits_svc
from app.services import notebook
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.ui.day_sheet_view import day_sheet_ctx, home_start

MONDAY = date(2026, 9, 28)
TUESDAY = MONDAY + timedelta(days=1)
TODAY = date.today()


def row(sheet: dict, day: date) -> dict:
    return next(r for r in sheet["rows"] if r["date"] == day)


def test_a_habit_ticked_on_the_sheet_is_written_in_the_days_notes(db) -> None:
    notebook.save_page(db, MONDAY, [{"kind": "text", "text": "Slow morning."}], version=0)
    notebook.set_habit(db, MONDAY, "exercise-run", True)
    # As "/habit exercise-run" would: a row on the page, at its top with no
    # habit before it, and its check.
    assert [b["kind"] for b in notebook.get_page(db, MONDAY).blocks] == ["habit", "text"]
    notebook.set_habit(db, MONDAY, "vitamin-d", True)
    blocks = notebook.blocks_of(db, MONDAY)
    assert [b.get("slug", b["kind"]) for b in blocks] == ["exercise-run", "vitamin-d", "text"]
    assert notebook.get_page(db, MONDAY).version == 3

    # One written unticked (skipped) is ticked where it is.
    notebook.save_page(
        db, MONDAY + timedelta(days=1),
        [{"kind": "text", "text": "x"}, {"kind": "habit", "habit": "vitamin-d", "done": False}],
        version=0,
    )
    notebook.set_habit(db, MONDAY + timedelta(days=1), "vitamin-d", True)
    [_, habit] = notebook.get_page(db, MONDAY + timedelta(days=1)).blocks
    assert habit["done"] is True

    # Unticked, its row leaves the page and the day has nothing for it.
    notebook.set_habit(db, MONDAY, "exercise-run", False)
    kept = [b.get("slug", b["kind"]) for b in notebook.blocks_of(db, MONDAY)]
    assert kept == ["vitamin-d", "text"]
    assert {(c.habit.slug, c.day) for c in db.query(HabitCheck).all()} == {
        ("vitamin-d", MONDAY), ("vitamin-d", MONDAY + timedelta(days=1)),
    }


def test_a_stay_written_on_the_sheet_is_the_days_stay(db) -> None:
    # Nothing to write leaves a day with no stay without one.
    assert notebook.set_stay_item(db, MONDAY, "place", value="  ") is None
    notebook.save_page(db, MONDAY, [{"kind": "text", "text": "Packed."}], version=0)
    notebook.set_stay_item(db, MONDAY, "place", value=" Leiden,   Netherlands ")
    # A new stay at the page's top, with the items a stay starts with.
    [stay, _] = notebook.get_page(db, MONDAY).blocks
    assert stay["text"] == "\n- [ ] place: Leiden, Netherlands\n- [ ] accommodation:"
    notebook.set_stay_item(db, MONDAY, "Accommodation", value="Canal house")
    notebook.set_stay_item(db, MONDAY, "accommodation", done=True)
    notebook.set_stay_item(db, MONDAY, "ferry", value="F4")
    assert notebook.stay_items(notebook.get_page(db, MONDAY).blocks[0]["text"]) == [
        {"name": "place", "value": "Leiden, Netherlands", "done": False},
        {"name": "accommodation", "value": "Canal house", "done": True},
        {"name": "ferry", "value": "F4", "done": False},
    ]
    # The next day's starts with the items this one has.
    notebook.set_stay_item(db, MONDAY + timedelta(days=1), "place", value="Delft")
    text = notebook.get_page(db, MONDAY + timedelta(days=1)).blocks[0]["text"]
    assert text == "\n- [ ] place: Delft\n- [ ] accommodation:\n- [ ] ferry:"


def test_the_sheet_reads_each_days_stay_plan_and_habits(db) -> None:
    notebook.set_stay_item(db, MONDAY, "place", value="Leiden")
    notebook.set_stay_item(db, MONDAY, "accommodation", value="Canal house", done=True)
    notebook.set_habit(db, MONDAY, "exercise-run", True)
    planned = tasks_svc.create_task(db, title="Book driving test", planned_for=MONDAY)
    tasks_svc.create_task(db, title="Do taxes", planned_for=MONDAY, status=TaskStatus.done)
    tasks_svc.create_task(db, title="File it", due=MONDAY)
    tasks_svc.create_task(db, title="Gone", planned_for=MONDAY, status=TaskStatus.cancelled)
    events_svc.create_event(
        db, title="Lunch at Delft", start=datetime.combine(MONDAY, time(12)),
        end=datetime.combine(MONDAY, time(13)),
    )
    events_svc.create_event(
        db, title="Parents here", start=datetime.combine(MONDAY, time.min),
        end=datetime.combine(MONDAY + timedelta(days=2), time.min), all_day=True,
    )

    sheet = day_sheet_ctx(db, MONDAY, MONDAY + timedelta(days=2))
    assert len(sheet["rows"]) == 28
    assert [(c["label"], c["check"]) for c in sheet["columns"]] == [
        ("Place", False), ("Accommodation", True),
    ]
    assert row(sheet, MONDAY)["plan_count"] == 5
    assert [h["slug"] for h in sheet["habits"]] == ["exercise-run"]
    monday = row(sheet, MONDAY)
    stays = [(i["value"], i["done"]) for i in monday["stay"]]
    assert stays == [("Leiden", False), ("Canal house", True)]
    # Its work, then its deadlines; a cancelled task is not on it.
    assert [(t["title"], t["done"], t["due"]) for t in monday["tasks"]] == [
        ("Book driving test", False, False), ("Do taxes", True, False), ("File it", False, True),
    ]
    assert monday["tasks"][0]["id"] == planned.id
    # Its own events, all day first; an event over days is on each.
    assert [(e["time"], e["title"]) for e in monday["events"]] == [
        ("", "Parents here"), ("12:00", "Lunch at Delft"),
    ]
    tuesday = row(sheet, TUESDAY)
    assert [e["title"] for e in tuesday["events"]] == ["Parents here"]
    assert row(sheet, MONDAY + timedelta(days=2))["events"] == []
    assert monday["habits"][0]["state"] == "done"
    # A day with no stay has its cells empty.
    assert row(sheet, MONDAY + timedelta(days=1))["stay"] == [None, None]


def test_the_sheet_opens_on_last_weeks_monday(client) -> None:
    client.cookies.delete("calendar_view")
    page = client.get("/calendar?view=sheet")
    assert page.cookies.get("calendar_view") == "sheet"
    start = home_start(TODAY)
    assert start.weekday() == 0 and timedelta(days=7) <= TODAY - start < timedelta(days=14)
    assert f'id="day-sheet" data-start="{start.isoformat()}"' in page.text
    assert page.text.count("<tr data-day=") == 28
    # Remembered; its steps go by its four weeks, and any start is snapped to a Monday.
    later = client.get(f"/calendar?start={(MONDAY + timedelta(days=3)).isoformat()}").text
    assert f'data-start="{MONDAY.isoformat()}"' in later
    assert f'href="/calendar?start={(MONDAY + timedelta(days=28)).isoformat()}"' in later
    assert "28 Sep – 25 Oct 2026" in later
    # From the time grid, the switch to it keeps today on it, a week down.
    week = client.get("/calendar?view=week").text
    assert f'href="/calendar?view=sheet&start={start.isoformat()}"' in week
    # A new event (from the command menu) is written on the time grid, the
    # sheet staying the choice.
    client.get("/calendar?view=sheet")
    assert 'class="day-col' in client.get("/calendar?new=1").text
    assert client.get("/calendar").text.count("<tr data-day=") == 28


def test_writing_in_the_sheet(client, db) -> None:
    task = tasks_svc.create_task(db, title="Send documents", planned_for=MONDAY)
    ops = [
        {"op": "stay", "day": MONDAY.isoformat(), "name": "place", "value": "Leiden"},
        {"op": "stay", "day": MONDAY.isoformat(), "name": "accommodation", "done": True},
        {"op": "habit", "day": MONDAY.isoformat(), "slug": "morning-run", "done": True},
        {"op": "habit", "day": TUESDAY.isoformat(), "slug": "morning-run", "done": True},
        {"op": "task", "day": MONDAY.isoformat(), "title": " Book driving test "},
        {"op": "task", "day": MONDAY.isoformat(), "title": "  "},
        {"op": "toggle", "task": task.id},
    ]
    answer = client.post(f"/ui/day-sheet?start={MONDAY.isoformat()}", json={"ops": ops})
    assert answer.status_code == 200
    # Answered with the sheet drawn again.
    assert 'data-name="place" data-value="Leiden"' in answer.text
    assert 'data-name="accommodation" data-done="true"' in answer.text
    assert answer.text.count('data-slug="morning-run" data-state="done"') == 2
    assert [b.get("slug") for b in notebook.blocks_of(db, MONDAY)] == ["morning-run", None]
    assert db.query(Task).filter_by(title="Book driving test").one().planned_for == MONDAY
    assert db.query(Task).count() == 2
    assert tasks_svc.get_task(db, task.id).status == TaskStatus.in_progress

    bad = client.post(
        f"/ui/day-sheet?start={MONDAY.isoformat()}", json={"ops": [{"op": "nope", "day": "x"}]}
    )
    assert bad.status_code == 422
    assert habits_svc.list_habits(db)[0].slug == "morning-run"


def test_a_tasks_box_goes_in_progress_then_done_and_its_menu_sets_either(client, db) -> None:
    task = tasks_svc.create_task(db, title="Send documents", planned_for=MONDAY)
    url = f"/ui/day-sheet?start={MONDAY.isoformat()}"

    def status_after(*ops: dict) -> TaskStatus:
        assert client.post(url, json={"ops": list(ops)}).status_code == 200
        db.expire_all()
        return tasks_svc.get_task(db, task.id).status

    toggle = {"op": "toggle", "task": task.id}
    assert status_after(toggle) == TaskStatus.in_progress
    answer = client.post(url, json={"ops": []}).text
    assert 'class="ds-task is-in-progress"' in answer
    assert f'data-status-menu="{task.id}" data-status="in_progress"' in answer
    assert status_after(toggle) == TaskStatus.done
    assert status_after(toggle) == TaskStatus.todo
    assert status_after({"op": "status", "task": task.id, "status": "done"}) == TaskStatus.done
    assert status_after({"op": "status", "task": task.id, "status": "todo"}) == TaskStatus.todo
    bad = client.post(url, json={"ops": [{"op": "status", "task": task.id, "status": "nope"}]})
    assert bad.status_code == 422


def test_a_task_is_deleted_from_the_sheet(client, db) -> None:
    task = tasks_svc.create_task(db, title="Cancel gym", planned_for=MONDAY)
    kept = tasks_svc.create_task(db, title="Pay rent", planned_for=MONDAY)
    answer = client.post(
        f"/ui/day-sheet?start={MONDAY.isoformat()}",
        json={"ops": [{"op": "delete", "task": task.id}]},
    )
    assert answer.status_code == 200
    assert "Cancel gym" not in answer.text
    assert f'data-delete-task="{kept.id}"' in answer.text
    assert [t.title for t in db.query(Task).all()] == ["Pay rent"]


def test_a_deadline_is_urgent_only_once_due_soon_and_a_task_wears_its_projects_colour(
    client, db,
) -> None:
    # Oscar's report on 2026-10-04: deadlines weeks out read as urgent as
    # tomorrow's. "due" warns only once a deadline is due soon (or past), as
    # a task row's due does.
    project = projects_svc.create_project(db, name="Garden Planner", color=8)
    soon_day = TODAY + timedelta(days=tasks_svc.DUE_SOON_DAYS)
    later_day = soon_day + timedelta(days=1)
    tasks_svc.create_task(db, title="Ship the beta", due=soon_day, project_id=project.id)
    tasks_svc.create_task(db, title="Ship docs", due=later_day)
    sheet = day_sheet_ctx(db, home_start(TODAY), TODAY)
    [soon] = row(sheet, soon_day)["tasks"]
    [later] = row(sheet, later_day)["tasks"]
    assert (soon["due"], soon["due_soon"]) == (True, True)
    assert (later["due"], later["due_soon"]) == (True, False)
    # Each task in its project's colour, the project named on hover.
    assert soon["project"] == {"name": "Garden Planner", "color": 8}
    assert later["project"] is None

    page = client.get("/calendar?view=sheet").text
    assert page.count('<span class="ds-due soon">due</span>') == 1
    assert page.count('<span class="ds-due">due</span>') == 1
    assert 'class="ds-task in-project" style="--project: var(--hue-8)"' in page
    assert 'title="Project: Garden Planner"' in page
