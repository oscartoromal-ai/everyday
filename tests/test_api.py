from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import create_app

NOW = datetime.now().replace(microsecond=0)


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


def test_task_crud_roundtrip(client) -> None:
    project = client.post("/api/projects", json={"name": "App"}).json()
    milestone = client.post(
        f"/api/projects/{project['id']}/milestones", json={"name": "v1"}
    ).json()

    created = client.post(
        "/api/tasks",
        json={"title": "build it", "project_id": project["id"], "milestone_id": milestone["id"]},
    )
    assert created.status_code == 201
    task = created.json()

    patched = client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    assert patched.json()["status"] == "in_progress"

    listed = client.get("/api/tasks", params={"project_id": project["id"]}).json()
    assert [t["id"] for t in listed] == [task["id"]]

    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get(f"/api/tasks/{task['id']}").status_code == 422


def test_domain_error_maps_to_422(client) -> None:
    response = client.post("/api/tasks", json={"title": "   "})
    assert response.status_code == 422
    assert "title" in response.json()["detail"].lower()


def test_calendar_endpoint_classifies_ghosts(client, db) -> None:
    from app.services import blocks as blocks_svc

    # The past block sits at the very start of today and the missed-block pass
    # runs just after it, so the test holds at any wall-clock time (a block a
    # few hours back is yesterday's between midnight and 2am, and never a ghost).
    midnight = datetime.combine(NOW.date(), datetime.min.time())
    task = client.post("/api/tasks", json={"title": "deep work"}).json()
    past = client.post(
        "/api/blocks",
        json={
            "task_id": task["id"],
            "start": midnight.isoformat(),
            "end": (midnight + timedelta(minutes=1)).isoformat(),
        },
    ).json()
    future = client.post(
        "/api/blocks",
        json={
            "task_id": task["id"],
            "start": (NOW + timedelta(hours=1)).isoformat(),
            "end": (NOW + timedelta(hours=2)).isoformat(),
        },
    ).json()
    params = {
        "start": midnight.isoformat(),
        "end": (NOW + timedelta(hours=12)).isoformat(),
    }

    cal = client.get("/api/calendar", params=params).json()
    assert {b["id"] for b in cal["blocks"]} == {past["id"], future["id"]}
    assert cal["ghosts"] == []

    # After the periodic job runs, today's missed block becomes a ghost outline.
    blocks_svc.mark_missed_blocks(db, midnight + timedelta(minutes=2))
    cal = client.get("/api/calendar", params=params).json()
    assert [b["id"] for b in cal["blocks"]] == [future["id"]]
    assert [g["id"] for g in cal["ghosts"]] == [past["id"]]
    assert cal["ghosts"][0]["task_title"] == "deep work"
