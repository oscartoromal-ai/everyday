from datetime import date, timedelta

from app.models import TaskOwner, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.ui.views import design_system

TODAY = date.today()


def test_today_is_a_notepad_beside_the_timeline(client, db) -> None:
    from app.services import notebook as notebook_svc

    tasks_svc.create_task(db, title="write the plan", planned_for=TODAY)
    notebook_svc.save_page(db, TODAY, [{"kind": "text", "text": "Slow morning."}], version=0)

    page = client.get("/today").text
    pad = page.split('id="notepad"')[1].split("</textarea>")[0]
    assert 'data-version="1"' in pad and ">Slow morning." in pad
    assert 'class="today-timeline"' in page
    # Just the notes: the day's tasks live on Tasks and on the timeline.
    assert "write the plan" not in page.split('class="today-timeline"')[0]
    # N writes a task in the capture window here, as on Calendar and Weeks.
    assert 'id="capture-dialog"' in page



def task_rows_of(pad: str) -> list[dict]:
    """The notepad's task rows, as the page hands them to notepad.js."""
    import json

    return json.loads(pad.split("data-task-rows='")[1].split("'")[0])


def test_a_page_written_with_tasks_reads_back_as_text(client, db) -> None:
    from app.services import notebook as notebook_svc

    task = tasks_svc.create_task(db, title="Call the dentist")
    notebook_svc.save_page(
        db,
        TODAY,
        [{"kind": "text", "text": "Morning."}, {"kind": "task", "id": task.id}],
        version=0,
    )
    pad = client.get("/today").text.split('id="notepad"')[1].split("</textarea>")[0]
    assert ">Morning.\n- [ ] Call the dentist" in pad
    [row] = task_rows_of(pad)
    assert (row["row"], row["done"], row["id"], row["folded"]) == (1, False, task.id, False)
    # Its title row's controls get the task's fields.
    assert row["fields"]["status"] == "todo" and row["fields"]["planned_for"] == ""


def test_a_reflection_reads_back_as_its_rows(client, db) -> None:
    from app.services import notebook as notebook_svc

    task = tasks_svc.create_task(db, title="Call the dentist")
    notebook_svc.save_page(
        db,
        TODAY,
        [
            {"kind": "text", "text": "Morning.\n"},
            {"kind": "reflection", "text": "Calmer than yesterday.\nSlept well."},
            {"kind": "text", "text": "- [ ] Call the dentist", "links": {"0": task.id}},
        ],
        version=0,
    )
    pad = client.get("/today").text.split('id="notepad"')[1].split("</textarea>")[0]
    text = "Morning.\n\n/reflection Calmer than yesterday.\n\tSlept well.\n- [ ] Call the dentist"
    assert f">{text}<" in pad + "<"
    # A task after it keeps its row.
    [row] = task_rows_of(pad)
    assert (row["row"], row["id"]) == (4, task.id)


def test_task_rows_follow_their_tasks(client, db) -> None:
    from app.models import TaskStatus
    from app.services import notebook as notebook_svc

    task = tasks_svc.create_task(db, title="Call the dentist")
    notebook_svc.save_page(
        db,
        TODAY,
        [{"kind": "text", "text": "\n\nMorning.\n- [ ] Call the dentist\n- [ ] just a thought",
          "links": {"3": task.id}}],
        version=0,
    )
    # The blank lines trimmed from the top take the link along with its row.
    assert notebook_svc.get_page(db, TODAY).blocks[0]["links"] == {"1": task.id}
    tasks_svc.set_status(db, task.id, TaskStatus.done)

    pad = client.get("/today").text.split('id="notepad"')[1].split("</textarea>")[0]
    # Ticked elsewhere: its row reads done. A row that made no task stays a row.
    assert ">Morning.\n- [x] Call the dentist\n- [ ] just a thought" in pad
    rows = {r["row"]: r for r in task_rows_of(pad)}
    assert (rows[1]["done"], rows[1]["id"]) == (True, task.id)
    assert (rows[2]["done"], rows[2]["id"], rows[2]["fields"]) == (False, None, None)


