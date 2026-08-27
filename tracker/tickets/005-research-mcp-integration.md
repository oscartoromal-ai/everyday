---
id: 5
title: "Research: how Claude acts as planner over the app"
labels: [wayfinder:research]
status: open
assignee:
blocked-by: []
parent: map
---

## Question

How should Claude read and write the app so it can plan Oscar's week, schedule tasks, and manage entries on his behalf?
Surface the integration options for a Python-backed local app and the facts needed to choose:

- An MCP server exposing app operations: Python SDK state of the art (FastMCP or official SDK), transport options (stdio vs HTTP), and which Claude surfaces can connect (Claude Code, Claude Desktop, claude.ai).
- A plain REST API that Claude Code calls via Bash/skills.
- A CLI the agent invokes.
- Auth story for each when the app is local.
- Which option best serves all three intake paths Oscar wants: auto session reporting, planner-written entries, manual entry.
