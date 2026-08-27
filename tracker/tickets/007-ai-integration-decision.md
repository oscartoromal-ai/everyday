---
id: 7
title: "Decision: AI integration architecture"
labels: [wayfinder:grilling]
status: closed
assignee: claude (ai-integration session)
blocked-by: [4, 5]
parent: map
---

## Question

Pick the concrete architecture for AI in and out of the system, covering all three intake paths Oscar wants:

- Auto capture: which mechanism (hooks, telemetry, transcripts, self-reporting MCP tool) feeds AI agent work into the app, and what an "AI task" record looks like.
- Planner interface: how Claude reads and writes the app (MCP server, REST plus skill, CLI) and from which surfaces.
- Manual entry stays possible as the fallback.

Decide HITL using the findings from [Research: how Claude Code sessions can auto-report work](004-research-session-capture.md) and [Research: how Claude acts as planner over the app](005-research-mcp-integration.md).

## Resolution

Decided with Oscar on 2026-08-27.

### Planner interface (v1)

- A FastMCP 3.x server mounted inside the FastAPI app, sharing one database with the REST API and web UI, as the research recommended.
- Local streamable HTTP on localhost; no auth needed locally.
- v1 client surface is Claude Code only, via a user-level MCP config.
- Claude Desktop and claude.ai can be added later without server changes (claude.ai needs HTTPS+OAuth, deferred).

### Auto capture (architecture decided now, ships in v2)

Oscar reframed the intent: he does not want a raw session-event feed.
Planning happens inside each project (wayfinder-style), and what should flow into the app is project-level plan state, so the app can surface what needs working in the next days and what sits in each project's backlog.

Two layers, both machine-wide across all projects:

1. Semantic layer (primary): project-plan MCP tools on the app's server, shaped like `upsert_project`, `upsert_tasks`, `update_task_status`, not a diary-style `report_work`.
   A user-level MCP config plus a standing CLAUDE.md instruction has sessions push their project's current state (done / next / blocked) after meaningful work or a planning pass.
2. Deterministic layer (backup): SessionStart/SessionEnd hooks POST a minimal "session happened in project X at time Y" record, keyed by cwd.
   A session that never calls the tools still leaves a trace, and the app can show "activity but no plan update" as a nudge to re-plan.

Failure handling: hooks spool events to disk when the POST fails and the app ingests the backlog on startup (spool + replay).

### Plan truth

- The app database is canonical for cross-project plan state (projects, tasks, timelines, what's next).
- Repo trackers (wayfinder maps and the like) remain per-project working artifacts; they are not synced or mirrored.

### AI task record (seed for the domain-model ticket)

- Oscar picked the minimal shape: title, status, project, plus a free-text notes/summary field.
- Provenance (session id, source path) and scheduling (due/target date) fields were deliberately not picked here.
- Tension flagged for [Domain model](008-domain-model.md): surfacing "what needs work in the next days" needs some date or priority signal on tasks; resolve there.

### Manual entry

- Stays as the web UI writing to the same database; nothing extra to build for it.
