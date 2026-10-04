from datetime import date, timedelta

from app.models import ProjectStatus, TaskOwner, TaskStatus
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
    # The notes are as written: the day's tasks are offered to write in
    # them ("For today"), not written for him.
    assert "write the plan" not in pad.split(">", 1)[1]
    assert '"title": "write the plan"' in pad.split(">", 1)[0]
    # N writes a task in the capture window here, as on Calendar.
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


def test_the_app_opens_on_today(client) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/today"


def test_plan_holds_every_open_task_without_a_day(client, db) -> None:
    p = projects_svc.create_project(db, name="Calendar sync")
    m = projects_svc.create_workstream(db, project_id=p.id, name="ICS import")
    in_m = tasks_svc.create_task(db, title="parse VEVENTs", project_id=p.id, workstream_id=m.id)
    tasks_svc.create_task(db, title="renew token", project_id=p.id, planned_for=TODAY)
    undated = tasks_svc.create_task(db, title="undated one")
    tasks_svc.create_task(db, title="has a deadline", due=TODAY + timedelta(days=3))
    tasks_svc.create_task(db, title="for today", planned_for=TODAY)
    tasks_svc.create_task(db, title="claude job", owner=TaskOwner.claude)

    page = client.get("/plan").text
    assert 'aria-current="page"' in page.split('title="Projects"')[1].split(">")[0]
    assert "3 open tasks without a day" in page
    # The tasks in no project first, with the page's composer: a deadline
    # before a bare capture; a task with a day, and Claude's work, off it.
    loose_group = page.split('id="group-loose"')[1].split("</section>")[0]
    loose = loose_group.split('id="loose-list"')[1].split("</ul>")[0]
    assert loose.index("has a deadline") < loose.index("undated one")
    assert 'data-composer-key="loose-list"' in loose_group
    assert f'hx-post="/ui/tasks/{undated.id}/plan"' in loose
    for off in ("for today", "renew token", "claude job"):
        assert off not in page
    # Then each project's, every row with its do-date buttons.
    group = page.split(f'id="plan-project-{p.id}"')[1].split("</section>")[0]
    assert "parse VEVENTs" in group and f'hx-post="/ui/tasks/{in_m.id}/plan"' in group
    assert page.index('id="group-loose"') < page.index(f'id="plan-project-{p.id}"')
    # It draws itself again as the plan changes, and its count with it.
    lists = page.split('id="plan-lists"')[1].split(">")[0]
    assert 'hx-get="/plan"' in lists and "tasks:changed from:body" in lists
    assert "#plan-rest" in lists and "data-cursor" in lists


