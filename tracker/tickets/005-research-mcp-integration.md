---
id: 5
title: "Research: how Claude acts as planner over the app"
labels: [wayfinder:research]
status: closed
assignee: claude (charting session)
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

## Resolution

Full findings: [mcp-integration.md](../research/mcp-integration.md).
Gist: an MCP server is the future-proof planner interface; the minimal stack is FastMCP 3.x mounted inside a FastAPI app on one port, sharing the same database as the web UI and REST API, so all three intake paths hit one store.
Local HTTP MCP needs no auth (OS-level trust); claude.ai web/mobile would additionally require a public HTTPS endpoint with OAuth, which can be deferred.
REST-plus-Bash and CLI are workable fallbacks but suffer permission prompts, no schema discoverability, and Claude Code-only reach.
SQLite is fine single-machine; use transactions and optimistic locking for concurrent writers.
