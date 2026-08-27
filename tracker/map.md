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

## Not yet specified

- Habit and routine mechanics (streaks, scheduling, checkoff UX). Sharpens once v1 phasing decides where habits land.
- Weekly/monthly review and reflection flow. Sharpens once v1 phasing decides where reviews land.
- AI nudging and notifications (how the planner reaches Oscar proactively). Sharpens after the AI integration decision.
- Security and auth model for a local app that AI agents can write to. Sharpens after the AI integration and architecture decisions.
- Reachability from the phone (remote access to the local web app). Sharpens after architecture.

## Out of scope

- Building the app itself. The destination is the spec; implementation is a fresh effort after this map.
- Native mobile apps. The chosen platform is a local web app.
