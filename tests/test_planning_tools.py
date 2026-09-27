"""The planning tools around a task: keyboard triage hooks, filing by drag,
and a block's checklist on the calendar."""

from datetime import date, datetime, timedelta

from app.services import blocks as blocks_svc
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()


def _row(page: str, task_id: int) -> str:
    return page.split(f'id="task-{task_id}"')[1].split("</li>")[0]


def test_planning_rows_take_keyboard_focus_and_name_their_actions(client, db) -> None:
    task = tasks_svc.create_task(db, title="triage me")
    row = client.get("/").text.split(f'id="task-{task.id}"')[1].split(">")[0]
    # The row itself is focusable (the keys act on it), but not a Tab stop.
    assert 'tabindex="-1"' in row
    buttons = _row(client.get("/").text, task.id)
    assert 'data-plan="today"' in buttons and 'data-plan="tomorrow"' in buttons
    # Today's and Projects' rows are cursor stops too, inside their pages' cursor areas.
    tasks_svc.update_task(db, task.id, planned_for=TODAY)
    today = client.get("/today").text
    assert 'tabindex="-1"' in today.split(f'id="task-{task.id}"')[1].split(">")[0]
    assert 'class="day-sheet" data-cursor' in today
    assert 'id="projects" data-cursor' in client.get("/projects").text


def test_project_cards_and_milestones_are_drop_targets(client, db) -> None:
    p = projects_svc.create_project(db, name="Calendar sync")
    m = projects_svc.create_milestone(db, project_id=p.id, name="ICS import")
    tasks_svc.create_task(db, title="parse", project_id=p.id, milestone_id=m.id)
    tasks_svc.create_task(db, title="loose one")

    page = client.get("/?view=project").text
    assert f'data-file-project="{p.id}"' in page
    assert f'data-file-milestone="{m.id}"' in page
    assert 'id="group-loose" data-file-project=""' in page
    # Projects re-renders when a task is filed elsewhere.
    projects = client.get("/projects").text
    assert 'hx-trigger="tasks:changed from:body"' in projects.split('id="projects"')[1][:300]


def test_filing_moves_a_task_between_milestones_projects_and_none(client, db) -> None:
    p = projects_svc.create_project(db, name="Calendar sync")
    other = projects_svc.create_project(db, name="Home")
    m = projects_svc.create_milestone(db, project_id=p.id, name="ICS import")
    task = tasks_svc.create_task(db, title="parse")

    # What a drop sends: onto a milestone, onto another project, onto No project.
    assert client.patch(
        f"/api/tasks/{task.id}", json={"project_id": p.id, "milestone_id": m.id}
    ).status_code == 200
    assert (task.project_id, task.milestone_id) == (p.id, m.id)
    client.patch(f"/api/tasks/{task.id}", json={"project_id": other.id, "milestone_id": None})
    assert (task.project_id, task.milestone_id) == (other.id, None)
    client.patch(f"/api/tasks/{task.id}", json={"project_id": None, "milestone_id": None})
    assert (task.project_id, task.milestone_id) == (None, None)
    # A milestone of another project is refused, with a reason to show.
    refused = client.patch(
        f"/api/tasks/{task.id}", json={"project_id": other.id, "milestone_id": m.id}
    )
    assert refused.status_code >= 400 and "milestone" in refused.json()["detail"].lower()


def test_block_menu_lists_the_tasks_subtasks(client, db) -> None:
    task = tasks_svc.create_task(
        db, title="ship sync", planned_for=TODAY, notes="Context.\n- fetch\n- [x] parse"
    )
    start = datetime.combine(TODAY, datetime.min.time()) + timedelta(hours=12)
    blocks_svc.schedule_block(db, task_id=task.id, start=start, end=start + timedelta(hours=1))

    page = client.get("/calendar").text
    assert f'data-task-id="{task.id}" data-state="planned"' in page
    assert f'hx-get="/ui/tasks/{task.id}/checklist"' not in page  # set when a menu opens

    checklist = client.get(f"/ui/tasks/{task.id}/checklist").text
    assert "fetch" in checklist and "parse" in checklist
    assert "Context." not in checklist  # context stays in the description
    assert '<span class="progress">1/2</span>' in checklist
    assert 'hx-target="closest .block-menu-checklist"' in checklist


def test_ticking_in_a_block_menu_returns_the_checklist(client, db) -> None:
    task = tasks_svc.create_task(db, title="ship sync", notes="- fetch\n- parse")
    response = client.post(
        f"/ui/tasks/{task.id}/subtasks/0/toggle",
        data={"text": "fetch"},
        headers={"X-Row-Context": "block"},
    )
    assert task.notes == "- [x] fetch\n- parse"
    assert "block-checklist" in response.text and "task-row" not in response.text
    # Today's list, beside the timeline, catches up with the count.
    assert response.headers["HX-Trigger"] == "tasks:changed"


def test_a_task_without_subtasks_adds_nothing_to_its_menu(client, db) -> None:
    task = tasks_svc.create_task(db, title="plain", notes="Only context.")
    assert client.get(f"/ui/tasks/{task.id}/checklist").text.strip() == ""


def test_a_save_is_committed_before_its_response_is_sent() -> None:
    # A page re-renders the moment a save returns (drag-to-file, Weeks' drag,
    # block moves); the commit has to land first. FastAPI's default scope for
    # a yield dependency tears it down only after the response is sent.
    from typing import get_args

    from app.db import DbSession

    _, depends = get_args(DbSession)
    assert depends.scope == "function"