def test_app_opens_on_tasks_grouped_by_do_date(client, db) -> None:
    from app.ui.views import plan_group

    sunday = TODAY + timedelta(days=6 - TODAY.weekday())
    undated = tasks_svc.create_task(db, title="undated one")
    deadline = tasks_svc.create_task(db, title="has a deadline", due=TODAY + timedelta(days=3))
    tasks_svc.create_task(db, title="slipped", planned_for=TODAY - timedelta(days=2))
    tasks_svc.create_task(db, title="for today", planned_for=TODAY)
    tasks_svc.create_task(db, title="next month", planned_for=sunday + timedelta(days=20))
    tasks_svc.create_task(db, title="claude job", owner=TaskOwner.claude)

    page = client.get("/").text
    assert 'aria-current="page"' in page.split('title="Tasks"')[1].split(">")[0]
    headings = [h.split("<")[0].strip() for h in page.split("<h2>")[1:]]
    # Overdue leads, then the triage list, then forward in time; empty groups hide.
    assert headings[:3] == ["Overdue", "No date", "Today"]
    assert headings[-1] == "Later"
    assert "Tomorrow" not in headings
    # Next week's Tuesday: never tomorrow, whatever day the suite runs.
    assert plan_group(sunday + timedelta(days=2), TODAY) == "nextweek"

    nodate = page.split('id="nodate-list"')[1].split("</ul>")[0]
    # A deadline outranks a bare capture; Claude's work stays off this page.
    assert nodate.index("has a deadline") < nodate.index("undated one")
    assert "claude job" not in page
    assert f'hx-post="/ui/tasks/{undated.id}/plan"' in nodate
    assert f'hx-post="/ui/tasks/{deadline.id}/plan"' in nodate
    assert "5 tasks open" in page and "2 without a day" in page


def test_today_group_offers_tomorrow_but_not_today(client, db) -> None:
    task = tasks_svc.create_task(db, title="for today", planned_for=TODAY)
    row = client.get("/").text.split(f'id="task-{task.id}"')[1].split("</li>")[0]
    assert ">Tomorrow</button>" in row and ">Today</button>" not in row
    assert "plan-btn slot" in row  # its slot stays, so the columns line up
    # While planning, a row always names its day, however it is grouped.
    assert '<span class="planned">today</span>' in row


def test_tasks_by_project_shows_cards_then_no_project(client, db) -> None:
    p = projects_svc.create_project(db, name="Calendar sync")
    m = projects_svc.create_milestone(db, project_id=p.id, name="ICS import")
    in_m = tasks_svc.create_task(db, title="parse VEVENTs", project_id=p.id, milestone_id=m.id)
    tasks_svc.create_task(db, title="renew token", project_id=p.id)
    tasks_svc.create_task(db, title="call the bank")

    page = client.get("/?view=project")
    assert page.cookies.get("tasks_view") == "project"
    html = page.text
    card = html.split(f'id="project-{p.id}"')[1].split("</article>")[0]
    assert "ICS import" in card and "parse VEVENTs" in card and "renew token" in card
    # Rows keep their date buttons; the Projects-only status control stays there.
    assert f'hx-post="/ui/tasks/{in_m.id}/plan"' in card
    assert "status-select" not in card
    loose = html.split('id="loose-list"')[1].split("</ul>")[0]
    assert "call the bank" in loose and "renew token" not in loose
    # The choice sticks for the next visit.
    assert 'aria-current="true">By project' in client.get("/").text


def test_done_work_folds_away_on_tasks(client, db) -> None:
    finished = tasks_svc.create_task(db, title="finished it", planned_for=TODAY)
    tasks_svc.create_task(db, title="still going", planned_for=TODAY)
    tasks_svc.set_status(db, finished.id, TaskStatus.done)

    tasks_page = client.get("/").text
    groups, fold = tasks_page.split('class="done-fold"')
    assert "finished it" not in groups and "finished it" in fold
    assert "last 14 days" in fold



def test_projects_show_one_occurrence_of_a_repeating_task(client, db) -> None:
    from app.models import RecurrenceKind
    from app.services import recurrence as rec_svc

    p = projects_svc.create_project(db, name="Home")
    series = rec_svc.create_template(
        db, kind=RecurrenceKind.task, repeat="daily", start_date=TODAY,
        title="water the plants", project_id=p.id,
    )
    rec_svc.materialize_template(db, series, TODAY)
    card = client.get("/projects").text.split(f'id="project-{p.id}"')[1].split("</article>")[0]
    assert card.count("water the plants</span>") == 1


def test_plan_sets_and_clears_the_do_date(client, db) -> None:
    task = tasks_svc.create_task(db, title="date me")
    response = client.post(f"/ui/tasks/{task.id}/plan", data={"planned_for": TODAY.isoformat()})
    assert response.status_code == 200
    assert response.headers["HX-Trigger"] == "tasks:changed"
    assert task.planned_for == TODAY
    client.post(f"/ui/tasks/{task.id}/plan", data={"planned_for": ""})
    assert task.planned_for is None


