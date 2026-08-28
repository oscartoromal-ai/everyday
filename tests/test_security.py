import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import create_app


@pytest.fixture
def client(db) -> TestClient:
    app = create_app()

    def override() -> object:
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_unknown_host_rejected(client) -> None:
    response = client.get("/", headers={"Host": "evil.example.com"})
    assert response.status_code == 421


def test_cross_origin_unsafe_request_rejected(client) -> None:
    client.get("/")
    client.headers["X-CSRF"] = client.cookies.get("csrf", "")
    response = client.post(
        "/ui/tasks/quick-add",
        data={"title": "x"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


def test_unsafe_request_without_csrf_rejected(client) -> None:
    client.get("/")  # cookie present, but no header echoed
    response = client.post("/ui/tasks/quick-add", data={"title": "x"})
    assert response.status_code == 403


def test_csrf_double_submit_allows_request(client) -> None:
    client.get("/")
    token = client.cookies.get("csrf", "")
    response = client.post(
        "/ui/tasks/quick-add", data={"title": "guarded"}, headers={"X-CSRF": token}
    )
    assert response.status_code == 200
    assert "guarded" in response.text


def test_same_origin_allowed(client) -> None:
    client.get("/")
    token = client.cookies.get("csrf", "")
    response = client.post(
        "/ui/tasks/quick-add",
        data={"title": "same origin"},
        headers={"X-CSRF": token, "Origin": "http://testserver"},
    )
    assert response.status_code == 200


def test_mcp_exempt_from_csrf(app_db) -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            },
            headers={"accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200
