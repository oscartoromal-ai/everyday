---
id: 15
title: "Decision: security and remote access"
labels: [wayfinder:grilling]
status: open
assignee:
blocked-by: []
parent: map
---

## Question

Two fog patches graduated together by [Architecture: framework, storage, frontend, deployment](009-architecture.md), because the auth model is a function of exposure:

- Security model for a localhost app that AI agents can write to: localhost-only binding, CSRF posture for the server-rendered UI, whether the REST/MCP surfaces need any token even locally, and what protects the database file and spool.
- Reachability from the phone: whether and how Oscar reaches the app remotely (Tailscale-style overlay, LAN, or deferred entirely), and what auth that exposure then requires.

Resolve HITL; the answer becomes the security section of the spec.
