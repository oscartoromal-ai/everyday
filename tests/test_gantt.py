"""A project's Gantt: reading weeks and days as written in its cells, a
task's span kept whole, the sheet's edits, and its page."""

from datetime import date, timedelta

import pytest

from app.models import MilestoneStatus, TaskStatus
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
        ("40", W40),
        ("W40", W40),
        ("w 41", W40 + timedelta(weeks=1)),
        ("2026-W40", W40),
        ("this week", W40),
        ("next week", W40 + timedelta(weeks=1)),
        ("1", date(2027, 1, 4)),  # 2027's week 1, nearer than 2026's
        ("1 oct", W40),
        ("16/10", date(2026, 10, 12)),
        ("2026-10-14", date(2026, 10, 12)),
    ],
)
def test_a_start_is_the_monday_of_the_week_written(text, expected) -> None:
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


def test_weeks_are_a_whole_number() -> None:
    assert gantt_svc.parse_weeks("3") == 3
    assert gantt_svc.parse_weeks(" 2w ") == 2
    for bad in ("0", "-1", "1.5", "lots", "999"):
        with pytest.raises(DomainError):
            gantt_svc.parse_weeks(bad)


def test_a_span_stays_whole(db) -> None:
    # A start alone ends that week's Friday, on its Monday whatever day was given.
    task = tasks_svc.create_task(db, title="Spec", starts_on=W40 + timedelta(days=2))
    assert (task.starts_on, task.due) == (W40, date(2026, 10, 2))
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
    launch = projects_svc.create_milestone(
        db, project_id=project.id, name="Launch", target_date=date(2026, 10, 23)
    )
    return project, launch


def test_cells_write_a_bar_in_weeks(db) -> None:
    project, _ = _project(db)
    task = tasks_svc.create_task(db, title="Spec", project_id=project.id)

    def edit(**op) -> None:
        gantt_svc.apply(db, project, [{"op": "task", "id": task.id, **op}], TODAY)

    edit(start="40")
    assert (task.starts_on, task.due, gantt_svc.weeks_of(task)) == (W40, date(2026, 10, 2), 1)

    # Weeks stretch it from its start, its due keeping its weekday.
    edit(weeks="3")
    assert (task.due, gantt_svc.weeks_of(task)) == (date(2026, 10, 16), 3)

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
    assert (task.due, gantt_svc.weeks_of(task)) == (date(2026, 9, 30), 1)

    # Cleared: the span, then the due.
    edit(clear="span")
    assert (task.starts_on, task.due) == (None, date(2026, 9, 30))
    edit(clear="due")
    assert task.due is None


def test_weeks_on_a_task_due_reach_back_from_its_due(db) -> None:
    project, _ = _project(db)
    task = tasks_svc.create_task(db, title="Ship", project_id=project.id, due=date(2026, 10, 21))
    gantt_svc.apply(db, project, [{"op": "task", "id": task.id, "weeks": "2"}], TODAY)
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
            {"op": "create", "milestone_id": launch.id, "title": "Spec", "start": "40",
             "weeks": "2"},
            {"op": "create", "milestone_id": launch.id, "title": "Build"},
            {"op": "create", "milestone_id": "", "title": "Docs", "due": "W43"},
        ],
        TODAY,
    )
    spec, build, docs = (tasks_svc.get_task(db, i) for i in made)
    assert (spec.milestone_id, spec.starts_on, spec.due) == (launch.id, W40, date(2026, 10, 9))
    assert (docs.milestone_id, docs.due) == (None, date(2026, 10, 23))

    def order():
        return [[t.title for t in g.tasks] for g in gantt_svc.groups(db, project, TODAY)]

    assert order() == [["Spec", "Build"], ["Docs"]]
    gantt_svc.apply(db, project, [{"op": "move", "id": build.id, "step": -1}], TODAY)
    assert order() == [["Build", "Spec"], ["Docs"]]
    # Past its group's end, into the next: out of the milestone.
    gantt_svc.apply(db, project, [{"op": "move", "id": spec.id, "step": 1}], TODAY)
    assert order() == [["Build"], ["Spec", "Docs"]]
    assert spec.milestone_id is None
    gantt_svc.apply(db, project, [{"op": "move", "id": spec.id, "step": -1}], TODAY)
    assert order() == [["Build", "Spec"], ["Docs"]]

    # Set: every field as it was, which is how the sheet undoes.
    gantt_svc.apply(
        db, project,
        [{"op": "task", "id": spec.id, "done": True, "title": "Spec it", "clear": "due"}],
        TODAY,
    )
    assert (spec.status, spec.title, spec.due) == (TaskStatus.done, "Spec it", None)
    was = {"title": "Spec", "status": "todo", "starts_on": "2026-09-28", "due": "2026-10-09"}
    gantt_svc.apply(db, project, [{"op": "task", "id": spec.id, "set": was}], TODAY)
    assert (spec.status, spec.title, spec.starts_on, spec.due) == (
        TaskStatus.todo, "Spec", W40, date(2026, 10, 9))

    gantt_svc.apply(db, project, [{"op": "delete", "id": docs.id}], TODAY)
    assert order() == [["Build", "Spec"], []]


def test_milestones_are_written_in_the_sheet(db) -> None:
    project, launch = _project(db)
    gantt_svc.apply(
        db, project,
        [{"op": "milestone", "id": launch.id, "name": "Go live", "shift": 1, "reached": True}],
        TODAY,
    )
    assert (launch.name, launch.target_date, launch.status) == (
        "Go live", date(2026, 10, 30), MilestoneStatus.reached)
    gantt_svc.apply(db, project, [{"op": "milestone", "id": launch.id, "target": ""}], TODAY)
    assert launch.target_date is None
    (made,) = gantt_svc.apply(
        db, project, [{"op": "milestone_create", "name": "Beta", "target": "W45"}], TODAY
    )
    assert projects_svc.get_project(db, project.id).milestones[-1].id == made


def test_the_gantt_page_draws_the_plan(client, db) -> None:
    project, launch = _project(db)
    today = date.today()
    this = today - timedelta(days=today.weekday())
    tasks_svc.create_task(
        db, title="Spec", project_id=project.id, milestone_id=launch.id,
        starts_on=this, due=this + timedelta(days=11),
    )
    tasks_svc.create_task(db, title="Loose end", project_id=project.id)
    db.commit()

    page = client.get(f"/projects/{project.id}").text
    assert "Beta" in page and 'role="grid"' in page
    assert 'data-edit="title"' in page and "Spec" in page and "Loose end" in page
    assert "Other tasks" in page and "Add a task to Launch…" in page
    assert 'class="gantt-bar"' in page and "--n: 2" in page
    assert 'class="gantt-diamond' in page
    # The Projects card opens it.
    assert f'href="/projects/{project.id}"' in client.get("/projects").text


def test_the_sheet_is_edited_through_one_request(client, db) -> None:
    project, launch = _project(db)
    db.commit()
    response = client.post(
        f"/ui/projects/{project.id}/gantt",
        json={"ops": [{"op": "create", "milestone_id": launch.id, "title": "Spec",
                       "start": "next week", "weeks": "2"}]},
    )
    assert response.status_code == 200
    (made,) = map(int, response.headers["X-Gantt-Made"].split(","))
    assert f'data-key="t{made}"' in response.text and "--n: 2" in response.text

    refused = client.post(
        f"/ui/projects/{project.id}/gantt",
        json={"ops": [{"op": "task", "id": made, "weeks": "many"}]},
    )
    assert refused.status_code == 422 and "1 to 260 weeks" in refused.json()["detail"]
