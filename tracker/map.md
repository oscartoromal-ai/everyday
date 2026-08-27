---
title: "Personal Calendar: way to a build-ready spec"
labels: [wayfinder:map]
status: open
---

# Personal Calendar: way to a build-ready spec

## Destination

A build-ready spec for a locally-run, Python-backed web app that unifies calendar, to-dos, and projects (with goals, habits, and reviews phased in) as Oscar's control panel for his life and his AI.
The spec covers the domain model, the planning interaction model, AI integration (agents reporting work in, Claude planning through it), and architecture, ready to hand to an implementation effort.

## Notes

- Tracker: local markdown. Map is `tracker/map.md`; tickets are `tracker/tickets/NNN-slug.md`. A ticket's frontmatter holds `status` (open/closed), `assignee` (the claim), and `blocked-by` (ticket ids). Frontier = open, unassigned, all blockers closed. Resolutions are appended to the ticket under `## Resolution`.
- Research findings live in `tracker/research/<slug>.md`, linked from their ticket.
- Standing decisions from charting: destination is a spec (build happens after this map); platform is a local web app; backend is Python; AI intake is all three paths (auto from sessions, planner-written, manual).
- Oscar's preferences: weigh quality, simplicity, robustness, and long-term sustainability over development cost. No em dashes. In long markdown, one sentence per line.
- Skills to consult: `impeccable` for the planning-model prototype ticket; `claude-api` and the claude-code-guide agent for AI integration tickets.

## Decisions so far

<!-- one line per closed ticket: [title](tickets/file.md): gist -->

- [Research: Google Calendar integration options](tickets/003-research-google-calendar.md): integration is workable via syncToken polling (push channels are off the table locally); auth needs a one-time publish-unverified Google Cloud project; read-only paths are cheap, two-way sync is a real sync-engine project.
- [Research: how Claude Code sessions can auto-report work](tickets/004-research-session-capture.md): hooks POSTing to localhost are the deterministic backbone, an app-exposed MCP `report_work` tool adds task-level semantics; telemetry and transcript-tailing are weaker options.
- [Research: how Claude acts as planner over the app](tickets/005-research-mcp-integration.md): FastMCP 3.x mounted inside a FastAPI app sharing one database serves all three intake paths; local MCP needs no auth, claude.ai reach can be deferred behind HTTPS+OAuth later.
- [Planning model: how todos and the calendar interact](tickets/001-planning-model.md): hybrid - lists by default, calendar blocks by choice; Claude's work is a status list section, not a calendar lane; missed blocks fall back to the list with a "missed" marker plus a ghost outline on today's calendar.
- [v1 phasing: what ships first vs later](tickets/002-v1-phasing.md): v1 = hybrid planner with recurrence (events and tasks) plus the MCP planner interface; v2 auto session capture; then goals, habits, reviews in that order.
- [Decision: sync with Google Calendar or self-contained](tickets/006-google-sync-decision.md): no Google integration at all; the real target is Oscar's corporate Microsoft 365 work calendar, read-only, now its own research + decision tickets.
- [Research: Outlook/Microsoft 365 work calendar read integration](tickets/011-research-outlook-calendar.md): Graph delegated read likely hits an admin-approval wall (personal-tenant registration does not bypass it); the OWA publish-calendar ICS route is a self-service probe with hours-scale freshness lag; EWS is retiring; an hour of probing settles which routes the tenant allows.
- [Decision: AI integration architecture](tickets/007-ai-integration-decision.md): FastMCP mounted in the FastAPI app (Claude Code only in v1); auto capture is project-plan MCP tools as the semantic channel plus machine-wide lifecycle hooks with disk spool as the deterministic trace; the app DB is canonical for cross-project plan state.
- [Domain model: entities, relationships, and states](tickets/008-domain-model.md): Project, Milestone (v1, Oscar's call), Task (do-date + due-date, one shared lifecycle with owner field), Block as its own entity, one Event entity with source for external events, recurrence as templates materializing real instances; goals/habits/reviews bolt on without core migration.

## Not yet specified

- Habit and routine mechanics (streaks, scheduling, checkoff UX, relation to v1 recurring tasks). Now placed in v4; sharpens as that phase nears and the domain model lands.
- Weekly/monthly review and reflection flow. Now placed in v5; sharpens as that phase nears.
- Security and auth model for a local app that AI agents can write to. Sharpens after the architecture decision (the AI integration side is now decided).
- Reachability from the phone (remote access to the local web app). Sharpens after architecture.

## Out of scope

- Building the app itself. The destination is the spec; implementation is a fresh effort after this map.
- Native mobile apps. The chosen platform is a local web app.
