"""A project's Gantt: reading weeks and days as written in its cells, a
task's span kept whole, the sheet's edits, and its page."""

from datetime import date, timedelta

import pytest

from app.models import TaskStatus, WorkstreamStatus
from app.services import DomainError
from app.services import gantt as gantt_svc
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

# A Wednesday in ISO week 40 of 2026 (Monday 28 September).
TODAY = date(2026, 9, 30)
W40 = date(2026, 9, 28)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A week starts on its Monday...
        ("40", (W40, True)),
        ("W40", (W40, True)),
        ("w 41", (W40 + timedelta(weeks=1), True)),
        ("2026-W40", (W40, True)),
        ("this week", (W40, True)),
        ("next week", (W40 + timedelta(weeks=1), True)),
        ("1", (date(2027, 1, 4), True)),  # 2027's week 1, nearer than 2026's
        # ...and a day on itself.
        ("1 oct", (date(2026, 10, 1), False)),
        ("16/10", (date(2026, 10, 16), False)),
        ("2026-10-14", (date(2026, 10, 14), False)),
        ("thu", (date(2026, 10, 1), False)),
    ],
)
def test_a_start_is_the_week_or_the_day_written(text, expected) -> None:
    assert gantt_svc.parse_start(text, TODAY) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("16 Oct", date(2026, 10, 16)),
        ("Oct 16", date(2026, 10, 16)),
        ("Fri 16 Oct", date(2026, 10, 16)),
        ("16/10/27", date(2027, 10, 16)),
        ("fri", date(2026, 10, 2)),
        ("wed", TODAY),
        ("today", TODAY),
        ("tomorrow", date(2026, 10, 1)),
        ("W42", date(2026, 10, 16)),  # a week for a due is its Friday
        ("5 jan", date(2027, 1, 5)),  # nearer next January than last
    ],
)
def test_a_due_is_the_day_written(text, expected) -> None:
    assert gantt_svc.parse_due(text, TODAY) == expected


@pytest.mark.parametrize("text", ["soon", "31/2", "W60", "banana 3"])
def test_what_is_not_a_date_is_refused(text) -> None:
    with pytest.raises(DomainError):
        gantt_svc.parse_due(text, TODAY)


def test_a_length_is_a_whole_number_of_the_view_s_unit_or_the_one_named() -> None:
    assert gantt_svc.parse_length("3", "week") == (3, "week")
    assert gantt_svc.parse_length(" 2w ", "day") == (2, "week")
    assert gantt_svc.parse_length("10d", "week") == (10, "day")
    assert gantt_svc.parse_length("5 days", "week") == (5, "day")
    assert gantt_svc.parse_length("400", "day") == (400, "day")
    for bad in ("0", "-1", "1.5", "lots", "999", "3x"):
        with pytest.raises(DomainError):
            gantt_svc.parse_length(bad, "week")


def test_a_span_stays_whole(db) -> None:
    # A start alone keeps its day, and ends that week's Friday.
    task = tasks_svc.create_task(db, title="Spec", starts_on=W40 + timedelta(days=2))
    assert (task.starts_on, task.due) == (date(2026, 9, 30), date(2026, 10, 2))
    # At a weekend, it ends on itself.
    weekend = tasks_svc.create_task(db, title="Sat", starts_on=date(2026, 10, 3))
    assert weekend.due == date(2026, 10, 3)
    # A due moved before the start pulls the start back to its week.
    tasks_svc.update_task(db, task.id, due=date(2026, 9, 22))
    assert task.starts_on == date(2026, 9, 21)
    # A start given after the due is refused.
    with pytest.raises(DomainError):
        tasks_svc.update_task(db, task.id, starts_on=date(2026, 10, 5))
    # Clearing the due takes the start with it.
    tasks_svc.update_task(db, task.id, due=None)
    assert task.starts_on is None


def _project(db):
    project = projects_svc.create_project(db, name="Beta")
    launch = projects_svc.create_workstream(db, project_id=project.id, name="Launch")
    return project, launch


