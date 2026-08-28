from fastapi.testclient import TestClient

from app.main import create_app


def test_index_serves(app_db) -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "Personal Calendar" in response.text


def test_mcp_endpoint_mounted(app_db) -> None:
    with TestClient(create_app()) as client:  # context manager runs the lifespan
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
        assert "personal-calendar" in response.text
