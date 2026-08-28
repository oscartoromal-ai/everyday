from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import create_app
from app.models import TaskOwner, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()


@pytest.fixture
def client(db) -> TestClient:
    app = create_app()

    def override() -> object:
        yield db

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    client.get("/")  # obtain the CSRF cookie
    client.headers["X-CSRF"] = client.cookies.get("csrf", "")
    return client


def test_today_page_shows_planned_and_delegated(client, db) -> None:
    tasks_svc.create_task(db, title="write the plan", planned_for=TODAY)
    claude_task = tasks_svc.create_task(db, title="review PR", owner=TaskOwner.claude)
    tasks_svc.set_status(db, claude_task.id, TaskStatus.needs_review)

    page = client.get("/").text
    assert "write the plan" in page
    assert "Delegated to Claude" in page
    assert "Needs review" in page


def test_next_days_page_groups_by_day(client, db) -> None:
    p = projects_svc.create_project(db, name="App")
    projects_svc.create_milestone(
        db, project_id=p.id, name="v1 ships", target_date=TODAY + timedelta(days=3)
    )
    tasks_svc.create_task(db, title="tomorrow thing", planned_for=TODAY + timedelta(days=1))

    page = client.get("/next").text
    assert "tomorrow thing" in page
    assert "v1 ships" in page


def test_quick_add_creates_row(client) -> None:
    response = client.post(
        "/ui/tasks/quick-add", data={"title": "captured", "planned_for": TODAY.isoformat()}
    )
    assert response.status_code == 200
    assert "captured" in response.text
    assert "task-row" in response.text


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
    assert "task-editor" in editor and "edit me" in editor

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