def test_cells_write_a_bar_in_weeks(db) -> None:
    project, _ = _project(db)
    task = tasks_svc.create_task(db, title="Spec", project_id=project.id)

    def edit(**op) -> None:
        gantt_svc.apply(db, project, [{"op": "task", "id": task.id, **op}], TODAY)

    edit(start="40")
    assert (task.starts_on, task.due, gantt_svc.length_of(task, "week")) == (
        W40, date(2026, 10, 2), 1)
    assert gantt_svc.length_of(task, "day") == 5

    # Weeks stretch it from its start, its due keeping its weekday.
    edit(length="3")
    assert (task.due, gantt_svc.length_of(task, "week")) == (date(2026, 10, 16), 3)

    # A new start moves the bar whole.
    edit(start="W42")
    assert (task.starts_on, task.due) == (date(2026, 10, 12), date(2026, 10, 30))

    # A due moves the end only.
    edit(due="wed 21 oct")
    assert (task.starts_on, task.due) == (date(2026, 10, 12), date(2026, 10, 21))

    # Drawn over weeks (either way round): those weeks, the due keeping its Wednesday.
    edit(span=["2026-10-19", "2026-10-05"])
    assert (task.starts_on, task.due) == (date(2026, 10, 5), date(2026, 10, 21))

    # Moved and stretched by whole weeks; never shorter than a week.
    edit(shift=-1)
    assert (task.starts_on, task.due) == (date(2026, 9, 28), date(2026, 10, 14))
    edit(grow=-5)
    assert task.due == date(2026, 10, 14)
    edit(grow=-2)
    assert (task.due, gantt_svc.length_of(task, "week")) == (date(2026, 9, 30), 1)

    # Cleared: the span, then the due.
    edit(clear="span")
    assert (task.starts_on, task.due) == (None, date(2026, 9, 30))
    edit(clear="due")
    assert task.due is None


def test_cells_write_a_bar_in_days(db) -> None:
    project, _ = _project(db)
    task = tasks_svc.create_task(db, title="Spec", project_id=project.id)

    def edit(**op) -> None:
        gantt_svc.apply(db, project, [{"op": "task", "id": task.id, "unit": "day", **op}], TODAY)

    # A day for its start, days for its length.
    edit(start="wed")
    assert (task.starts_on, task.due) == (TODAY, date(2026, 10, 2))
    edit(length="4")
    assert (task.due, gantt_svc.length_of(task, "day")) == (date(2026, 10, 3), 4)
    # A week for its start keeps the weekday it started on, and its length.
    edit(start="W42")
    assert (task.starts_on, task.due) == (date(2026, 10, 14), date(2026, 10, 17))
    # Drawn over days: exactly those days.
    edit(span=["2026-10-06", "2026-10-08"])
    assert (task.starts_on, task.due) == (date(2026, 10, 6), date(2026, 10, 8))
    # Moved, stretched and started by days; never shorter than a day.
    edit(shift=2)
    assert (task.starts_on, task.due) == (date(2026, 10, 8), date(2026, 10, 10))
    edit(grow=-1)
    assert task.due == date(2026, 10, 9)
    edit(move_start=1)
    assert task.starts_on == date(2026, 10, 9)
    edit(move_start=1)
    assert task.starts_on == date(2026, 10, 9)
    # A length in weeks, named, in the Days view.
    edit(length="2w")
    assert (task.starts_on, task.due) == (date(2026, 10, 9), date(2026, 10, 16))


def test_rows_are_dropped_into_another_place_and_workstream(db) -> None:
    project, launch = _project(db)
    made = gantt_svc.apply(
        db, project,
        [{"op": "create", "workstream_id": launch.id, "title": t} for t in ("Spec", "Build")]
        + [{"op": "create", "workstream_id": "", "title": t} for t in ("Docs", "Ship")],
        TODAY,
    )
    spec, build, docs, ship = (tasks_svc.get_task(db, i) for i in made)

    def order():
        return [[t.title for t in g.tasks] for g in gantt_svc.groups(db, project, TODAY)]

    def place(task, workstream_id, before=None) -> None:
        gantt_svc.apply(
            db, project,
            [{"op": "place", "id": task.id, "workstream_id": workstream_id,
              "before": before.id if before else None}],
            TODAY,
        )

    # Into the workstream, between its tasks.
    place(ship, launch.id, before=build)
    assert order() == [["Spec", "Ship", "Build"], ["Docs"]]
    assert ship.workstream_id == launch.id
    # Out of it, to the other tasks' end.
    place(spec, "")
    assert order() == [["Ship", "Build"], ["Docs", "Spec"]]
    assert spec.workstream_id is None
    # Within its group, to the top.
    place(spec, "", before=docs)
    assert order() == [["Ship", "Build"], ["Spec", "Docs"]]
    # A workstream of another project is refused.
    other = projects_svc.create_project(db, name="Other")
    elsewhere = projects_svc.create_workstream(db, project_id=other.id, name="Elsewhere")
    with pytest.raises(DomainError):
        place(spec, elsewhere.id)


