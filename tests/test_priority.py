"""A task's priority: how much it matters against the others (urgent, high,
medium, low, or none). Set in the task sheet (its menu, or "p1" to "p4" as
the title is written), in Today's notes, on a project's Gantt and by Claude;
shown wherever tasks are, and the first tie-break after a list's dates.
The browser's side is test_priority_browser.py."""

from datetime import date, datetime, timedelta

import pytest
from fastmcp import Client

from app.mcp.server import mcp
from app.models import Task, TaskPriority, TaskStatus
from app.services import DomainError
from app.services import gantt as gantt_svc
from app.services import history as history_svc
from app.services import projects as projects_svc
from app.services import search as search_svc
from app.services import tasks as tasks_svc
from app.ui.day_sheet_view import day_sheet_ctx
from app.ui.gantt_view import gantt_ctx
from app.ui.views import history_ctx, projects_page_ctx

TODAY = date.today()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("urgent", TaskPriority.urgent), ("High", TaskPriority.high),
        (" medium ", TaskPriority.medium),
        ("med", TaskPriority.medium), ("l", TaskPriority.low), ("u", TaskPriority.urgent),
        ("1", TaskPriority.urgent), ("4", TaskPriority.low), ("p2", TaskPriority.high),
        ("P3", TaskPriority.medium), ("", None), ("none", None), ("No priority", None), ("0", None),
    ],
)
def test_a_priority_reads_as_it_is_written(text, expected) -> None:
    assert tasks_svc.parse_priority(text) == expected


@pytest.mark.parametrize("text", ["5", "p5", "top", "very high"])
def test_what_is_not_a_priority_is_refused(text) -> None:
    with pytest.raises(DomainError, match="Not a priority"):
        tasks_svc.parse_priority(text)


def test_a_task_has_none_until_given_one(db) -> None:
    task = tasks_svc.create_task(db, title="Book the venue")
    assert task.priority is None
    tasks_svc.update_task(db, task.id, priority=TaskPriority.urgent)
    db.commit()
    db.expire_all()
    assert db.get(Task, task.id).priority == TaskPriority.urgent
    tasks_svc.update_task(db, task.id, priority=None)
    assert task.priority is None


def test_the_sheet_writes_shows_and_clears_it(client, db) -> None:
    client.post("/ui/tasks/quick-add", data={"title": "Book the venue", "priority": "high"})
    [task] = tasks_svc.list_tasks(db)
    assert task.priority == TaskPriority.high
    row = client.get(f"/ui/tasks/{task.id}/row").text
    assert 'title="Priority: High"' in row and 'data-priority="high"' in row
    assert "<span>High</span>" in row
    sheet = client.get(f"/ui/tasks/{task.id}/edit").text
    assert 'name="priority" value="high"' in sheet
    assert 'aria-label="Priority: High"' in sheet

    fields = {"title": "Book the venue", "status": "todo", "owner": "oscar"}
    client.post(f"/ui/tasks/{task.id}", data={**fields, "priority": "urgent"})
    db.refresh(task)
    assert task.priority == TaskPriority.urgent
    # Its page saves it as it is written.
    client.post(f"/ui/tasks/{task.id}/page", data={**fields, "priority": "low"})
    db.refresh(task)
    assert task.priority == TaskPriority.low
    client.post(f"/ui/tasks/{task.id}", data={**fields, "priority": ""})
    db.refresh(task)
    assert task.priority is None
    assert "Priority:" not in client.get(f"/ui/tasks/{task.id}/row").text


def test_a_priority_the_sheet_cannot_read_is_refused(client, db) -> None:
    response = client.post("/ui/tasks/quick-add", data={"title": "Book", "priority": "top"})
    assert response.status_code == 422
    assert tasks_svc.list_tasks(db) == []


def test_its_history_says_how_it_changed(db) -> None:
    task = tasks_svc.create_task(db, title="Book the venue")
    db.commit()
    tasks_svc.update_task(db, task.id, priority=TaskPriority.high)
    db.commit()
    tasks_svc.update_task(db, task.id, priority=None)
    db.commit()
    lines = [line for step in history_ctx(history_svc.changes(db, task.id), TODAY)
             for line in step["lines"]]
    assert "Priority: none → High" in lines
    assert "Priority: High → none" in lines


def test_a_task_written_in_todays_notes_keeps_its_priority(client, db) -> None:
    page = {"blocks": [{
        "kind": "text", "text": "- [ ] Book the venue",
        "new": {"0": {"title": "Book the venue", "priority": "urgent"}},
    }], "version": 0}
    assert client.post(f"/ui/notebook/{TODAY.isoformat()}", json=page).status_code == 200
    [task] = tasks_svc.list_tasks(db)
    assert task.priority == TaskPriority.urgent
    # Its row's controls show it when the notes are read back.
    assert '"priority": "urgent"' in client.get("/today").text.replace("&#34;", '"')


