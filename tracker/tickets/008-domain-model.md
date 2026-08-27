---
id: 8
title: "Domain model: entities, relationships, and states"
labels: [wayfinder:grilling]
status: open
assignee:
blocked-by: [1, 2]
parent: map
---

## Question

Define the domain model the spec will carry: goals, projects, tasks, events, habits, and reviews; how they nest and reference each other; task states and lifecycle; recurrence; how AI-owned work is distinguished from Oscar-owned work.
Blocked on the planning model (whether tasks become calendar blocks changes the task/event relationship) and on v1 phasing (which entities exist in v1 at all).
Resolve HITL with grilling and domain modeling.
Per the [v1 phasing resolution](002-v1-phasing.md): model v1 entities fully (tasks, projects, events, blocks, recurrence for events and tasks, delegated-AI status); goals, habits, and reviews (v3-v5) need only enough future-proofing that adding them later will not force a migration of the core.
