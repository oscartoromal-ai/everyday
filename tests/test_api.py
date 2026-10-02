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
    workstream = client.post(
        f"/api/projects/{project['id']}/workstreams", json={"name": "v1"}
    ).json()

    created = client.post(
        "/api/tasks",
        json={"title": "build it", "project_id": project["id"], "workstream_id": workstream["id"]},
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


def test_calendar_endpoint_lists_the_events_in_its_window(client) -> None:
    soon = client.post("/api/events", json={
        "title": "dentist", "start": (NOW + timedelta(hours=1)).isoformat(),
        "end": (NOW + timedelta(hours=2)).isoformat(),
    }).json()
    client.post("/api/events", json={
        "title": "next week", "start": (NOW + timedelta(days=9)).isoformat(),
        "end": (NOW + timedelta(days=9, hours=1)).isoformat(),
    })
    params = {"start": NOW.isoformat(), "end": (NOW + timedelta(hours=12)).isoformat()}
    cal = client.get("/api/calendar", params=params).json()
    assert [e["id"] for e in cal["events"]] == [soon["id"]]
    assert client.post("/api/blocks", json={}).status_code in (404, 405)
