from datetime import date, timedelta

from app.models import TaskOwner, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.ui.views import design_system

TODAY = date.today()


def test_today_page_shows_planned_and_delegated(client, db) -> None:
    tasks_svc.create_task(db, title="write the plan", planned_for=TODAY)
    claude_task = tasks_svc.create_task(db, title="review PR", owner=TaskOwner.claude)
    tasks_svc.set_status(db, claude_task.id, TaskStatus.needs_review)

    page = client.get("/today").text
    assert "write the plan" in page
    assert "Delegated to Claude" in page
    assert "Needs review" in page


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
    assert plan_group(sunday + timedelta(days=1), TODAY) == "nextweek"

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


def test_done_work_folds_away_on_tasks_and_today(client, db) -> None:
    finished = tasks_svc.create_task(db, title="finished it", planned_for=TODAY)
    tasks_svc.create_task(db, title="still going", planned_for=TODAY)
    tasks_svc.set_status(db, finished.id, TaskStatus.done)

    tasks_page = client.get("/").text
    groups, fold = tasks_page.split('class="done-fold"')
    assert "finished it" not in groups and "finished it" in fold
    assert "last 14 days" in fold

    today = client.get("/today").text
    today_list = today.split('id="today-list"')[1].split("</ul>")[0]
    assert "still going" in today_list and "finished it" not in today_list
    assert "finished it" in today.split('id="today-done"')[1]
    assert "1 task open" in today


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
    # The list row carries the block's time and is marked as a drag source.
    assert "11:00–12:00" in page.split('id="today-list"')[1]
    assert "data-drag-to-grid" in page


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


def test_todays_composer_starts_dated_today(client) -> None:
    page = client.get("/today").text
    composer = page.split('data-sheet="compose"')[1].split("</form>")[0]
    assert f'name="planned_for" value="{TODAY.isoformat()}"' in composer
    assert f'name="list_day" value="{TODAY.isoformat()}"' in composer
    assert '<span class="prop-value">today</span>' in composer


def test_calendar_page_renders_grid_and_tray(client, db) -> None:
    from datetime import datetime, timedelta

    from app.services import blocks as blocks_svc

    task = tasks_svc.create_task(db, title="deep work", planned_for=TODAY)
    tasks_svc.create_task(db, title="loose end", planned_for=TODAY)
    now = datetime.now()
    blocks_svc.schedule_block(
        db, task_id=task.id, start=now + timedelta(hours=1), end=now + timedelta(hours=2)
    )

    page = client.get("/calendar").text
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

    page = client.get("/today").text
    assert "nudge-center" in page
    assert "missed its block" in page
    assert "Replan" in page

    assert client.post(f"/ui/nudges/{nudge.id}/dismiss").status_code == 200
    assert "nudge-center" not in client.get("/today").text


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
    row = client.get("/today").text.split(f'id="task-{task.id}"')[1].split("</li>")[0]
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