def test_projects_lays_the_projects_over_the_weeks(client, db) -> None:
    late = projects_svc.create_project(db, name="Late one")
    tasks_svc.create_task(
        db, title="missed it", project_id=late.id,
        starts_on=TODAY - timedelta(days=3), due=TODAY - timedelta(days=1),
    )
    done = tasks_svc.create_task(
        db, title="did it", project_id=late.id, due=TODAY + timedelta(days=20)
    )
    tasks_svc.set_status(db, done.id, TaskStatus.done)
    calm = projects_svc.create_project(db, name="Calm one")
    lane = projects_svc.create_workstream(db, project_id=calm.id, name="Lane open")
    tasks_svc.create_task(
        db, title="later on", project_id=calm.id, workstream_id=lane.id,
        due=TODAY + timedelta(days=10),
    )
    shut = projects_svc.create_workstream(db, project_id=calm.id, name="Lane shut")
    shut_task = tasks_svc.create_task(
        db, title="shut it", project_id=calm.id, workstream_id=shut.id
    )
    tasks_svc.set_status(db, shut_task.id, TaskStatus.done)
    soon = projects_svc.create_project(db, name="Soon one")
    tasks_svc.create_task(db, title="almost", project_id=soon.id, due=TODAY + timedelta(days=1))
    projects_svc.create_project(db, name="Bare one")
    parked = projects_svc.create_project(db, name="Parked one")
    projects_svc.update_project(db, parked.id, status=ProjectStatus.paused)
    finished = projects_svc.create_project(db, name="Finished one")
    projects_svc.update_project(db, finished.id, status=ProjectStatus.done)

    page = client.get("/projects").text
    timeline = page.split('class="list-section projects-timeline"')[1].split("</section>")[0]
    # A group a project, the active ones, in their order.
    groups = timeline.split('class="tl-group')[1:]
    assert [g.split('title="Open ')[1].split('"')[0] for g in groups] == [
        "Late one", "Calm one", "Soon one", "Bare one",
    ]
    late_g, calm_g, soon_g, bare_g = groups
    # Its health is what its deadlines say, in words.
    assert '"chip err">1 overdue<' in late_g
    assert '"chip ok">On track<' in calm_g
    assert '"chip warn">Due soon<' in soon_g
    assert '"chip neutral">Nothing open<' in bare_g
    # Its progress, its span with what is done of it, and its deadlines.
    assert "<b>50%</b> <span>1/2</span>" in late_g
    assert 'class="tl-bar"' in late_g and 'class="tl-bar-done" style="width: 50%"' in late_g
    assert 'class="tl-due overdue"' in late_g and 'title="missed it, due yesterday"' in late_g
    assert 'class="tl-bar"' not in bare_g and "No dates yet" in bare_g
    # Under it, its workstreams with work open; the finished ones counted.
    assert "Lane open" in calm_g and "Lane shut" not in calm_g and "1 finished" in calm_g
    assert f'data-project-fold="{calm.id}"' in calm_g and "data-project-fold" not in bare_g
    # The paused and done ones after it, a line each.
    shelf = page.split('class="projects-shelf"')[1].split("</nav>")[0]
    assert shelf.index("Parked one") < shelf.index("Finished one")
    assert "Parked one" not in timeline and "Finished one" not in timeline
    # It is drawn again as tasks and projects change.
    body = page.split('id="projects-body"')[1].split(">")[0]
    assert 'hx-get="/projects"' in body and "projects:changed from:body" in body


def test_projects_says_what_needs_attention(client, db) -> None:
    active = projects_svc.create_project(db, name="Reno")
    parked = projects_svc.create_project(db, name="Boat")
    projects_svc.update_project(db, parked.id, status=ProjectStatus.paused)
    tasks_svc.create_task(db, title="soon one", project_id=active.id, due=TODAY + timedelta(days=2))
    tasks_svc.create_task(db, title="late one", due=TODAY - timedelta(days=1))
    tasks_svc.create_task(db, title="later", project_id=active.id, due=TODAY + timedelta(days=9))
    tasks_svc.create_task(
        db, title="parked late", project_id=parked.id, due=TODAY - timedelta(days=1)
    )
    review = tasks_svc.create_task(db, title="claude did it", owner=TaskOwner.claude)
    tasks_svc.set_status(db, review.id, TaskStatus.needs_review)
    tasks_svc.create_task(db, title="no day")

    page = client.get("/projects").text
    attention = page.split('class="list-section attention"')[1].split("</section>")[0]
    # Overdue, then due soon, then Claude's work to review; not what is
    # far off, nor a paused project's.
    order = [attention.index(t) for t in ("late one", "soon one", "claude did it")]
    assert order == sorted(order)
    assert '"chip err">Overdue<' in attention and '"chip warn">Due soon<' in attention
    assert '"chip needs_review">Needs review<' in attention
    assert ">later</a>" not in attention and "parked late" not in attention
    assert ">No project<" in attention and ">Reno<" in attention
    # And the tasks without a day, sent to Plan.
    assert "open tasks have no day" in attention and 'href="/plan"' in attention
    assert page.index('class="list-section attention"') < page.index("projects-timeline")


def test_nothing_needing_attention_draws_no_card(client, db) -> None:
    p = projects_svc.create_project(db, name="Calm")
    tasks_svc.create_task(
        db, title="later", project_id=p.id, planned_for=TODAY, due=TODAY + timedelta(days=9)
    )
    assert 'class="list-section attention"' not in client.get("/projects").text


