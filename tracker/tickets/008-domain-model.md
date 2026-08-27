---
id: 8
title: "Domain model: entities, relationships, and states"
labels: [wayfinder:grilling]
status: closed
assignee: claude (domain-model session)
blocked-by: [1, 2]
parent: map
---

## Question

Define the domain model the spec will carry: goals, projects, tasks, events, habits, and reviews; how they nest and reference each other; task states and lifecycle; recurrence; how AI-owned work is distinguished from Oscar-owned work.
Blocked on the planning model (whether tasks become calendar blocks changes the task/event relationship) and on v1 phasing (which entities exist in v1 at all).
Resolve HITL with grilling and domain modeling.
Per the [v1 phasing resolution](002-v1-phasing.md): model v1 entities fully (tasks, projects, events, blocks, recurrence for events and tasks, delegated-AI status); goals, habits, and reviews (v3-v5) need only enough future-proofing that adding them later will not force a migration of the core.

## Resolution

Decided with Oscar on 2026-08-27.
One deviation from the recommended defaults: Oscar chose to ship milestones in v1 rather than defer that structure to v3.

### Entities

**Project**: name, status (active / paused / done), notes.
Flat, no nesting.
v3 goals arrive as a new entity plus a nullable goal reference on Project; no migration of the core.

**Milestone**: belongs to one project; name, optional target date, status (open / reached / dropped).
Tasks may attach to at most one milestone, and only one of their own project.
Milestone target dates feed the urgency/next-days view; progress toward a milestone is computable from its attached tasks.

**Task**: title, notes, status, owner (oscar / claude), optional project, optional milestone, optional planned_for (do-date), optional due (deadline).
planned_for is the day Oscar intends to work it and drives the daily list; due is the obligation and drives urgency.
Backlog tasks have neither.
This resolves the date-signal tension flagged by [Decision: AI integration architecture](007-ai-integration-decision.md): the next-days view is driven by planned_for, due, and milestone target dates.

**Block**: belongs to one task; start, end, state (planned / completed / missed).
A task accumulates blocks over time (missed Tuesday, re-slotted Thursday).
The "missed" marker on a listed task and the faded ghost outline on today's calendar both derive from block state; missed is a block-level fact, never a task status.

**Event**: title, start, end, all-day flag, source (local / work), read-only flag, external id.
One entity for own and external events: external work-calendar events (mechanism per [Decision: work calendar integration mechanism](012-work-calendar-decision.md)) are rows with source=work, read-only, upserted by external id.
One calendar query, one rendering path; removing the integration deletes rows by source.

**RecurrenceTemplate**: a rule (frequency, interval, weekday selectors) attached to a task template or a local event template.
The app materializes real instance rows over a rolling horizon (about 8 weeks ahead) via a small generator job.
Each occurrence is its own task/event row, individually checkable and editable, carrying its template reference and occurrence date.
v4 habits build streaks by querying instance history; no new recurrence machinery needed.

**SessionActivity** (v2, from the hooks layer of [Decision: AI integration architecture](007-ai-integration-decision.md)): session id, project, started/ended timestamps.
The deterministic "session happened in project X" trace; the app surfaces "activity but no plan update" from it.

### Task lifecycle

One shared lifecycle for every task regardless of owner: todo, in_progress, blocked, needs_review, done, cancelled.
The "Delegated to Claude" chips from [Planning model](001-planning-model.md) map onto it: queued = todo, running = in_progress, needs review = needs_review.
needs_review is a first-class state, also usable for Oscar's own review-me tasks.
The owner field (oscar / claude) is what distinguishes AI-owned work; per ticket 7, richer provenance (session ids, intake path) stays off the task record.

### Future-proofing (v3-v5)

- Goals (v3): new entity; Project gains a nullable goal reference.
- Habits (v4): build on recurrence templates and instance history (streaks, checkoff); may extend recurring tasks, forcing no core change.
- Reviews (v5): standalone flows reading existing history; no core hooks needed now.
