"""A task's estimate: how long its work is thought to take, set in the task
sheet (its menu, or words such as "45m"), in Today's notes and by Claude,
and its weight in a day's plan (test_calendar_view.py)."""

from datetime import date

import pytest
from fastmcp import Client

from app.dates import duration_label
from app.mcp.server import mcp
from app.services import DomainError
from app.services import history as history_svc
from app.services import tasks as tasks_svc
from app.ui.views import history_ctx

TODAY = date.today()


def test_a_duration_reads_as_it_is_written() -> None:
    assert [duration_label(m) for m in (15, 45, 60, 90, 120, 135)] == [
        "15m", "45m", "1h", "1h 30m", "2h", "2h 15m",
    ]


def test_an_estimate_is_a_minute_to_a_day(db) -> None:
    task = tasks_svc.create_task(db, title="Write the report", estimate_minutes=90)
    assert task.estimate_minutes == 90
    for wrong in (0, -5, 24 * 60 + 1):
        with pytest.raises(DomainError):
            tasks_svc.update_task(db, task.id, estimate_minutes=wrong)
    tasks_svc.update_task(db, task.id, estimate_minutes=None)
    assert task.estimate_minutes is None


def test_the_sheet_writes_and_clears_it(client, db) -> None:
    client.post("/ui/tasks/quick-add", data={"title": "Write the report", "estimate": "45"})
    [task] = tasks_svc.list_tasks(db)
    assert task.estimate_minutes == 45
    row = client.get(f"/ui/tasks/{task.id}/row").text
    assert '<span class="estimate" title="Estimate">45m</span>' in row
    sheet = client.get(f"/ui/tasks/{task.id}/edit").text
    assert 'name="estimate" value="45"' in sheet and ">45m</span>" in sheet

    fields = {"title": "Write the report", "status": "todo", "owner": "oscar"}
    client.post(f"/ui/tasks/{task.id}", data={**fields, "estimate": "120"})
    db.refresh(task)
    assert task.estimate_minutes == 120
    client.post(f"/ui/tasks/{task.id}", data={**fields, "estimate": ""})
    db.refresh(task)
    assert task.estimate_minutes is None


def test_its_history_says_how_it_changed(db) -> None:
    task = tasks_svc.create_task(db, title="Write the report")
    db.commit()
    tasks_svc.update_task(db, task.id, estimate_minutes=90)
    db.commit()
    lines = [line for step in history_ctx(history_svc.changes(db, task.id), TODAY)
             for line in step["lines"]]
    assert "Estimate: none → 1h 30m" in lines


def test_a_task_written_in_todays_notes_keeps_its_estimate(client, db) -> None:
    page = {"blocks": [{
        "kind": "text", "text": "- [ ] Write the report",
        "new": {"0": {"title": "Write the report", "estimate": "30"}},
    }], "version": 0}
    assert client.post(f"/ui/notebook/{TODAY.isoformat()}", json=page).status_code == 200
    [task] = tasks_svc.list_tasks(db)
    assert task.estimate_minutes == 30
    # Its row's controls show it when the notes are read back.
    assert '"estimate": 30' in client.get("/today").text.replace("&#34;", '"')


async def test_claude_sets_an_estimate(app_db) -> None:
    async with Client(mcp) as client:
        [task] = (await client.call_tool(
            "upsert_tasks", {"tasks": [{"title": "Draft the outline", "estimate_minutes": 45}]},
        )).data
        assert task["estimate_minutes"] == 45
        [task] = (await client.call_tool(
            "upsert_tasks", {"tasks": [{"task_id": task["id"], "estimate_minutes": None}]},
        )).data
        assert task["estimate_minutes"] is None

