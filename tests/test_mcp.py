from datetime import date, datetime, time

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp.server import mcp

TODAY = date.today()
# Midday, so the event stays on today's agenda whatever the time the suite runs.
NOON = datetime.combine(TODAY, time(12, 0))

EXPECTED_TOOLS = {
    "list_projects",
    "upsert_project",
    "list_tasks",
    "upsert_tasks",
    "update_task_status",
    "get_agenda",
    "add_event",
    "get_notebook",
    "get_task_history",
    "get_health_profile",
    "get_garmin",
}


async def test_planner_surface(app_db) -> None:
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
    assert tools >= EXPECTED_TOOLS
    assert "schedule_block" not in tools  # a task takes no time on the calendar


async def test_upsert_project_matches_by_name(app_db) -> None:
    async with Client(mcp) as client:
        created = (await client.call_tool("upsert_project", {"name": "App"})).data
        updated = (
            await client.call_tool(
                "upsert_project", {"name": "App", "notes": "the planner app"}
            )
        ).data
        assert updated["id"] == created["id"]
        assert updated["notes"] == "the planner app"
        listed = (await client.call_tool("list_projects", {})).data
        assert [p["name"] for p in listed] == ["App"]


async def test_task_flow_through_tools(app_db) -> None:
    async with Client(mcp) as client:
        project = (await client.call_tool("upsert_project", {"name": "App"})).data
        [task] = (
            await client.call_tool(
                "upsert_tasks",
                {
                    "tasks": [
                        {
                            "title": "wire the MCP server",
                            "owner": "claude",
                            "project_id": project["id"],
                            "planned_for": str(TODAY),
                        }
                    ]
                },
            )
        ).data
        assert task["owner"] == "claude"

        updated = (
            await client.call_tool(
                "update_task_status", {"task_id": task["id"], "status": "in_progress"}
            )
        ).data
        assert updated["status"] == "in_progress"

        one_pm = NOON.replace(hour=13)
        await client.call_tool(
            "add_event", {"title": "pairing", "start": NOON.isoformat(), "end": one_pm.isoformat()}
        )

        agenda = (await client.call_tool("get_agenda", {"start": str(TODAY)})).data
        assert [e["title"] for e in agenda["events"]] == ["pairing"]
        assert "blocks" not in agenda
        assert [t["id"] for t in agenda["days"][str(TODAY)]["planned"]] == [task["id"]]


async def test_domain_errors_surface_as_tool_errors(app_db) -> None:
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="title"):
            await client.call_tool("upsert_tasks", {"tasks": [{"notes": "no title"}]})


async def test_claude_reads_the_notebook_and_a_tasks_history(app_db) -> None:
    from app.services import habits as habits_svc
    from app.services import notebook as notebook_svc
    from app.services import stays as stays_svc
    from app.services import tasks as tasks_svc

    with app_db() as db:
        task = tasks_svc.create_task(db, title="Call the dentist", written_on=TODAY)
        notebook_svc.save_page(
            db,
            TODAY,
            [
                {"kind": "text", "text": "Slow morning."},
                {"kind": "task", "id": task.id},
                {"kind": "reflection", "text": "Calmer."},
            ],
            version=0,
        )
        stays_svc.set_item(db, TODAY, "place", value="Lisbon", done=True)
        stretch = habits_svc.create(db, "stretch")
        habits_svc.set_done(db, stretch, TODAY, True)
        habits_svc.set_note(db, stretch, TODAY, "Ten minutes.")
        db.commit()
        task_id = task.id

    async with Client(mcp) as client:
        await client.call_tool("update_task_status", {"task_id": task_id, "status": "done"})
        pages = (await client.call_tool("get_notebook", {})).data
        # The page as written, then where he stays and the habits ticked that day.
        [text, written, reflection, stay, habit] = pages[TODAY.isoformat()]
        assert text == {"kind": "text", "text": "Slow morning."}
        assert written["task"]["title"] == "Call the dentist"
        assert written["task"]["status"] == "done"
        assert reflection == {"kind": "reflection", "text": "Calmer."}
        assert habit == {"kind": "habit", "habit": "stretch", "done": True, "note": "Ten minutes."}
        assert stay == {"kind": "stay", "items": [
            {"name": "place", "value": "Lisbon", "done": True},
            {"name": "accommodation", "value": "", "done": False},
        ]}

        # How consistent he is: each habit, day by day.
        [row] = (await client.call_tool("get_habits", {"days": 2})).data
        assert (row["slug"], row["days"]) == ("stretch", "")
        assert [c["state"] for c in row["checks"]] == [None, "done"]
        today = {"day": TODAY.isoformat(), "state": "done", "note": "Ten minutes."}
        assert row["checks"][1] == today

        agenda = (await client.call_tool("get_agenda", {})).data
        assert agenda["days"][TODAY.isoformat()]["notebook"][1]["title"] == "Call the dentist"

        history = (await client.call_tool("get_task_history", {"task_id": task_id})).data
        # Claude's own change is named as Claude's.
        assert history[0]["actor"] == "claude"
        assert history[0]["fields"] == [{"field": "status", "from": "todo", "to": "done"}]
        assert history[-1]["change"] == "created"


async def test_health_profile_is_context_for_claude(app_db) -> None:
    from app.services import health as health_svc

    with app_db() as db:
        health_svc.update_profile(db, height_cm=180, allergies="peanuts")
        health_svc.log_weight(db, TODAY, 80)
        db.commit()
    async with Client(mcp) as client:
        me = (await client.call_tool("get_health_profile", {})).data
    got = (me["height_cm"], me["weight_kg"], me["bmi"], me["allergies"])
    assert got == (180, 80, 24.7, "peanuts")
    assert me["weights"] == [{"day": TODAY.isoformat(), "weight_kg": 80}]
    assert me["energy_kcal"] is None and me["sex"] is None
