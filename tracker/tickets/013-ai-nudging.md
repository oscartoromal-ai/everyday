---
id: 13
title: "Decision: AI nudging and notifications"
labels: [wayfinder:grilling]
status: closed
assignee: claude (nudging session)
blocked-by: [9]
parent: map
---

## Question

How does the planner proactively reach Oscar?

Decide what triggers nudges (missed calendar blocks, stale projects, sessions with activity but no plan update, upcoming deadlines) and through which channels (web app UI, Windows notifications, phone).

Graduated from the fog by [Decision: AI integration architecture](007-ai-integration-decision.md), which fixed the mechanisms nudges build on (app DB canonical, lifecycle hooks, MCP planner tools).
Channel choice depends on deployment and reachability, so this waits on [Architecture: framework, storage, frontend, deployment](009-architecture.md).

## Resolution

Decided with Oscar on 2026-08-27.

### Triggers (all four)

- Missed blocks: a scheduled block passed uncompleted; nudge to replan the fallen-back task.
- Activity without plan update: SessionActivity shows sessions in a project but no MCP plan update followed; nudge to re-plan that project.
- Upcoming due dates and milestone target dates within a lookahead window (about 3 days) with the task not done.
- Needs-review backlog: tasks sitting in needs_review beyond a threshold.

Trigger availability follows its data: the first, third, and fourth work from v1 data; activity-without-plan-update arrives with v2 session capture.

### Authorship

- Deterministic rules only: APScheduler jobs evaluate triggers and emit templated nudges.
- No Claude in the nudge loop; Claude remains the planner Oscar talks to, not a background voice.

### Channels

- In-app nudge center: a nudge inbox/banner in the web UI, each nudge dismissable or actionable.
- Phone push via a relay (ntfy or Pushover): works without exposing the app; nudge text (task titles) transits the relay, and self-hosting ntfy stays open as a later hardening step.
- Windows toasts: explicitly not chosen.
- Note for [Decision: security and remote access](015-security-remote-access.md): the push relay is an outbound-only third-party dependency carrying task titles; weigh relay choice/self-hosting there if it matters.

### Cadence

- Morning digest bundles everything: the day's shape, missed blocks, upcoming dues, review backlog.
- Only genuinely time-sensitive items (due-today slipping, a block just missed) break through during the day.
- Configurable quiet hours.