def test_the_days_view_has_a_column_a_day(client, db) -> None:
    project, launch = _project(db)
    today = date.today()
    tasks_svc.create_task(
        db, title="Spec", project_id=project.id, starts_on=today, due=today + timedelta(days=2),
    )
    db.commit()
    page = client.get(f"/projects/{project.id}/gantt?scale=days").text
    assert 'data-scale="days"' in page and '<abbr title="Days">Days</abbr>' in page
    assert f'data-day="{today.isoformat()}"' in page and "--n: 3.0" in page
    # Remembered: the sheet comes back in days.
    assert 'data-scale="days"' in client.get(f"/ui/projects/{project.id}/gantt").text
    assert 'data-scale="weeks"' in client.get(f"/projects/{project.id}/gantt?scale=weeks").text


def test_weeks_on_a_task_due_reach_back_from_its_due(db) -> None:
    project, _ = _project(db)
    task = tasks_svc.create_task(db, title="Ship", project_id=project.id, due=date(2026, 10, 21))
    gantt_svc.apply(db, project, [{"op": "task", "id": task.id, "length": "2"}], TODAY)
    assert (task.starts_on, task.due) == (date(2026, 10, 12), date(2026, 10, 21))


def test_an_edit_keeps_to_its_project(db) -> None:
    project, _ = _project(db)
    other = projects_svc.create_project(db, name="Other")
    stranger = tasks_svc.create_task(db, title="Not here", project_id=other.id)
    with pytest.raises(DomainError):
        gantt_svc.apply(db, project, [{"op": "task", "id": stranger.id, "title": "x"}], TODAY)


def test_rows_are_written_moved_and_undone(db) -> None:
    project, launch = _project(db)
    made = gantt_svc.apply(
        db, project,
        [
            {"op": "create", "workstream_id": launch.id, "title": "Spec", "start": "40",
             "length": "2"},
            {"op": "create", "workstream_id": launch.id, "title": "Build"},
            {"op": "create", "workstream_id": "", "title": "Docs", "due": "W43"},
        ],
        TODAY,
    )
    spec, build, docs = (tasks_svc.get_task(db, i) for i in made)
    assert (spec.workstream_id, spec.starts_on, spec.due) == (launch.id, W40, date(2026, 10, 9))
    assert (docs.workstream_id, docs.due) == (None, date(2026, 10, 23))

    def order():
        return [[t.title for t in g.tasks] for g in gantt_svc.groups(db, project, TODAY)]

    assert order() == [["Spec", "Build"], ["Docs"]]
    gantt_svc.apply(db, project, [{"op": "move", "id": build.id, "step": -1}], TODAY)
    assert order() == [["Build", "Spec"], ["Docs"]]
    # Past its group's end, into the next: out of the workstream.
    gantt_svc.apply(db, project, [{"op": "move", "id": spec.id, "step": 1}], TODAY)
    assert order() == [["Build"], ["Spec", "Docs"]]
    assert spec.workstream_id is None
    gantt_svc.apply(db, project, [{"op": "move", "id": spec.id, "step": -1}], TODAY)
    assert order() == [["Build", "Spec"], ["Docs"]]

    # Set: every field as it was, which is how the sheet undoes.
    gantt_svc.apply(
        db, project,
        [{"op": "task", "id": spec.id, "status": "done", "title": "Spec it", "clear": "due"}],
        TODAY,
    )
    assert (spec.status, spec.title, spec.due) == (TaskStatus.done, "Spec it", None)
    gantt_svc.apply(db, project, [{"op": "task", "id": spec.id, "status": "needs_review"}], TODAY)
    assert spec.status == TaskStatus.needs_review
    with pytest.raises(DomainError):
        gantt_svc.apply(db, project, [{"op": "task", "id": spec.id, "status": "later"}], TODAY)
    was = {"title": "Spec", "status": "todo", "starts_on": "2026-09-28", "due": "2026-10-09"}
    gantt_svc.apply(db, project, [{"op": "task", "id": spec.id, "set": was}], TODAY)
    assert (spec.status, spec.title, spec.starts_on, spec.due) == (
        TaskStatus.todo, "Spec", W40, date(2026, 10, 9))

    gantt_svc.apply(db, project, [{"op": "delete", "id": docs.id}], TODAY)
    assert order() == [["Build", "Spec"], []]


