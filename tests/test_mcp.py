from datetime import date, datetime, time

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp.server import mcp

TODAY = date.today()
# Midday, so the block stays on today's agenda whatever the time the suite runs.
NOON = datetime.combine(TODAY, time(12, 0))

EXPECTED_TOOLS = {
    "list_projects",
    "upsert_project",
    "list_tasks",
    "upsert_tasks",
    "update_task_status",
    "get_agenda",
    "schedule_block",
    "add_event",
}


async def test_planner_surface(app_db) -> None:
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
    assert tools >= EXPECTED_TOOLS


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

        block = (
            await client.call_tool(
                "schedule_block",
                {
                    "task_id": task["id"],
                    "start": NOON.isoformat(),
                    "end": NOON.replace(hour=13).isoformat(),
                },
            )
        ).data
        assert block["task_id"] == task["id"]

        agenda = (await client.call_tool("get_agenda", {"start": str(TODAY)})).data
        assert [b["task_title"] for b in agenda["blocks"]] == ["wire the MCP server"]
        assert [t["id"] for t in agenda["days"][str(TODAY)]["planned"]] == [task["id"]]


async def test_domain_errors_surface_as_tool_errors(app_db) -> None:
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="title"):
            await client.call_tool("upsert_tasks", {"tasks": [{"notes": "no title"}]})