def test_a_projects_tasks_tab_plans_its_tasks(client, db) -> None:
    p = projects_svc.create_project(db, name="Reno")
    m = projects_svc.create_workstream(db, project_id=p.id, name="quotes in")
    tasks_svc.create_task(db, title="call sparky", project_id=p.id, workstream_id=m.id)
    tasks_svc.create_task(
        db, title="pick tiles", project_id=p.id, planned_for=TODAY + timedelta(days=2)
    )
    claude = tasks_svc.create_task(
        db, title="draft the plan", project_id=p.id, owner=TaskOwner.claude
    )
    tasks_svc.set_status(db, claude.id, TaskStatus.in_progress)
    finished = tasks_svc.create_task(db, title="measure wall", project_id=p.id)
    tasks_svc.set_status(db, finished.id, TaskStatus.done)
    shut = projects_svc.create_workstream(db, project_id=p.id, name="permits")
    from app.models import WorkstreamStatus

    projects_svc.update_workstream(db, shut.id, status=WorkstreamStatus.done)

    page = client.get(f"/projects/{p.id}/tasks").text
    # Its tabs, Tasks the current one.
    assert f'<a href="/projects/{p.id}/tasks" aria-current="page">Tasks</a>' in page
    lists = page.split('id="project-tasks"')[1]
    # A card a workstream, its composer filing into it.
    group = lists.split(f'id="workstream-group-{m.id}"')[1].split("</section>")[0]
    assert "call sparky" in group and f'data-file-workstream="{m.id}"' in group
    assert f'name="workstream_id" value="{m.id}"' in group
    # Then the tasks in none, its day shown, Claude's work with them.
    loose = lists.split('id="no-workstream"')[1].split("</section>")[0]
    assert "pick tiles" in loose and (TODAY + timedelta(days=2)).strftime("%a") in loose
    assert "draft the plan" in loose and "Running" in loose
    assert f'data-composer-key="project-tasks-{p.id}"' in loose
    # A finished workstream folds to the finished ones' line; done work folds away.
    finished_line = lists.split('class="finished-workstreams"')[1].split("</section>")[0]
    assert "permits" in finished_line and 'id="workstream-group-' + str(shut.id) not in lists
    groups, fold = lists.split('class="done-fold" id="project-done"')
    assert "measure wall" not in groups and "measure wall" in fold and "last 14 days" in fold
    # It works from the keyboard, and draws itself again as the plan changes.
    head = lists.split(">")[0]
    assert "data-cursor" in head and f'hx-get="/projects/{p.id}/tasks"' in head
    assert "tasks:changed from:body" in head and "#project-head" in head


def test_a_row_for_today_offers_tomorrow_but_not_today(client, db) -> None:
    p = projects_svc.create_project(db, name="Home")
    task = tasks_svc.create_task(db, title="for today", project_id=p.id, planned_for=TODAY)
    page = client.get(f"/projects/{p.id}/tasks").text
    row = page.split(f'id="task-{task.id}"')[1].split("</li>")[0]
    assert ">Tomorrow</button>" in row and ">Today</button>" not in row
    assert "plan-btn slot" in row  # its slot stays, so the columns line up
    # A row always names its day, today included.
    assert '<span class="planned">today</span>' in row


def test_a_projects_tasks_show_one_occurrence_of_a_repeating_task(client, db) -> None:
    from app.models import RecurrenceKind
    from app.services import recurrence as rec_svc

    p = projects_svc.create_project(db, name="Home")
    series = rec_svc.create_template(
        db, kind=RecurrenceKind.task, repeat="daily", start_date=TODAY,
        title="water the plants", project_id=p.id,
    )
    rec_svc.materialize_template(db, series, TODAY)
    page = client.get(f"/projects/{p.id}/tasks").text.split('id="project-tasks"')[1]
    assert page.count("water the plants</span>") == 1


def test_plan_sets_and_clears_the_do_date(client, db) -> None:
    task = tasks_svc.create_task(db, title="date me")
    response = client.post(f"/ui/tasks/{task.id}/plan", data={"planned_for": TODAY.isoformat()})
    assert response.status_code == 200
    assert response.headers["HX-Trigger"] == "tasks:changed"
    assert task.planned_for == TODAY
    client.post(f"/ui/tasks/{task.id}/plan", data={"planned_for": ""})
    assert task.planned_for is None


def test_rows_rerendered_keep_their_date_buttons(client, db) -> None:
    task = tasks_svc.create_task(db, title="keep buttons", notes="- one")
    assert "task-plan" in client.get(f"/ui/tasks/{task.id}/row").text
    toggled = client.post(f"/ui/tasks/{task.id}/subtasks/0/toggle", data={"text": "one"}).text
    assert "task-plan" in toggled


