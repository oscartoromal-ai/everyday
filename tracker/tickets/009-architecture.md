---
id: 9
title: "Architecture: framework, storage, frontend, deployment"
labels: [wayfinder:grilling]
status: closed
assignee: claude (architecture session)
blocked-by: [7, 8, 12]
parent: map
---

## Question

Fix the technical architecture for the spec: Python web framework, data storage, frontend approach, and how the app runs locally on Oscar's Windows machine (startup, persistence, backups).
Constraints already decided: Python backend, local web app, prefer quality, simplicity, robustness, and long-term sustainability over development cost.
Blocked on the work calendar decision (a calendar-pull job changes storage and background-job needs; was the Google sync decision before that was resolved as no-Google), the AI integration decision (MCP server vs REST changes the API surface), and the domain model.

## Resolution

Decided with Oscar on 2026-08-27.

### Framework

- FastAPI, as already fixed by [Decision: AI integration architecture](007-ai-integration-decision.md): one process serving the web UI, the REST API, and the mounted FastMCP server against one database.

### Storage

- SQLite in WAL mode, a single database file.
- SQLAlchemy for models, Alembic for migrations.
- Zero-admin, file-copy restore; judged sufficient for single-user write load by the MCP research and confirmed here.

### Frontend

- Server-rendered: Jinja templates plus HTMX for pages, lists, and forms; no build step, state server-side.
- The drag-to-slot day/week calendar is a focused JS island (vanilla or Alpine), the one piece of real client JS, built well once.

### Background jobs

- APScheduler inside the FastAPI process; jobs share app code and database sessions.
- Jobs: daily recurrence materialization (8-week rolling horizon per [Domain model](008-domain-model.md)), work-calendar poll a few times a day morning-weighted (per [Decision: work calendar integration mechanism](012-work-calendar-decision.md)), hook-spool ingestion at startup, and future nudge checks.

### Deployment and backups

- Auto-starting background service on Windows (NSSM or Task Scheduler at-logon, hidden window), bound to localhost; the app is effectively always up, which the hooks-spool design assumed.
- In-app daily backup job uses SQLite's backup API to write dated snapshots into a cloud-synced folder; retain about 30.
- Restore is copying a snapshot back over the database file.
