"""The app's use, counted by route and day (app/usage.py)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import usage
from app.models import RouteUse
from app.services import tasks as tasks_svc


@pytest.fixture
def recorder(monkeypatch) -> usage.UsageRecorder:
    """The app's recorder, fresh for the test."""
    fresh = usage.UsageRecorder()
    monkeypatch.setattr(usage, "recorder", fresh)
    return fresh


def _flushed(recorder: usage.UsageRecorder, db) -> dict[str, RouteUse]:  # noqa: ANN001
    recorder.flush(db)
    return {row.route: row for row in db.scalars(select(RouteUse))}


def test_requests_are_counted_by_the_route_that_answered(client, db, recorder) -> None:
    task = tasks_svc.create_task(db, title="Water the plants")
    db.commit()
    assert client.get(f"/ui/tasks/{task.id}/edit").status_code == 200
    assert client.get(f"/ui/tasks/{task.id}/edit").status_code == 200

    used = _flushed(recorder, db)
    row = used["GET /ui/tasks/{task_id}/edit"]
    assert (row.day, row.requests, row.failures) == (date.today(), 2, 0)
    assert row.total_ms >= row.slowest_ms >= 0
    # Never the address asked for: which task was looked at is not kept.
    assert not [route for route in used if str(task.id) in route]


def test_static_files_and_unknown_addresses_are_not_counted(client, db, recorder) -> None:
    client.get("/static/app.css")
    client.get("/no/such/page")

    assert not [r for r in _flushed(recorder, db) if "static" in r or "no/such" in r]


def test_a_mount_is_counted_by_its_path(recorder) -> None:
    # As the MCP server is mounted at /mcp.
    async def mounted(scope, receive, send) -> None:  # noqa: ANN001
        await PlainTextResponse("ok")(scope, receive, send)

    app = FastAPI()
    app.mount("/mcp", mounted)
    app.add_middleware(usage.UsageMiddleware)
    TestClient(app).post("/mcp/tools", json={})

    assert list(recorder._counts) == [(date.today(), "POST /mcp")]


def test_server_errors_and_errors_raised_count_as_failures(recorder) -> None:
    app = FastAPI()

    @app.get("/down")
    def down() -> None:
        raise HTTPException(503)

    @app.get("/missing")
    def missing() -> None:
        raise HTTPException(404)

    @app.get("/broken")
    def broken() -> None:
        raise RuntimeError("broken")

    app.add_middleware(usage.UsageMiddleware)
    client = TestClient(app, raise_server_exceptions=False)
    for path in ("/down", "/missing", "/broken"):
        client.get(path)

    counts = recorder._counts
    assert counts[(date.today(), "GET /down")].failures == 1
    assert counts[(date.today(), "GET /missing")].failures == 0
    assert counts[(date.today(), "GET /broken")].failures == 1


def test_flushes_add_up_day_by_day(db) -> None:
    recorder = usage.UsageRecorder()
    monday, tuesday = date(2026, 10, 5), date(2026, 10, 6)
    recorder.record("GET /today", 40, False, monday)
    recorder.record("GET /today", 90, True, monday)
    assert recorder.flush(db) == 1
    recorder.record("GET /today", 60, False, monday)
    recorder.record("GET /today", 10, False, tuesday)
    assert recorder.flush(db) == 2
    assert recorder.flush(db) == 0

    rows = {row.day: row for row in db.scalars(select(RouteUse))}
    assert (rows[monday].requests, rows[monday].failures) == (3, 1)
    assert (rows[monday].total_ms, rows[monday].slowest_ms) == (190, 90)
    assert (rows[tuesday].requests, rows[tuesday].slowest_ms) == (1, 10)


def test_counts_a_flush_could_not_write_wait_for_the_next(db, monkeypatch) -> None:
    recorder = usage.UsageRecorder()
    recorder.record("GET /today", 40, False)

    def refuse(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("database is locked")

    with monkeypatch.context() as m:
        m.setattr(db, "execute", refuse)
        with pytest.raises(RuntimeError):
            recorder.flush(db)
    recorder.record("GET /today", 20, False)
    recorder.flush(db)

    row = db.scalars(select(RouteUse)).one()
    assert (row.requests, row.total_ms) == (2, 60)
