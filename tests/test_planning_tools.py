"""The planning tools around a task: keyboard triage hooks and filing by drag."""

from datetime import date

from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()


def _row(page: str, task_id: int) -> str:
    return page.split(f'id="task-{task_id}"')[1].split("</li>")[0]


def test_planning_rows_take_keyboard_focus_and_name_their_actions(client, db) -> None:
    task = tasks_svc.create_task(db, title="triage me")
    page = client.get("/plan").text
    row = page.split(f'id="task-{task.id}"')[1].split(">")[0]
    # The row itself is focusable (the keys act on it), but not a Tab stop.
    assert 'tabindex="-1"' in row
    buttons = _row(page, task.id)
    assert 'data-plan="today"' in buttons and 'data-plan="tomorrow"' in buttons
    # The rows are cursor stops, inside the page's cursor area.
    assert 'id="plan-lists" class="task-lists" data-cursor' in page


def test_task_lists_and_workstreams_are_drop_targets(client, db) -> None:
    p = projects_svc.create_project(db, name="Calendar sync")
    m = projects_svc.create_workstream(db, project_id=p.id, name="ICS import")
    tasks_svc.create_task(db, title="parse", project_id=p.id, workstream_id=m.id)
    tasks_svc.create_task(db, title="loose one")

    # A project's Tasks: the project, and each of its workstreams.
    page = client.get(f"/projects/{p.id}/tasks").text
    assert f'data-file-project="{p.id}"' in page
    assert f'data-file-workstream="{m.id}"' in page
    # The list re-renders when a task is filed elsewhere.
    assert "tasks:changed from:body" in page.split('id="project-tasks"')[1][:600]
    # Plan: No project, and each project's list.
    plan = client.get("/plan").text
    assert 'id="group-loose" data-file-project=""' in plan
    assert f'data-file-project="{p.id}"' in plan
    assert "tasks:changed from:body" in plan.split('id="plan-lists"')[1][:600]


def test_filing_moves_a_task_between_workstreams_projects_and_none(client, db) -> None:
    p = projects_svc.create_project(db, name="Calendar sync")
    other = projects_svc.create_project(db, name="Home")
    m = projects_svc.create_workstream(db, project_id=p.id, name="ICS import")
    task = tasks_svc.create_task(db, title="parse")

    # What a drop sends: onto a workstream, onto another project, onto No project.
    assert client.patch(
        f"/api/tasks/{task.id}", json={"project_id": p.id, "workstream_id": m.id}
    ).status_code == 200
    assert (task.project_id, task.workstream_id) == (p.id, m.id)
    client.patch(f"/api/tasks/{task.id}", json={"project_id": other.id, "workstream_id": None})
    assert (task.project_id, task.workstream_id) == (other.id, None)
    client.patch(f"/api/tasks/{task.id}", json={"project_id": None, "workstream_id": None})
    assert (task.project_id, task.workstream_id) == (None, None)
    # A workstream of another project is refused, with a reason to show.
    refused = client.patch(
        f"/api/tasks/{task.id}", json={"project_id": other.id, "workstream_id": m.id}
    )
    assert refused.status_code >= 400 and "workstream" in refused.json()["detail"].lower()


def test_a_save_is_committed_before_its_response_is_sent() -> None:
    # A page re-renders the moment a save returns (drag-to-file, an event's
    # drag); the commit has to land first. FastAPI's default scope for
    # a yield dependency tears it down only after the response is sent.
    from typing import get_args

    from app.db import DbSession

    _, depends = get_args(DbSession)
    assert depends.scope == "function"