def test_lists_put_the_most_pressing_first_among_the_same_dates(db) -> None:
    tasks_svc.create_task(db, title="Low", planned_for=TODAY, priority=TaskPriority.low)
    tasks_svc.create_task(db, title="None", planned_for=TODAY)
    tasks_svc.create_task(db, title="Urgent", planned_for=TODAY, priority=TaskPriority.urgent)
    tasks_svc.create_task(
        db, title="Later", planned_for=TODAY + timedelta(days=1), priority=TaskPriority.urgent
    )
    ctx = projects_page_ctx(db, datetime.now())
    # Dates first: a later day stays later, however pressing.
    assert [r["task"].title for r in ctx["loose_rows"]] == ["Urgent", "Low", "None", "Later"]
    assert [t.title for t in tasks_svc.for_day(db, TODAY, TODAY)] == ["Urgent", "Low", "None"]
    sheet = day_sheet_ctx(db, TODAY, TODAY, days=1)
    assert [t["title"] for t in sheet["rows"][0]["tasks"]] == ["Urgent", "Low", "None"]
    assert sheet["rows"][0]["tasks"][0]["priority_label"] == "Urgent"


def test_calendars_sheet_shows_its_bars(client, db) -> None:
    tasks_svc.create_task(db, title="Book the venue", planned_for=TODAY,
                          priority=TaskPriority.medium)
    db.commit()
    html = client.get(f"/calendar/sheet?start={TODAY.isoformat()}").text
    assert 'class="ds-priority" role="img" title="Priority: Medium"' in html


def test_the_gantt_shows_writes_and_undoes_it(db) -> None:
    project = projects_svc.create_project(db, name="Launch")
    task = tasks_svc.create_task(db, title="Book the venue", project_id=project.id)
    [row] = [r for g in gantt_ctx(db, project, TODAY)["groups"] for r in g["rows"]
             if r["kind"] == "task"]
    assert row["priority"] == "" and "priority" not in row["describe"]

    gantt_svc.apply(db, project, [{"op": "task", "id": task.id, "priority": "h"}], TODAY)
    assert task.priority == TaskPriority.high
    [row] = [r for g in gantt_ctx(db, project, TODAY)["groups"] for r in g["rows"]
             if r["kind"] == "task"]
    assert row["priority_label"] == "High"
    assert row["describe"] == "Book the venue, high priority"

    # Undo puts every field back as it was, its priority among them.
    was = {"title": "Book the venue", "status": "todo", "priority": "", "starts_on": "", "due": ""}
    gantt_svc.apply(db, project, [{"op": "task", "id": task.id, "set": was}], TODAY)
    assert task.priority is None
    with pytest.raises(DomainError, match="Not a priority"):
        gantt_svc.apply(db, project, [{"op": "task", "id": task.id, "priority": "soon"}], TODAY)


def test_pasted_lines_write_their_priority(db) -> None:
    project = projects_svc.create_project(db, name="Launch")
    [made] = gantt_svc.apply(db, project, [{
        "op": "create", "workstream_id": "", "title": "Book the venue", "priority": "urgent",
        "start": "", "length": "", "due": "",
    }], TODAY)
    assert db.get(Task, made).priority == TaskPriority.urgent


def test_the_gantt_page_has_a_priority_column(client, db) -> None:
    project = projects_svc.create_project(db, name="Launch")
    tasks_svc.create_task(db, title="Book the venue", project_id=project.id,
                          priority=TaskPriority.urgent)
    db.commit()
    html = client.get(f"/projects/{project.id}/gantt").text
    assert '<span class="gantt-cell gantt-priority" role="columnheader">Priority</span>' in html
    assert 'data-edit="priority"' in html and 'data-priority="urgent"' in html
    assert '<span class="gantt-priority-word">Urgent</span>' in html
    # The time's columns start after the six frozen ones.
    assert 'class="gantt-cell gantt-wk' in html and 'data-col="6"' in html


def test_search_names_it(db) -> None:
    tasks_svc.create_task(db, title="Book the venue", due=TODAY, priority=TaskPriority.high)
    tasks_svc.create_task(db, title="Book the band")
    found = search_svc.search(db, "book", datetime.now())["tasks"]
    metas = {t["title"]: t["meta"] for t in found}
    assert metas["Book the venue"] == "high · due today"
    assert metas["Book the band"] == ""
    # A done task says only that.
    task = tasks_svc.list_tasks(db)[0]
    tasks_svc.set_status(db, task.id, TaskStatus.done)
    assert search_svc.search(db, "venue", datetime.now())["tasks"][0]["meta"] == "done"


async def test_claude_sets_a_priority(app_db) -> None:
    async with Client(mcp) as client:
        [task] = (await client.call_tool(
            "upsert_tasks", {"tasks": [{"title": "Draft the outline", "priority": "high"}]},
        )).data
        assert task["priority"] == "high"
        [listed] = (await client.call_tool("list_tasks", {})).data
        assert listed["priority"] == "high"
        [task] = (await client.call_tool(
            "upsert_tasks", {"tasks": [{"task_id": task["id"], "priority": None}]},
        )).data
        assert task["priority"] is None


def test_the_api_reads_and_writes_it(client) -> None:
    made = client.post("/api/tasks", json={"title": "Book", "priority": "low"}).json()
    assert made["priority"] == "low"
    patched = client.patch(f"/api/tasks/{made['id']}", json={"priority": "urgent"}).json()
    assert patched["priority"] == "urgent"
    assert client.post("/api/tasks", json={"title": "x", "priority": "top"}).status_code == 422
