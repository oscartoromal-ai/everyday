---
id: 10
title: "Assemble the build-ready spec"
labels: [wayfinder:task]
status: closed
assignee: oscar (spec session)
blocked-by: [6, 7, 8, 9, 13, 14, 15]
parent: map
---

## Question

Assemble the destination artifact: a single build-ready spec drawing on every decision this map recorded (planning model, v1 phasing, Google sync, AI integration, domain model, architecture) plus whatever graduated from the fog by then.
This is the one ticket that does rather than decides; it earns its place because it is the destination itself.
Resolved when the spec exists in this repo and Oscar has reviewed it.

## Resolution

Resolved 2026-08-28.
The spec is [SPEC.md](../../SPEC.md) at the repo root, assembled from all fourteen closed decisions on the map.
Each section gists its decision and links the ticket holding the full reasoning; implementation-grade specifics (entity fields, lifecycle states, recurrence horizon, FastMCP mounting, ICS parsing libraries, service and backup setup) are carried inline.
The work-calendar section records the confirmed ICS branch from [Probe the work tenant's calendar routes](014-probe-work-tenant.md), not the earlier conditional.
Two assembly judgment calls, flagged to Oscar in review: nudges (minus the v2-data trigger) and Tailscale phone access placed in v1, and Oscar's standing build preferences restated as section 10.
Oscar reviewed and signed off; the map's destination is reached.
