# Personal Calendar: build-ready spec

A locally-run, Python-backed web app that unifies calendar, to-dos, and projects (with goals, habits, and reviews phased in) as Oscar's control panel for his life and his AI.
This spec is the destination of the wayfinder map in [tracker/map.md](tracker/map.md).
Every section gists a decision made on that map and links the ticket that holds its full reasoning; the tickets are the authority when detail here feels thin.

## 1. Product shape

- Single user (Oscar), single machine (Windows 11), browser UI, no cloud backend.
- The app is the canonical store for personal plan state: projects, tasks, events, blocks.
- Claude is a first-class client: it reads and writes the plan through MCP from day one.
- The work calendar is visible read-only inside the app; the app never writes to it.

## 2. Phasing

Per [v1 phasing](tracker/tickets/002-v1-phasing.md):

- **v1**: the hybrid planner: calendar (events plus chosen task blocks), todos, projects with milestones, manual entry, recurrence for both events and tasks, the work-calendar ICS feed, the MCP planner interface, nudges (three of four triggers), Tailscale phone access.
- **v2**: automatic capture of Claude Code session work (MCP plan tools as the semantic channel, lifecycle hooks as the deterministic trace); enables the fourth nudge trigger.
- **v3**: goals, which projects roll up into.
- **v4**: habits and routines, building on recurrence instance history.
- **v5**: reviews and reflection flows.

