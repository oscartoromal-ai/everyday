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


def test_dev_server_app_runs_no_scheduler(app_db, monkeypatch) -> None:
    """`uvicorn app.main:app` is the dev server, which may share the desktop
    app's database; only the app itself (app/desktop, serve.py) may run the jobs."""
    import app.jobs.scheduler as scheduler
    from app.main import app

    def refuse():  # noqa: ANN202
        raise AssertionError("the dev server started the scheduler")

    monkeypatch.setattr(scheduler, "create_scheduler", refuse)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