def test_workstreams_are_written_in_the_sheet(db) -> None:
    project, launch = _project(db)
    gantt_svc.apply(
        db, project, [{"op": "workstream", "id": launch.id, "name": "Go live", "done": True}],
        TODAY,
    )
    assert (launch.name, launch.status) == ("Go live", WorkstreamStatus.done)
    gantt_svc.apply(
        db, project,
        [{"op": "workstream", "id": launch.id, "set": {"name": "Launch", "status": "open"}}],
        TODAY,
    )
    assert (launch.name, launch.status) == ("Launch", WorkstreamStatus.open)
    (made,) = gantt_svc.apply(db, project, [{"op": "workstream_create", "name": "Beta"}], TODAY)
    assert projects_svc.get_project(db, project.id).workstreams[-1].id == made

    # Deleted, a workstream's tasks stay in the project, in none.
    task = tasks_svc.create_task(db, title="Spec", project_id=project.id, workstream_id=made)
    gantt_svc.apply(db, project, [{"op": "workstream_delete", "id": made}], TODAY)
    assert task.workstream_id is None and task.project_id == project.id
    assert [w.name for w in projects_svc.get_project(db, project.id).workstreams] == ["Launch"]


def test_the_gantt_page_draws_the_plan(client, db) -> None:
    project, launch = _project(db)
    today = date.today()
    this = today - timedelta(days=today.weekday())
    tasks_svc.create_task(
        db, title="Spec", project_id=project.id, workstream_id=launch.id,
        starts_on=this, due=this + timedelta(days=11),
    )
    tasks_svc.create_task(db, title="Loose end", project_id=project.id)
    db.commit()

    page = client.get(f"/projects/{project.id}/gantt").text
    assert "Beta" in page and 'role="grid"' in page
    assert 'data-edit="title"' in page and "Spec" in page and "Loose end" in page
    assert "Add a task to Launch…" in page
    # The row to add a workstream heads the tasks in none.
    assert page.index("Add a workstream…") < page.index("Loose end")
    # In weeks, a bar is drawn to the day: twelve days are 12/7 of a column.
    assert 'class="gantt-bar"' in page and "--n: 1.7143" in page
    # A workstream's lane: its tasks' summary, its Due their last due, no dates of its own.
    assert 'class="gantt-summary"' in page and 'data-key="w' in page
    # The Projects card's bars icon opens it.
    projects = client.get("/projects").text
    assert f'<a class="card-edit-btn" href="/projects/{project.id}/gantt"' in projects


def test_the_sheet_is_edited_through_one_request(client, db) -> None:
    project, launch = _project(db)
    db.commit()
    response = client.post(
        f"/ui/projects/{project.id}/gantt",
        json={"ops": [{"op": "create", "workstream_id": launch.id, "title": "Spec",
                       "start": "next week", "length": "2"}]},
    )
    assert response.status_code == 200
    (made,) = map(int, response.headers["X-Gantt-Made"].split(","))
    assert f'data-key="t{made}"' in response.text and "--n: 1.7143" in response.text

    refused = client.post(
        f"/ui/projects/{project.id}/gantt",
        json={"ops": [{"op": "task", "id": made, "length": "many"}]},
    )
    assert refused.status_code == 422 and "1 to 260 weeks" in refused.json()["detail"]