def test_backlog_folds_into_plan(client) -> None:
    response = client.get("/backlog", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/plan"


def test_today_page_has_timeline_with_its_events(client, db) -> None:
    from datetime import datetime, time

    from app.services import events as events_svc

    morning = datetime.combine(TODAY, time(9))
    events_svc.create_event(db, title="standup", start=morning, end=morning + timedelta(minutes=30))

    page = client.get("/today").text
    timeline = page.split('class="today-timeline"')[1]
    assert 'data-days="1"' in timeline
    assert "standup" in timeline


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


def test_quick_add_files_it_into_a_workstream(client, db) -> None:
    home = projects_svc.create_project(db, name="Home")
    work = projects_svc.create_project(db, name="Work")
    garden = projects_svc.create_workstream(db, project_id=home.id, name="Garden")
    db.commit()
    response = client.post(
        "/ui/tasks/quick-add",
        data={"title": "plant tulips", "project_id": str(home.id), "workstream_id": str(garden.id)},
    )
    assert response.status_code == 200
    (task,) = tasks_svc.list_tasks(db)
    assert (task.project_id, task.workstream_id) == (home.id, garden.id)
    # A workstream of another project is refused, and nothing is added.
    refused = client.post(
        "/ui/tasks/quick-add",
        data={"title": "stray", "project_id": str(work.id), "workstream_id": str(garden.id)},
    )
    assert refused.status_code == 422
    assert [t.title for t in tasks_svc.list_tasks(db)] == ["plant tulips"]


def test_every_page_offers_the_new_task_window(client, db) -> None:
    home = projects_svc.create_project(db, name="Home")
    projects_svc.create_workstream(db, project_id=home.id, name="Garden")
    db.commit()
    for path in ("/today", "/garmin", "/me", "/projects", f"/projects/{home.id}"):
        page = client.get(path).text
        assert "data-capture-open" in page, path
        window = page.split('id="capture-dialog"')[1].split("</dialog>")[0]
        # The projects and workstreams to file it into, at its foot.
        assert 'class="prop file-into"' in window, path
        assert '"name": "Garden"' in window, path
        # A project's pages start it in that project.
        default = home.id if path.startswith("/projects/") else ""
        assert f'name="project_id" value="{default}"' in window, path


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


def test_a_fenced_block_in_a_description_is_code() -> None:
    from app.ui.views import description_blocks

    blocks = description_blocks("Run:\n```sh\n- not a list\n  **x**\n```\n- ship")
    assert [b["kind"] for b in blocks] == ["text", "code", "list"]
    assert blocks[1]["lines"] == ["- not a list", "  **x**"]


def test_a_description_line_reads_as_its_markdown() -> None:
    from app.markdown import render_note

    assert render_note("## Packing ##") == '<strong class="md-h md-h2">Packing</strong>'
    assert render_note("> ask *Ana*") == '<span class="md-quote">ask <em>Ana</em></span>'
    assert render_note("---") == '<span class="md-hr"></span>'
    assert render_note("~~old~~ `new`") == "<s>old</s> <code>new</code>"
    # Only a web address is a link, as in the editor; HTML is escaped.
    assert render_note("see https://a.b/c") == (
        'see <a href="https://a.b/c" target="_blank" rel="noopener noreferrer">https://a.b/c</a>'
    )
    assert render_note("www.a.b [x](javascript:alert(1)) [TBD]") == (
        "www.a.b [x](javascript:alert(1)) [TBD]"
    )
    assert render_note("<b>hi</b>") == "&lt;b&gt;hi&lt;/b&gt;"


def test_a_row_shows_its_description_as_markdown(client, db) -> None:
    task = tasks_svc.create_task(
        db, title="md", planned_for=TODAY, notes="# Plan\n- **bold** step\n  a [link](https://x.y)"
    )
    row = client.get(f"/ui/tasks/{task.id}/row").text
    assert '<strong class="md-h md-h1">Plan</strong>' in row
    assert "<span><strong>bold</strong> step</span>" in row
    assert '<a href="https://x.y" target="_blank" rel="noopener noreferrer">link</a>' in row
    # The box still posts the sub-task's words as written, for the toggle's check.
    assert "**bold** step" in row


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
            "workstream_id": "",
            "planned_for": "",
            "due": (TODAY + timedelta(days=2)).isoformat(),
        },
    ).text
    assert "edited" in row
    assert "due" in row


