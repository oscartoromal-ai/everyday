---
id: 7
title: "Decision: AI integration architecture"
labels: [wayfinder:grilling]
status: open
assignee:
blocked-by: [4, 5]
parent: map
---

## Question

Pick the concrete architecture for AI in and out of the system, covering all three intake paths Oscar wants:

- Auto capture: which mechanism (hooks, telemetry, transcripts, self-reporting MCP tool) feeds AI agent work into the app, and what an "AI task" record looks like.
- Planner interface: how Claude reads and writes the app (MCP server, REST plus skill, CLI) and from which surfaces.
- Manual entry stays possible as the fallback.

Decide HITL using the findings from [Research: how Claude Code sessions can auto-report work](004-research-session-capture.md) and [Research: how Claude acts as planner over the app](005-research-mcp-integration.md).