def test_rows_rerendered_on_tasks_keep_their_date_buttons(client, db) -> None:
    task = tasks_svc.create_task(db, title="keep buttons", notes="- one")
    plain = client.get(f"/ui/tasks/{task.id}/row").text
    assert "task-plan" not in plain
    on_tasks = client.post(
        f"/ui/tasks/{task.id}/subtasks/0/toggle",
        data={"text": "one"},
        headers={"X-Row-Context": "plan"},
    ).text
    assert "task-plan" in on_tasks


def test_backlog_folds_into_tasks(client) -> None:
    response = client.get("/backlog", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/"


def test_next_days_redirects_to_weeks_rows(client) -> None:
    response = client.get("/next", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/weeks?layout=rows"


def test_today_page_has_timeline_with_events_and_blocks(client, db) -> None:
    from datetime import datetime, time

    from app.services import blocks as blocks_svc
    from app.services import events as events_svc

    morning = datetime.combine(TODAY, time(9))
    events_svc.create_event(db, title="standup", start=morning, end=morning + timedelta(minutes=30))
    task = tasks_svc.create_task(db, title="focus", planned_for=TODAY)
    blocks_svc.schedule_block(
        db, task_id=task.id, start=morning + timedelta(hours=2), end=morning + timedelta(hours=3)
    )

    page = client.get("/today").text
    timeline = page.split('class="today-timeline"')[1]
    assert 'data-days="1"' in timeline
    assert "standup" in timeline and "focus" in timeline


def test_grid_fragment_refreshes_one_day_and_a_week(client) -> None:
    day = client.get(f"/calendar/grid?start={TODAY.isoformat()}&days=1")
    assert day.status_code == 200
    assert day.text.count('class="day-col') == 1
    assert "grid-head" not in day.text  # Today's page already names the day

    week = client.get(f"/calendar/grid?start={TODAY.isoformat()}&days=7")
    assert week.status_code == 200
    assert week.text.count('class="day-col') == 7
    monday = TODAY - timedelta(days=TODAY.weekday())
    assert f'data-date="{monday.isoformat()}"' in week.text

    assert client.get("/calendar/grid?days=8").status_code == 422


def test_weeks_page_shows_plans_deadlines_and_work_load(client, db) -> None:
    from datetime import datetime, time

    from app.models import Event, EventSource

    p = projects_svc.create_project(db, name="Reno")
    later = TODAY + timedelta(days=9)
    projects_svc.create_milestone(db, project_id=p.id, name="quotes in", target_date=later)
    tasks_svc.create_task(db, title="call sparky", planned_for=later, project_id=p.id)
    tasks_svc.create_task(db, title="pay invoice", due=later)
    tasks_svc.create_task(db, title="someday thing")
    start = datetime.combine(later, time(10))
    for offset in (0, 30):  # overlapping meetings count once toward busy hours
        db.add(
            Event(
                title="work sync", start=start + timedelta(minutes=offset),
                end=start + timedelta(minutes=offset + 60), source=EventSource.work,
                read_only=True, external_id=f"w{offset}",
            )
        )
    db.flush()

    for layout in ("grid", "rows"):
        page = client.get(f"/weeks?layout={layout}").text
        day = page.split(f'data-date="{later.isoformat()}"')[1].split("plan-day")[0]
        assert "call sparky" in day
        assert "pay invoice" in day and "due" in day
        assert "quotes in" in day
        assert "1.5h" in day  # union of 10:00-11:00 and 10:30-11:30
        assert "work sync" not in page  # meetings are condensed to load, not listed
        tray = page.split('class="tray plan-tray"')[1]
        assert "someday thing" in tray and "call sparky" not in tray


def test_weeks_layout_is_remembered(client) -> None:
    assert "week-rows" in client.get("/weeks?layout=rows").text
    assert "week-rows" in client.get("/weeks").text
    assert "month-grid" in client.get("/weeks?layout=grid").text
    assert "month-grid" in client.get("/weeks").text
    assert "month-grid" in client.get("/weeks?layout=bogus").text


def test_busy_hours_and_labels() -> None:
    from datetime import datetime

    from app.ui.weeks_view import _busy_hours, hours_label

    t = datetime(2026, 1, 5, 9)
    spans = [
        (t, t + timedelta(hours=1)),
        (t + timedelta(minutes=30), t + timedelta(hours=2)),
        (t + timedelta(hours=3), t + timedelta(hours=3, minutes=15)),
    ]
    assert _busy_hours(spans) == 2.25
    assert _busy_hours([]) == 0
    assert hours_label(0.75) == "45m"
    assert hours_label(2.25) == "2.5h"
    assert hours_label(4) == "4h"


def test_static_assets_are_versioned(client) -> None:
    page = client.get("/today").text
    assert "/static/app.css?v=" in page
    assert "/static/favicon.svg?v=" in page


def test_quick_add_creates_row(client) -> None:
    response = client.post(
        "/ui/tasks/quick-add", data={"title": "captured", "planned_for": TODAY.isoformat()}
    )
    assert response.status_code == 200
    assert "captured" in response.text
    assert "task-row" in response.text
    assert response.headers["HX-Trigger"] == "task:added"


def test_quick_add_takes_a_description_with_subtasks(client, db) -> None:
    row = client.post(
        "/ui/tasks/quick-add",
        data={
            "title": "ship sync",
            "notes": "ICS only for now.\r\n- fetch the feed\r\n- dedupe <instances>\r\n",
            "planned_for": TODAY.isoformat(),
        },
    ).text
    task = tasks_svc.list_tasks(db)[0]
    # The browser's CRLFs are stored as plain newlines, edges trimmed.
    assert task.notes == "ICS only for now.\n- fetch the feed\n- dedupe <instances>"
    assert '<span class="progress">0/2</span>' in row
    assert "ICS only for now." in row
    assert "dedupe &lt;instances&gt;" in row
    assert f'id="notes-{task.id}" hidden' in row


def test_ticking_a_subtask_rewrites_its_line_and_keeps_the_row_open(client, db) -> None:
    task = tasks_svc.create_task(db, title="ship sync", notes="- fetch\nwhy: TZ\n- dedupe")
    row = client.post(f"/ui/tasks/{task.id}/subtasks/1/toggle", data={"text": "dedupe"}).text
    assert task.notes == "- fetch\nwhy: TZ\n- [x] dedupe"
    assert '<span class="progress">1/2</span>' in row
    assert 'aria-expanded="true"' in row
    assert f'id="notes-{task.id}" hidden' not in row
    # The task itself is untouched.
    assert task.status == TaskStatus.todo


def test_a_stale_subtask_toggle_changes_nothing(client, db) -> None:
    task = tasks_svc.create_task(db, title="ship sync", notes="- fetch\n- dedupe")
    row = client.post(f"/ui/tasks/{task.id}/subtasks/0/toggle", data={"text": "gone"})
    assert row.status_code == 200
    assert task.notes == "- fetch\n- dedupe"
    assert '<span class="progress">0/2</span>' in row.text


def test_description_groups_context_subtasks_and_their_notes() -> None:
    from app.ui.views import description_blocks

    blocks = description_blocks(
        "\nWhy: ICS only.\nOAuth is blocked.\n\n\n"
        "- fetch\n    mind TZID\n- dedupe\nAfter that, ship.\n"
    )
    assert [b["kind"] for b in blocks] == ["text", "gap", "list", "text"]
    assert blocks[0]["lines"] == ["Why: ICS only.", "OAuth is blocked."]
    entries = blocks[2]["entries"]
    assert [(e["item"].text, e["notes"]) for e in entries] == [
        ("fetch", ["mind TZID"]),
        ("dedupe", []),
    ]


def test_a_task_without_description_has_no_toggle(client, db) -> None:
    task = tasks_svc.create_task(db, title="bare", planned_for=TODAY)
    row = client.get(f"/ui/tasks/{task.id}/row").text
    assert "notes-toggle" not in row and "task-notes" not in row


def test_toggle_marks_done_and_back(client, db) -> None:
    task = tasks_svc.create_task(db, title="flip me")
    row = client.post(f"/ui/tasks/{task.id}/toggle").text
    assert "done" in row and "checked" in row
    row = client.post(f"/ui/tasks/{task.id}/toggle").text
    assert "checked" not in row


def test_editor_roundtrip(client, db) -> None:
    p = projects_svc.create_project(db, name="App")
    task = tasks_svc.create_task(db, title="edit me")

    editor = client.get(f"/ui/tasks/{task.id}/edit").text
    assert 'data-sheet="edit"' in editor and "edit me" in editor

    row = client.post(
        f"/ui/tasks/{task.id}",
        data={
            "title": "edited",
            "notes": "",
            "status": "in_progress",
            "owner": "oscar",
            "project_id": str(p.id),
            "milestone_id": "",
            "planned_for": "",
            "due": (TODAY + timedelta(days=2)).isoformat(),
        },
    ).text
    assert "edited" in row
    assert "due" in row


def test_the_edit_sheet_carries_the_task_as_fields(client, db) -> None:
    from app.models import MilestoneStatus, ProjectStatus

    app_ = projects_svc.create_project(db, name="App")
    v1 = projects_svc.create_milestone(db, project_id=app_.id, name="v1")
    reached = projects_svc.create_milestone(db, project_id=app_.id, name="v0")
    reached.status = MilestoneStatus.reached
    shelved = projects_svc.create_project(db, name="Shelved")
    shelved.status = ProjectStatus.done
    task = tasks_svc.create_task(
        db, title="ship it", project_id=app_.id, milestone_id=v1.id,
        planned_for=TODAY + timedelta(days=1), due=TODAY,
    )
    db.flush()

    sheet = client.get(f"/ui/tasks/{task.id}/edit").text
    assert f'name="planned_for" value="{(TODAY + timedelta(days=1)).isoformat()}"' in sheet
    assert f'name="due" value="{TODAY.isoformat()}"' in sheet
    assert f'name="milestone_id" value="{v1.id}"' in sheet
    assert 'name="repeat" value="none"' in sheet
    assert '<span class="prop-value">tomorrow</span>' in sheet  # the do-date's label
    assert '<span class="prop-value">today</span>' in sheet  # the due date's
    assert "App › v1" in sheet
    # Open projects and milestones to file into; done ones stay out.
    assert '"name": "v1"' in sheet and '"name": "v0"' not in sheet
    assert "Shelved" not in sheet


def test_quick_add_takes_the_sheets_fields(client, db) -> None:
    p = projects_svc.create_project(db, name="Home")
    response = client.post(
        "/ui/tasks/quick-add",
        data={
            "title": "water plants",
            "planned_for": TODAY.isoformat(),
            "due": (TODAY + timedelta(days=3)).isoformat(),
            "repeat": "weekly",
            "project_id": str(p.id),
            "list_day": TODAY.isoformat(),
        },
    )
    assert response.headers["HX-Trigger"] == "task:added"
    task = next(t for t in tasks_svc.list_tasks(db) if t.title == "water plants")
    assert task.due == TODAY + timedelta(days=3)
    assert task.project_id == p.id
    assert task.recurrence_template is not None and task.recurrence_template.active


def test_a_task_dated_away_from_todays_list_regroups_instead(client, db) -> None:
    response = client.post(
        "/ui/tasks/quick-add",
        data={
            "title": "later thing",
            "planned_for": (TODAY + timedelta(days=1)).isoformat(),
            "list_day": TODAY.isoformat(),
        },
    )
    assert response.text == ""
    assert response.headers["HX-Trigger"] == "tasks:changed"
    task = next(t for t in tasks_svc.list_tasks(db) if t.title == "later thing")
    assert task.planned_for == TODAY + timedelta(days=1)




def test_calendar_page_renders_grid_and_tray(client, db) -> None:
    from datetime import datetime, timedelta

    from app.services import blocks as blocks_svc

    # Tomorrow at 10, and that day's week: always ahead (a block already past
    # is missed, and offered again), and on the grid shown (an hour from now
    # can fall past midnight, and on a Sunday into next week).
    day = TODAY + timedelta(days=1)
    task = tasks_svc.create_task(db, title="deep work", planned_for=day)
    tasks_svc.create_task(db, title="loose end", planned_for=day)
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=10)
    blocks_svc.schedule_block(db, task_id=task.id, start=start, end=start + timedelta(hours=1))

    page = client.get(f"/calendar?week={day.isoformat()}").text
    assert "calendar-grid" in page
    assert "deep work" in page  # rendered as a block on the grid
    assert "loose end" in page  # waiting in the tray
    tray_part = page.split('class="tray"')[1]
    assert "loose end" in tray_part
    assert "deep work" not in tray_part  # already slotted; not offered again


def test_nudge_banner_and_dismiss(client, db) -> None:
    from datetime import datetime, timedelta

    from app.services import blocks as blocks_svc
    from app.services import nudges as nudges_svc

    now = datetime.now()
    task = tasks_svc.create_task(db, title="slipped", planned_for=TODAY)
    blocks_svc.schedule_block(
        db, task_id=task.id, start=now - timedelta(hours=3), end=now - timedelta(hours=2)
    )
    blocks_svc.mark_missed_blocks(db, now)
    [nudge] = nudges_svc.evaluate(db, now)

    # The nudge center opens the app, on Tasks.
    page = client.get("/").text
    assert "nudge-center" in page
    assert "missed its block" in page
    assert "Replan" in page

    assert client.post(f"/ui/nudges/{nudge.id}/dismiss").status_code == 200
    assert "nudge-center" not in client.get("/").text


def test_repeat_from_editor_materializes_series(client, db) -> None:
    from sqlalchemy import select

    from app.models import Task

    task = tasks_svc.create_task(db, title="water plants", planned_for=TODAY)
    client.post(
        f"/ui/tasks/{task.id}",
        data={
            "title": "water plants",
            "notes": "",
            "status": "todo",
            "owner": "oscar",
            "repeat": "daily",
        },
    )
    occurrences = list(db.scalars(select(Task).where(Task.title == "water plants")))
    assert len(occurrences) > 50  # 8-week daily horizon
    assert all(t.recurrence_template_id for t in occurrences)

    # Turning repeat off keeps this task, drops pristine future occurrences.
    off = client.post(
        f"/ui/tasks/{task.id}",
        data={
            "title": "water plants",
            "notes": "",
            "status": "todo",
            "owner": "oscar",
            "repeat": "none",
        },
    )
    assert off.status_code == 200, off.text
    remaining = list(db.scalars(select(Task).where(Task.title == "water plants")))
    assert [t.id for t in remaining] == [task.id]


def test_add_event_form_creates_event_and_series(client, db) -> None:
    from sqlalchemy import select

    from app.models import Event

    response = client.post(
        "/ui/events",
        data={"title": "Dentist", "day": TODAY.isoformat(), "start_time": "14:00",
              "end_time": "15:00", "repeat": "none"},
    )
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "calendar:refresh"
    assert db.scalars(select(Event).where(Event.title == "Dentist")).one().start.hour == 14

    client.post(
        "/ui/events",
        data={"title": "Yoga", "day": TODAY.isoformat(), "start_time": "18:00",
              "end_time": "19:00", "repeat": "weekly"},
    )
    yoga = list(db.scalars(select(Event).where(Event.title == "Yoga")))
    assert len(yoga) == 9
    assert all(e.recurrence_template_id for e in yoga)


def test_project_card_lists_open_tasks_under_milestones(client, db) -> None:
    p = projects_svc.create_project(db, name="Reno")
    m = projects_svc.create_milestone(db, project_id=p.id, name="quotes in")
    tasks_svc.create_task(db, title="call sparky", project_id=p.id, milestone_id=m.id)
    tasks_svc.create_task(
        db, title="pick tiles", project_id=p.id, planned_for=TODAY + timedelta(days=2)
    )
    finished = tasks_svc.create_task(db, title="measure wall", project_id=p.id)
    tasks_svc.set_status(db, finished.id, TaskStatus.done)

    page = client.get("/projects").text
    card = page.split(f'id="project-{p.id}"')[1]
    group = card.split('class="milestone-group"')[1].split("</div>")[0]
    assert "call sparky" in group
    loose = card.split('class="loose-head"')[1]
    assert "pick tiles" in loose
    assert (TODAY + timedelta(days=2)).strftime("%a") in loose  # planned day shown
    assert "measure wall" not in card
    assert "2 open" in card


def test_project_quick_add_edit_and_status(client, db) -> None:
    p = projects_svc.create_project(db, name="Reno")

    row = client.post("/ui/tasks/quick-add", data={"title": "get quotes", "project_id": p.id})
    assert "get quotes" in row.text
    [task] = tasks_svc.list_tasks(db, project_id=p.id)
    assert task.title == "get quotes"

    assert 'name="notes"' in client.get(f"/ui/projects/{p.id}/edit").text
    card = client.post(
        f"/ui/projects/{p.id}", data={"name": "Kitchen reno", "notes": "  before summer  "}
    ).text
    assert "Kitchen reno" in card and "before summer" in card
    assert projects_svc.get_project(db, p.id).notes == "before summer"

    shelved = client.post(f"/ui/projects/{p.id}/status", data={"status": "paused"}).text
    assert 'class="project-shelf"' in shelved
    assert shelved.index("Paused") < shelved.index("Kitchen reno")
    active = client.post(f"/ui/projects/{p.id}/status", data={"status": "active"}).text
    assert "project-shelf" not in active


def test_projects_page_and_milestone_toggle(client, db) -> None:
    created = client.post("/ui/projects", data={"name": "New thing"})
    assert "New thing" in created.text

    p = projects_svc.list_projects(db)[0]
    milestone_row = client.post(
        f"/ui/projects/{p.id}/milestones", data={"name": "first cut", "target_date": ""}
    ).text
    assert "first cut" in milestone_row

    from sqlalchemy import select

    from app.models import Milestone

    m = db.scalars(select(Milestone).where(Milestone.project_id == p.id)).one()
    toggled = client.post(f"/ui/milestones/{m.id}/toggle").text
    assert "reached" in toggled


def test_task_rows_carry_a_delete_bin(client, db) -> None:
    task = tasks_svc.create_task(db, title="bin me", planned_for=TODAY)
    row = client.get("/").text.split(f'id="task-{task.id}"')[1].split("</li>")[0]
    assert f'hx-post="/ui/tasks/{task.id}/delete"' in row
    assert 'data-confirm-name="bin me"' in row


def test_delete_removes_task_and_refreshes_the_grid(client, db) -> None:
    from datetime import datetime

    from app.services import blocks as blocks_svc
    from app.services import nudges as nudges_svc

    now = datetime.now()
    task = tasks_svc.create_task(db, title="slipped", planned_for=TODAY)
    blocks_svc.schedule_block(
        db, task_id=task.id, start=now - timedelta(hours=3), end=now - timedelta(hours=2)
    )
    blocks_svc.mark_missed_blocks(db, now)
    assert nudges_svc.evaluate(db, now)

    response = client.post(f"/ui/tasks/{task.id}/delete")
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "calendar:refresh"
    page = client.get("/today").text
    assert "slipped" not in page
    assert "nudge-center" not in page


def test_shell_groups_calendar_pages_under_planner(client) -> None:
    page = client.get("/weeks").text
    planner = page.split('id="nav-planner"')[1].split("</div>\n      <div")[0]
    for href in ('href="/"', 'href="/today"', 'href="/calendar"', 'href="/weeks"'):
        assert href in planner
    # Tasks leads the group; Backlog folded into it.
    assert planner.index('href="/"') < planner.index('href="/today"')
    assert 'href="/backlog"' not in page
    assert 'aria-current="page"' in planner  # Weeks, inside its group


def test_shell_has_theme_toggle_and_collapse_control(client) -> None:
    page = client.get("/today").text
    # the toggle names the modes the installed design system names
    modes = design_system()["modes"]
    assert 'class="theme-toggle"' in page and modes["light"] in page and modes["dark"] in page
    assert 'class="rail-collapse"' in page and 'aria-controls="main-nav"' in page
    assert "/static/shell.js?v=" in page
    # the saved theme and rail state apply in <head>, before the stylesheet paints
    head = page.split("</head>")[0]
    assert head.index("pc-theme") < head.index("app.css")
    # the design system's stylesheet comes first, and its fonts are preloaded
    assert head.index("/static/design/design.css?v=") < head.index("/static/app.css?v=")
    for font in design_system()["fonts"]:
        assert f'href="/static/design/{font}" as="font"' in head


def at(hour: int, minute: int):  # noqa: ANN201
    """A wall-clock time today."""
    from datetime import datetime, time

    return datetime.combine(TODAY, time(hour, minute))


def _fixed_now(monkeypatch, moment):  # noqa: ANN001, ANN202
    """Pin datetime.now() for the fragments module (the replan endpoint's clock)."""
    import datetime as dt

    import app.ui.fragments as fragments

    class Fixed(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return moment

    monkeypatch.setattr(fragments, "datetime", Fixed)


def test_missed_row_replans_into_the_next_free_slot(client, db, monkeypatch) -> None:
    from app.models import Event, EventSource
    from app.services import blocks as blocks_svc

    now = at(14, 7)
    _fixed_now(monkeypatch, now)
    task = tasks_svc.create_task(db, title="slipped", planned_for=TODAY - timedelta(days=1))
    blocks_svc.schedule_block(
        db, task_id=task.id, start=at(9, 0), end=at(9, 45)
    )
    blocks_svc.mark_missed_blocks(db, now)
    db.add(Event(title="1:1", start=at(14, 15), end=at(15, 0),
                 source=EventSource.work, read_only=True))
    db.flush()

    row = client.get(f"/ui/tasks/{task.id}/row").text
    assert 'class="replan-btn"' in row and f'hx-post="/ui/tasks/{task.id}/replan"' in row

    response = client.post(f"/ui/tasks/{task.id}/replan")
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "calendar:refresh, tasks:changed"
    planned = [b for b in task.blocks if b.state.value == "planned"]
    assert [(b.start, b.end) for b in planned] == [
        (at(15, 0), at(15, 45))
    ]
    assert task.planned_for == TODAY
    assert "missed" not in response.text and "15:00–15:45" in response.text


def test_missed_row_moves_to_tomorrow_when_today_is_full(client, db, monkeypatch) -> None:
    from app.models import Event, EventSource
    from app.services import blocks as blocks_svc

    now = at(14, 7)
    _fixed_now(monkeypatch, now)
    task = tasks_svc.create_task(db, title="slipped", planned_for=TODAY)
    blocks_svc.schedule_block(
        db, task_id=task.id, start=at(9, 0), end=at(10, 0)
    )
    blocks_svc.mark_missed_blocks(db, now)
    db.add(Event(title="Offsite", start=at(14, 0), end=at(22, 0),
                 source=EventSource.work, read_only=True))
    db.flush()

    response = client.post(f"/ui/tasks/{task.id}/replan")
    assert response.status_code == 200
    assert task.planned_for == TODAY + timedelta(days=1)
    assert not [b for b in task.blocks if b.state.value == "planned"]
    assert "missed" not in response.text and "tomorrow" in response.text


def test_book_gives_a_task_the_next_free_hour_today(client, db, monkeypatch) -> None:
    from app.models import Event, EventSource

    _fixed_now(monkeypatch, at(14, 7))
    task = tasks_svc.create_task(db, title="deep work")
    db.add(Event(title="1:1", start=at(14, 15), end=at(15, 0),
                 source=EventSource.work, read_only=True))
    db.flush()

    response = client.post(f"/ui/tasks/{task.id}/book")
    assert response.status_code == 200
    assert response.json() == {"start": "15:00", "end": "16:00"}
    assert [(b.start, b.end) for b in task.blocks] == [(at(15, 0), at(16, 0))]
    assert task.planned_for == TODAY


def test_book_says_when_today_is_full(client, db, monkeypatch) -> None:
    from app.models import Event, EventSource

    _fixed_now(monkeypatch, at(14, 7))
    task = tasks_svc.create_task(db, title="deep work")
    db.add(Event(title="Offsite", start=at(14, 0), end=at(22, 0),
                 source=EventSource.work, read_only=True))
    db.flush()

    response = client.post(f"/ui/tasks/{task.id}/book")
    assert response.status_code == 422
    assert response.json() == {"detail": "No free hour left today."}
    assert task.blocks == []


def test_a_task_shows_its_project_as_its_flag_in_its_colour(client, db) -> None:
    p = projects_svc.create_project(db, name="Reno", color=3)
    task = tasks_svc.create_task(db, title="get quotes", planned_for=TODAY, project_id=p.id)

    # Its row: the flag in the project's colour, the name on hover, not written.
    row = client.get("/").text.split(f'id="task-{task.id}"')[1].split("</li>")[0]
    assert 'class="project-flag" role="img" style="--project: var(--hue-3)"' in row
    assert 'title="Project: Reno"' in row
    assert ">Reno<" not in row
    # Its sheet: the flag set, the name only in its title.
    sheet = client.get(f"/ui/tasks/{task.id}/edit").text
    assert 'class="prop in-project"' in sheet and 'style="--project: var(--hue-3)"' in sheet
    assert 'title="Project: Reno"' in sheet

    # The project's colour is chosen when it is edited.
    assert 'name="color" value="3" checked' in client.get(f"/ui/projects/{p.id}/edit").text
    card = client.post(f"/ui/projects/{p.id}", data={"name": "Reno", "color": "6"}).text
    assert 'style="--project: var(--hue-6)"' in card
    assert projects_svc.get_project(db, p.id).color == 6


def test_health_is_its_own_nav_group_with_nutrition(client) -> None:
    page = client.get("/nutrition").text
    group = page.split('aria-labelledby="nav-health"')[1].split("</nav>")[0]
    assert '<div class="nav-group-label" id="nav-health">Health</div>' in group
    link = group.split('href="/nutrition"')[1].split("</a>")[0]
    assert 'aria-keyshortcuts="6"' in link and 'aria-current="page"' in link
    # The day's log beside the day's chat with Claude (test_nutrition.py has the rest).
    main = page.split('<main class="main">')[1]
    assert 'class="chat-page nutrition-page"' in main and 'id="chat-composer"' in main


def test_me_saves_as_it_changes_and_says_what_follows(client, db) -> None:
    page = client.get("/me").text
    assert 'aria-keyshortcuts="7"' in page and "<h1>Me</h1>" in page
    assert "No weigh-ins yet." in page
    needs = "once you add your weight, height, birth date, sex and activity."
    assert f"Daily energy is estimated {needs}" in page

    form = {
        "height_cm": "180", "birth_date": "1996-03-01", "sex": "male", "activity": "moderate",
        "goal": "lose", "target_weight_kg": "75", "diet": "Omnivore", "allergies": "",
        "avoids": "", "notes": "",
    }
    context = client.post("/ui/me", data=form).text
    assert 'id="me-context"' in context and "once you add your weight." in context

    weights = client.post("/ui/me/weight", data={"weight_kg": "80,5"})
    assert weights.headers["HX-Trigger"] == "me:changed"
    assert "80.5 kg" in weights.text and "Today" in weights.text
    context = client.get("/ui/me/context").text
    assert "Your target is 75 kg: 5.5 kg to lose." in context
    assert "kcal a day keeps your weight" in context

    # A value out of range is refused, with why (the page toasts it).
    refused = client.post("/ui/me", data={**form, "height_cm": "1800"})
    assert refused.status_code == 422 and "Height" in refused.json()["detail"]