def test_the_edit_sheet_carries_the_task_as_fields(client, db) -> None:
    from app.models import ProjectStatus, WorkstreamStatus

    app_ = projects_svc.create_project(db, name="App")
    v1 = projects_svc.create_workstream(db, project_id=app_.id, name="v1")
    finished = projects_svc.create_workstream(db, project_id=app_.id, name="v0")
    finished.status = WorkstreamStatus.done
    shelved = projects_svc.create_project(db, name="Shelved")
    shelved.status = ProjectStatus.done
    task = tasks_svc.create_task(
        db, title="ship it", project_id=app_.id, workstream_id=v1.id,
        planned_for=TODAY + timedelta(days=1), due=TODAY,
    )
    db.flush()

    sheet = client.get(f"/ui/tasks/{task.id}/edit").text
    assert f'name="planned_for" value="{(TODAY + timedelta(days=1)).isoformat()}"' in sheet
    assert f'name="due" value="{TODAY.isoformat()}"' in sheet
    assert f'name="workstream_id" value="{v1.id}"' in sheet
    assert 'name="repeat" value="none"' in sheet
    assert '<span class="prop-value">tomorrow</span>' in sheet  # the do-date's label
    assert '<span class="prop-value">today</span>' in sheet  # the due date's
    assert "App › v1" in sheet
    # Open projects and workstreams to file into; done ones stay out.
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


def test_calendar_page_is_the_grid_of_events_alone(client, db) -> None:
    from datetime import datetime, timedelta

    from app.services import events as events_svc

    day = TODAY + timedelta(days=1)
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=10)
    events_svc.create_event(db, title="dentist", start=start, end=start + timedelta(hours=1))
    tasks_svc.create_task(db, title="loose end", planned_for=day)

    page = client.get(f"/calendar?week={day.isoformat()}").text
    assert "calendar-grid" in page and "dentist" in page
    # Tasks take no time here: no tray of them to schedule.
    assert "loose end" not in page and 'id="calendar-tray"' not in page


def test_nudge_banner_and_dismiss(client, db) -> None:
    from datetime import datetime, timedelta

    from app.services import nudges as nudges_svc

    now = datetime.now()
    task = tasks_svc.create_task(db, title="pay invoice", due=TODAY + timedelta(days=1))
    [nudge] = nudges_svc.evaluate(db, now)

    # The nudge center opens the day, on Today; a past day's page has none.
    page = client.get("/today").text
    assert "nudge-center" in page
    assert "“pay invoice” is due tomorrow." in page
    # Its Open is the task's own page.
    assert f'<a class="nudge-action" href="/tasks/{task.id}">Open</a>' in page
    assert "nudge-center" not in client.get(f"/day/{TODAY - timedelta(days=1)}").text

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


def test_a_folded_project_stays_folded_on_the_timeline(client, db) -> None:
    p = projects_svc.create_project(db, name="Reno")
    m = projects_svc.create_workstream(db, project_id=p.id, name="quotes in")
    tasks_svc.create_task(db, title="call sparky", project_id=p.id, workstream_id=m.id)

    def group() -> str:
        return client.get("/projects").text.split(f'id="timeline-{p.id}"')[0].rsplit("<div", 1)[1]

    assert "folded" not in group()
    assert client.post(f"/ui/projects/{p.id}/fold", data={"folded": "true"}).status_code == 204
    assert projects_svc.get_project(db, p.id).folded
    assert "folded" in group()
    chevron = client.get("/projects").text.split(f'data-project-fold="{p.id}"')[1].split(">")[0]
    assert 'aria-expanded="false"' in chevron

    client.post(f"/ui/projects/{p.id}/fold", data={"folded": "false"})
    assert not projects_svc.get_project(db, p.id).folded
    assert "folded" not in group()


def test_quick_add_files_into_a_project_and_its_workstream(client, db) -> None:
    p = projects_svc.create_project(db, name="Reno")
    m = projects_svc.create_workstream(db, project_id=p.id, name="quotes in")

    row = client.post("/ui/tasks/quick-add", data={"title": "get quotes", "project_id": p.id})
    assert "get quotes" in row.text
    client.post(
        "/ui/tasks/quick-add",
        data={"title": "call sparky", "project_id": p.id, "workstream_id": m.id},
    )
    quotes, sparky = tasks_svc.list_tasks(db, project_id=p.id)
    assert (quotes.title, quotes.workstream_id) == ("get quotes", None)
    assert (sparky.title, sparky.workstream_id) == ("call sparky", m.id)


