"""The views a project's Tasks tab is drawn in (app/services/task_views.py):
the one chosen from its gear, kept for every project's tab, and the one
?view= shows without choosing it."""

import json
from datetime import date, timedelta
from urllib.parse import quote

import pytest

from app.models import TaskStatus
from app.services import DomainError, task_views
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()


def shown(page: str) -> str:
    return page.split('data-tasks-view="')[1].split('"')[0]


def test_the_list_is_the_view_until_another_is_chosen(db) -> None:
    assert task_views.current(db).key == "list"
    task_views.choose(db, "board")
    assert task_views.current(db).key == "board"
    with pytest.raises(DomainError):
        task_views.choose(db, "gallery")
    assert task_views.current(db).key == "board"


def test_every_view_has_a_partial_and_all_but_the_list_a_row(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    task = tasks_svc.create_task(db, title="parse", project_id=project.id)
    for view in task_views.VIEWS:
        page = client.get(f"/projects/{project.id}/tasks?view={view.key}")
        assert page.status_code == 200 and shown(page.text) == view.key
        row = client.get(f"/ui/tasks/{task.id}/row", headers={"X-Tasks-View": view.key}).text
        assert f'id="task-{task.id}"' in row
    assert {v.key for v in task_views.VIEWS} - {"list"} == task_views.ROW_VIEWS


def test_the_view_chosen_is_every_projects_and_view_only_shows_one(client, db) -> None:
    one = projects_svc.create_project(db, name="Calendar sync")
    other = projects_svc.create_project(db, name="Garden")
    assert shown(client.get(f"/projects/{one.id}/tasks").text) == "list"
    assert client.post("/ui/tasks-view", data={"view": "table"}).status_code == 204
    assert shown(client.get(f"/projects/{other.id}/tasks").text) == "table"
    # Looked at, not chosen: the next visit opens in the one chosen.
    assert shown(client.get(f"/projects/{one.id}/tasks?view=board").text) == "board"
    assert shown(client.get(f"/projects/{one.id}/tasks").text) == "table"
    assert client.post("/ui/tasks-view", data={"view": "gallery"}).status_code == 422
    assert client.get(f"/projects/{one.id}/tasks?view=gallery").status_code == 404


def test_the_gear_names_the_view_and_ticks_it_and_the_list_redraws_in_it(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    page = client.get(f"/projects/{project.id}/tasks?view=pane").text
    assert 'aria-label="View: List and details"' in page
    assert 'data-view="pane" aria-checked="true"' in page
    assert 'data-view="list" aria-checked="false"' in page
    assert f'hx-get="/projects/{project.id}/tasks?view=pane"' in page
    assert '"X-Tasks-View": "pane"' in page
    # The list sends no view: its rows are every list's task rows.
    assert "X-Tasks-View" not in client.get(f"/projects/{project.id}/tasks").text


def test_a_row_drawn_again_in_the_list_is_the_task_row(client, db) -> None:
    task = tasks_svc.create_task(db, title="parse")
    row = client.get(f"/ui/tasks/{task.id}/row").text
    assert row.lstrip().startswith("<li") and 'class="task-row' in row
    unknown = client.get(f"/ui/tasks/{task.id}/row", headers={"X-Tasks-View": "gallery"}).text
    assert unknown.lstrip().startswith("<li")


def test_open_tasks_are_grouped_by_when_they_are_to_be_done(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    for title, day in [
        ("late", TODAY - timedelta(days=2)),
        ("now", TODAY),
        ("next", TODAY + timedelta(days=1)),
        ("soon", TODAY + timedelta(days=7)),
        ("far", TODAY + timedelta(days=8)),
        ("someday", None),
    ]:
        tasks_svc.create_task(db, title=title, project_id=project.id, planned_for=day)
    from datetime import datetime

    from app.ui.views import project_tasks_ctx

    when = project_tasks_ctx(db, project, datetime.now())["when"]
    assert [(w["key"], [r["task"].title for r in w["rows"]]) for w in when] == [
        ("overdue", ["late"]),
        ("today", ["now"]),
        ("tomorrow", ["next"]),
        ("week", ["soon"]),
        ("later", ["far"]),
        ("none", ["someday"]),
    ]
    # Each stretch says, beside where it is decided, the day a task dropped
    # on it takes (in days from today, "" for none) and its composer's.
    assert [(w["key"], w["drop"], w["offset"]) for w in when] == [
        ("overdue", False, ""),
        ("today", True, 0),
        ("tomorrow", True, 1),
        ("week", True, 2),
        ("later", True, 8),
        ("none", True, ""),
    ]
    composers = {w["key"]: (w["composer"], w["planned_for"]) for w in when if w["composer"]}
    assert composers == {
        "today": ("Add task for today…", TODAY),
        "tomorrow": ("Add task for tomorrow…", TODAY + timedelta(days=1)),
        "none": ("Add task…", None),
    }


def test_each_view_is_drawn_as_it_was_left_on_the_device(client, db) -> None:
    """Folds, sub-tasks shown, Show completed and the task picked, from the
    tab's cookie (tasks-views.js writes it), so no first paint is wrong."""
    project = projects_svc.create_project(db, name="Calendar sync")
    api = projects_svc.create_workstream(db, project_id=project.id, name="API")
    task = tasks_svc.create_task(
        db, title="parse", project_id=project.id, workstream_id=api.id, notes="- [ ] read"
    )
    done = tasks_svc.create_task(db, title="old", project_id=project.id)
    tasks_svc.set_status(db, done.id, TaskStatus.done)
    url = f"/projects/{project.id}/tasks"
    state = {
        "table": {"folds": [f"ws-{api.id}"], "subtasks": [task.id], "done": True},
        "pane": {"picked": task.id},
    }
    client.cookies.set(task_views.STATE_COOKIE, quote(json.dumps(state)), path=url)
    table = client.get(f"{url}?view=table").text
    section = table.split(f'id="tt-ws-{api.id}"')[0].rsplit("<section", 1)[1]
    assert 'class="tv-section folded"' in section
    assert 'aria-label="0 of 1 sub-tasks done: hide them"' in table
    assert f'id="tv-subtasks-{task.id}">' in table  # shown
    assert "data-done-part hidden" not in table and "data-show-done checked" in table
    # Another view keeps its own: the pane's task picked, in its pane.
    pane = client.get(f"{url}?view=pane").text
    assert f'data-lp-for="{task.id}"' in pane.split('class="lp-details"')[1]
    assert 'class="task-row lp-line picked"' in pane and 'class="tv-section folded"' not in pane
    # A cookie it cannot read is no state at all.
    client.cookies.set(task_views.STATE_COOKIE, "not json", path=url)
    assert client.get(f"{url}?view=table").status_code == 200
    assert task_views.state("%7B%22table%22%3A1%7D", "table") == task_views.State()


def test_the_toolbar_says_the_views_keys_and_shows_completed_beside_the_gear(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    url = f"/projects/{project.id}/tasks"

    def toolbar(view: str) -> str:
        page = client.get(f"{url}?view={view}").text
        return page.split('class="tasks-toolbar"')[1].split('id="project-tasks"')[0]

    def hint(view: str) -> str:
        return toolbar(view).split('class="keys-hint"')[1].split("</p>")[0]

    # The Board's arrows cross its columns; Space opens what a row folds away.
    assert "column" in hint("board") and "description" in hint("board")
    assert "column" not in hint("table") and "sub-tasks" in hint("table")
    assert "sub-tasks" in hint("schedule") and "details" in hint("pane")
    assert "Space" not in hint("list")
    # Show completed keeps its place while nothing is finished; the list has its Done fold.
    assert 'id="tasks-show-done" data-none' in toolbar("table")
    assert "tasks-show-done" not in toolbar("list")
    task = tasks_svc.create_task(db, title="parse", project_id=project.id)
    tasks_svc.set_status(db, task.id, TaskStatus.done)
    bar = toolbar("table")
    assert "data-none" not in bar and 'Show completed <span class="count">1</span>' in bar
    # It comes with every redraw of the list, as the page's head does.
    page = client.get(f"{url}?view=table").text
    assert 'hx-select-oob="#project-head, #tasks-show-done"' in page