Habit mechanics and review flows are deliberately unspecified here; they sharpen as their phase nears (see the map's Not yet specified section).

## 3. Planning interaction model

Per [Planning model](tracker/tickets/001-planning-model.md), decided against interactive prototypes ([asset](tracker/prototypes/planning-model.html)):

- **Hybrid**: to-dos live in lists by default; a task gets a calendar block only when Oscar chooses to give it a slot.
  The calendar shows real events plus deliberately scheduled task blocks, never a forced block per task.
- **Delegated to Claude** is a list section with status chips (queued, running, needs review), not a calendar lane.
- **Missed blocks**: when a scheduled block passes uncompleted, the task falls back to the list wearing a visible "missed" marker until replanned or completed.
  The empty slot stays on today's calendar as a faded ghost outline, gone tomorrow.
  The calendar's future is a plan; its past stays honest.
- **Today** puts the day's list beside a one-day timeline (events, blocks, ghosts), so the day is planned on one screen; dragging a task from the list onto the timeline gives it a block.
- **Weeks** is the planning-ahead surface: six weeks at a glance, as a month-style grid or as one ruled row per day, Oscar's choice and remembered.
  Each day shows its planned tasks, deadlines, milestones, and personal events; the work calendar is condensed to a load figure (meetings and busy hours) rather than listed.
  Dragging a task between days replans it (sets planned_for); an Unplanned tray holds tasks with no do-date, and dragging back to it unplans.
  It supersedes the earlier seven-day next-days list.

## 4. Domain model

Per [Domain model](tracker/tickets/008-domain-model.md). All v1 entities below; goals (v3), habits (v4), and reviews (v5) bolt on without core migration.

### Entities

**Project**: name, status (active / paused / done), notes.
Flat, no nesting.
v3 adds a Goal entity plus a nullable goal reference on Project.

**Milestone**: belongs to one project; name, optional target date, status (open / reached / dropped).
Progress toward a milestone is computable from its attached tasks.

**Task**: title, notes, status, owner (oscar / claude), optional project, optional milestone (only of its own project), optional planned_for (do-date), optional due (deadline).
Notes are the task's free-form description, and sub-tasks live inside it: a line starting with "- " (or "* ") is a sub-task, "- [x] " once done, and every other line is context kept where it was written.
Sub-tasks are text, not rows: they carry no status, owner, or dates of their own, and ticking one rewrites only its own line.
A repeating task's occurrences start with every sub-task open.
planned_for is the day Oscar intends to work it and drives the daily list; due is the obligation and drives urgency.
Backlog tasks have neither.
The Weeks view is driven by planned_for, due, and milestone target dates.

**Block**: belongs to one task; start, end, state (planned / completed / missed).
A task accumulates blocks over time (missed Tuesday, re-slotted Thursday).
The missed marker and the ghost outline both derive from block state; missed is a block-level fact, never a task status.

**Event**: title, start, end, all-day flag, source (local / work), read-only flag, external id.
One entity for own and external events: work-calendar events are rows with source=work, read-only, upserted by external id.
One calendar query, one rendering path; removing the integration deletes rows by source.

**RecurrenceTemplate**: a rule (frequency, interval, weekday selectors) attached to a task template or a local event template.
A daily generator job materializes real instance rows over a rolling horizon of about 8 weeks.
Each occurrence is its own task/event row, individually checkable and editable, carrying its template reference and occurrence date.
v4 habits build streaks by querying instance history; no new recurrence machinery needed.

**SessionActivity** (v2): session id, project, started/ended timestamps.
The deterministic "session happened in project X" trace from the hooks layer.

### Task lifecycle

One shared lifecycle for every task regardless of owner: todo, in_progress, blocked, needs_review, done, cancelled.
The Delegated-to-Claude chips map onto it: queued = todo, running = in_progress, needs review = needs_review.
needs_review is a first-class state, also usable for Oscar's own review-me tasks.
The owner field is the only AI/human distinction; richer provenance (session ids, intake path) stays off the task record.

## 5. Work calendar integration

Per [Decision: work calendar integration mechanism](tracker/tickets/012-work-calendar-decision.md), with the branch settled by [Probe the work tenant's calendar routes](tracker/tickets/014-probe-work-tenant.md):

- **Route: published ICS feed, confirmed live.**
  The tenant offers "Publish a calendar" in Outlook settings; Oscar published at the "Can view titles and locations" level.
  The feed is an anonymous plain GET; verified end-to-end (555 events, titles and locations present, no bodies or attendees).
- The feed URL lives in `local/work-calendar-ics-url.txt`, git-ignored; the app reads it from config, never from the tracker or repo history.
- **Detail stored**: subject, start/end, location only.
  No bodies, attendee lists, or attachments in the personal database, regardless of what the route offers.
- **Polling**: a few times a day, morning-weighted (for example early morning, midday, late afternoon).
  Freshness need is a morning snapshot; intraday changes are seen in Outlook anyway, so publish lag is acceptable and was not measured.
- **Source interface**: the work-calendar source sits behind a small interface so Graph delegated auth (auth code + PKCE via msal, per the [research](tracker/research/outlook-calendar.md)) can swap in later without touching the rest of the app.
  No Graph work and no IT ask in v1.
- Parsing: `icalendar` plus `recurring-ical-events` to expand recurring meetings into concrete occurrences before upserting by external id.

## 6. AI integration

Per [Decision: AI integration architecture](tracker/tickets/007-ai-integration-decision.md), grounded in the [MCP research](tracker/research/mcp-integration.md) and [session-capture research](tracker/research/session-capture.md).

### Planner interface (v1)

- A FastMCP 3.x server mounted inside the FastAPI app, sharing the one database with the REST API and web UI.
- Transport: local streamable HTTP on localhost; no auth locally (see section 8).
- v1 client surface is Claude Code only, via a user-level MCP config.
  Claude Desktop and claude.ai can be added later without server changes (claude.ai needs HTTPS+OAuth, deferred).

### Auto capture (architecture fixed now, ships in v2)

Not a raw session-event feed: what flows in is project-level plan state, so the app can surface what needs working in the next days and each project's backlog.
Two layers, both machine-wide across all projects:

1. **Semantic layer (primary)**: project-plan MCP tools on the app's server, shaped like `upsert_project`, `upsert_tasks`, `update_task_status`.
   A user-level MCP config plus a standing CLAUDE.md instruction has sessions push their project's current state (done / next / blocked) after meaningful work or a planning pass.
2. **Deterministic layer (backup)**: SessionStart/SessionEnd hooks POST a minimal "session happened in project X at time Y" record, keyed by cwd.
   A session that never calls the tools still leaves a trace, feeding the activity-without-plan-update nudge.

Failure handling: hooks spool events to disk when the POST fails; the app ingests the spool backlog at startup (spool and replay).
Hook commands need a short HTTP timeout so a down app never delays sessions.

### Plan truth

- The app database is canonical for cross-project plan state.
- Repo trackers (wayfinder maps and the like) remain per-project working artifacts, not synced or mirrored.

### Manual entry

The web UI writing to the same database; nothing extra to build.

## 7. Nudging and notifications

Per [Decision: AI nudging and notifications](tracker/tickets/013-ai-nudging.md):

- **Triggers (rule-based, no Claude in the loop)**:
  1. Missed blocks: a scheduled block passed uncompleted; nudge to replan.
  2. Activity without plan update (arrives with v2 data): sessions ran in a project but no MCP plan update followed.
  3. Upcoming due dates and milestone target dates within about 3 days, task not done.
  4. Needs-review backlog: tasks sitting in needs_review beyond a threshold.
- Nudges are templated by APScheduler jobs; Claude remains the planner Oscar talks to, not a background voice.
- **Channels**: an in-app nudge center (inbox/banner, each nudge dismissable or actionable) plus phone push via a relay.
  Windows toasts explicitly not used.
- **Cadence**: a morning digest bundles the day's shape, missed blocks, upcoming dues, and review backlog.
  Only genuinely time-sensitive items (due-today slipping, a block just missed) break through during the day.
  Quiet hours are configurable.

## 8. Architecture

Per [Architecture](tracker/tickets/009-architecture.md) and [Decision: security and remote access](tracker/tickets/015-security-remote-access.md).

### Framework and process

- One FastAPI process serving the web UI, the REST API, and the mounted FastMCP server against one database.

### Storage

- SQLite in WAL mode, a single database file.
- SQLAlchemy for models, Alembic for migrations.
- Zero-admin, file-copy restore; sufficient for single-user write load.

### Frontend

- Server-rendered: Jinja templates plus HTMX for pages, lists, and forms; no build step, state server-side.
- Real client JS is limited to two focused vanilla islands, each built well once: the drag-to-slot calendar (week grid and Today's timeline) and drag-to-replan on the Weeks view.

### Background jobs

APScheduler inside the FastAPI process; jobs share app code and database sessions:

- Daily recurrence materialization (8-week rolling horizon).
- Work-calendar ICS poll, a few times a day, morning-weighted.
- Hook-spool ingestion at startup (v2).
- Nudge trigger evaluation and morning digest.
- Daily backup snapshot.

### Deployment and backups

- Auto-starting background service on Windows (NSSM or Task Scheduler at-logon, hidden window); the app is effectively always up, which the hook-spool design assumes.
- The in-app daily backup job uses SQLite's backup API to write dated snapshots into a cloud-synced folder; retain about 30.
- Restore is copying a snapshot back over the database file.

### Security and remote access

- **Tailscale overlay**: the app binds localhost plus the Tailscale interface; Oscar's phone joins the tailnet and gets the full web UI anywhere.
  WireGuard-authenticated, zero public exposure, no port forwarding.
- **No app-level login**: localhost and the tailnet are the trust boundary; MCP and REST stay authless locally.
- **Browser-side hardening**: middleware rejects requests whose Origin/Host headers are not the app's own (closing DNS rebinding and cross-site XHR against localhost); standard CSRF tokens on HTMX form posts.
- **Push relay**: managed ntfy.sh with an unguessable topic name plus access token.
  Task titles transiting ntfy's server is accepted for personal use; self-hosting ntfy on the tailnet is a drop-in swap later.
- **Data at rest**: the SQLite file, hook spool, and backup snapshots are protected by OS user permissions; no additional encryption.

## 9. Out of scope

- Google Calendar integration, in any direction ([decision](tracker/tickets/006-google-sync-decision.md)).
- Writing to or editing the work calendar; work-event bodies and attendees in the personal database.
- Native mobile apps; the phone gets the web UI over Tailscale.
- Claude authoring nudges or acting as a background voice.
- Building the app itself was out of scope for the map that produced this spec; it is exactly what starts from here.

## 10. Standing preferences for the build

- Weigh quality, simplicity, robustness, and long-term sustainability over development cost.
- Be picky about UI quality; pixel-perfection matters to Oscar.
- Fix lint, test failures, and flakiness on sight.