def test_projects_and_workstreams_redraw_the_lists(client, db) -> None:
    created = client.post("/ui/projects", data={"name": "New thing"})
    assert created.headers["HX-Trigger"] == "tasks:changed, projects:changed"
    assert "New thing" in client.get("/projects").text

    p = projects_svc.list_projects(db)[0]
    added = client.post(f"/ui/projects/{p.id}/workstreams", data={"name": "first cut"})
    assert added.headers["HX-Trigger"] == "tasks:changed"
    assert "first cut" in client.get(f"/projects/{p.id}/tasks").text

    from sqlalchemy import select

    from app.models import Workstream

    m = db.scalars(select(Workstream).where(Workstream.project_id == p.id)).one()
    toggled = client.post(f"/ui/workstreams/{m.id}/toggle")
    assert toggled.headers["HX-Trigger"] == "tasks:changed"
    finished = client.get(f"/projects/{p.id}/tasks").text.split('class="finished-workstreams"')[1]
    assert 'class="workstream done"' in finished and "Mark “first cut” open" in finished


def test_task_rows_carry_a_delete_bin(client, db) -> None:
    task = tasks_svc.create_task(db, title="bin me")
    row = client.get("/plan").text.split(f'id="task-{task.id}"')[1].split("</li>")[0]
    assert f'hx-post="/ui/tasks/{task.id}/delete"' in row
    assert 'data-confirm-name="bin me"' in row


def test_delete_removes_task_and_refreshes_the_grid(client, db) -> None:
    from datetime import datetime

    from app.services import nudges as nudges_svc

    task = tasks_svc.create_task(db, title="pay invoice", planned_for=TODAY, due=TODAY)
    assert nudges_svc.evaluate(db, datetime.now())

    response = client.post(f"/ui/tasks/{task.id}/delete")
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "calendar:refresh"
    assert "pay invoice" not in client.get("/projects").text
    assert "nudge-center" not in client.get("/today").text


def test_shell_groups_calendar_pages_under_planner(client) -> None:
    page = client.get("/calendar").text
    planner = page.split('id="nav-planner"')[1].split("</div>\n      <div")[0]
    for href in ('href="/today"', 'href="/calendar"'):
        assert href in planner
    # Today leads the group; Tasks and Weeks are gone.
    assert planner.index('href="/today"') < planner.index('href="/calendar"')
    assert 'href="/"' not in planner
    for gone in ('href="/weeks"', 'href="/backlog"'):
        assert gone not in page
    assert 'aria-current="page"' in planner  # Calendar, inside its group


def test_shell_has_theme_toggle_and_collapse_control(client) -> None:
    page = client.get("/today").text
    # the toggle names the modes the installed design system names
    modes = design_system()["modes"]
    assert 'class="rail-button theme-toggle"' in page
    assert modes["light"] in page and modes["dark"] in page
    assert 'class="rail-collapse"' in page and 'aria-controls="main-nav"' in page
    assert "/static/shell.js?v=" in page
    # the saved theme and rail state apply in <head>, before the stylesheet paints
    head = page.split("</head>")[0]
    assert head.index("pc-theme") < head.index("app.css")
    # the design system's stylesheet comes first, and its fonts are preloaded
    assert head.index("/static/design/design.css?v=") < head.index("/static/app.css?v=")
    for font in design_system()["fonts"]:
        assert f'href="/static/design/{font}" as="font"' in head


def test_a_task_shows_its_project_as_its_flag_in_its_colour(client, db) -> None:
    p = projects_svc.create_project(db, name="Reno", color=3)
    task = tasks_svc.create_task(db, title="get quotes", planned_for=TODAY, project_id=p.id)

    # Its row: the flag in the project's colour, the name on hover, not written.
    page = client.get(f"/projects/{p.id}/tasks").text
    row = page.split(f'id="task-{task.id}"')[1].split("</li>")[0]
    assert 'class="project-flag" role="img" style="--project: var(--hue-3)"' in row
    assert 'title="Project: Reno"' in row
    assert ">Reno<" not in row
    # Its sheet: the flag set, the name only in its title.
    sheet = client.get(f"/ui/tasks/{task.id}/edit").text
    assert 'class="prop in-project"' in sheet and 'style="--project: var(--hue-3)"' in sheet
    assert 'title="Project: Reno"' in sheet

    # The project's colour is chosen on its page.
    assert 'name="color" value="3" checked' in client.get(f"/projects/{p.id}").text
    client.post(f"/ui/projects/{p.id}/about", data={"color": "6"})
    assert projects_svc.get_project(db, p.id).color == 6
    page = client.get(f"/projects/{p.id}/tasks").text
    row = page.split(f'id="task-{task.id}"')[1].split("</li>")[0]
    assert 'style="--project: var(--hue-6)"' in row


