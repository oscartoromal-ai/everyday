---
id: 2
title: "v1 phasing: what ships first vs later"
labels: [wayfinder:grilling]
status: closed
assignee: claude (v1-phasing session)
blocked-by: []
parent: map
---

## Question

Oscar wants calendar, todos, projects, goals and milestones, habits and routines, and reviews and reflection.
That is too much for one v1.
Which capabilities land in v1, and in what order do the rest phase in?
The answer becomes the phasing section of the spec and decides how much of the fog (habits mechanics, review flow) ever graduates into tickets on this map.

## Resolution

Phasing decided with Oscar:

- **v1**: the hybrid planner from [Planning model](001-planning-model.md) - calendar (events plus chosen task blocks), todos, projects, manual entry - **plus the MCP planner interface**, so Claude can read and write the plan from day one.
  The "Delegated to Claude" list starts manual- and planner-fed.
  Recurrence ships in v1 for **both events and tasks** (weekly gym, bins every Tuesday); habits proper still come later.
- **v2**: automatic capture of Claude Code session work (hooks, report_work tool - per the [session capture research](../research/session-capture.md)).
- **v3**: goals and milestones that projects roll up into.
  Amendment (2026-08-27): milestones moved into v1 as dated checkpoints inside projects, per Oscar's call in [Domain model](008-domain-model.md); v3 keeps goals.
- **v4**: habits and routines (may absorb or extend recurring tasks).
- **v5**: reviews and reflection flows.

Google Calendar sync's phase placement is decided in [Decision: sync with Google Calendar or self-contained](006-google-sync-decision.md), not here.