def test_sidebar_lists_the_active_projects_under_projects(client, db) -> None:
    reno = projects_svc.create_project(db, name="Reno", color=3)
    trip = projects_svc.create_project(db, name="Trip")
    shelved = projects_svc.create_project(db, name="Shelved")
    projects_svc.update_project(db, shelved.id, status=ProjectStatus.paused)

    # Every page: each active project under Projects, in its colour, opening its page.
    nav = client.get("/today").text.split('id="main-nav"')[1].split("</nav>")[0]
    sub = nav.split('id="rail-projects"')[1].split("</ul>")[0]
    assert nav.index('href="/projects"') < nav.index('id="rail-projects"')
    assert sub.index(f'href="/projects/{reno.id}"') < sub.index(f'href="/projects/{trip.id}"')
    assert 'style="--project: var(--hue-3)"' in sub and ">Reno<" in sub
    assert "Shelved" not in sub and 'aria-current' not in sub

    # A project's page, and its Gantt: its own row is the page, Projects the set it is in.
    nav = client.get(f"/projects/{reno.id}").text.split('id="main-nav"')[1].split("</nav>")[0]
    projects = nav.split('href="/projects"')[1].split(">")[0]
    assert 'aria-current="true"' in projects
    row = nav.split(f'href="/projects/{reno.id}"')[1].split(">")[0]
    assert 'aria-current="page"' in row

    # Added, renamed or shelved, the list is drawn again, the open one still current.
    assert 'hx-trigger="projects:changed from:body"' in nav
    again = client.get(f"/ui/rail/projects?current={reno.id}").text
    assert f'hx-get="/ui/rail/projects?current={reno.id}"' in again
    assert 'aria-current="page"' in again.split(f'href="/projects/{reno.id}"')[1].split(">")[0]
    renamed = client.post(f"/ui/projects/{trip.id}/about", data={"name": "Road trip"})
    assert "projects:changed" in renamed.headers["HX-Trigger"]
    assert ">Road trip<" in client.get("/ui/rail/projects").text


def test_health_is_its_own_nav_group_with_nutrition(client) -> None:
    page = client.get("/nutrition").text
    group = page.split('aria-labelledby="nav-health"')[1].split("</nav>")[0]
    assert 'id="nav-health" title="Drag to move Health">Health</div>' in group
    link = group.split('href="/nutrition"')[1].split("</a>")[0]
    assert 'aria-keyshortcuts="Alt+4"' in link and 'aria-current="page"' in link
    # The day's log beside the day's chat with Claude (test_nutrition.py has the rest).
    main = page.split('<main class="main">')[1]
    assert 'class="chat-page nutrition-page"' in main and 'id="chat-composer"' in main


def test_me_saves_as_it_changes_and_says_what_follows(client, db) -> None:
    page = client.get("/me").text
    assert 'aria-keyshortcuts="Alt+5"' in page and "<h1>Me</h1>" in page
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
    # An older one names its day, its month in capitals ("Wed 30 Sep").
    earlier = date.today() - timedelta(days=9)
    weights = client.post(
        "/ui/me/weight", data={"weight_kg": "81", "day": earlier.isoformat()}
    ).text
    assert f">{earlier:%a} {earlier.day} {earlier:%b}</span>" in weights
    context = client.get("/ui/me/context").text
    assert "Your target is 75 kg: 5.5 kg to lose." in context
    assert "kcal a day keeps your weight" in context

    # A value out of range is refused, with why (the page toasts it).
    refused = client.post("/ui/me", data={**form, "height_cm": "1800"})
    assert refused.status_code == 422 and "Height" in refused.json()["detail"]
