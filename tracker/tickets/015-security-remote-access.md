---
id: 15
title: "Decision: security and remote access"
labels: [wayfinder:grilling]
status: closed
assignee: claude (security session)
blocked-by: []
parent: map
---

## Question

Two fog patches graduated together by [Architecture: framework, storage, frontend, deployment](009-architecture.md), because the auth model is a function of exposure:

- Security model for a localhost app that AI agents can write to: localhost-only binding, CSRF posture for the server-rendered UI, whether the REST/MCP surfaces need any token even locally, and what protects the database file and spool.
- Reachability from the phone: whether and how Oscar reaches the app remotely (Tailscale-style overlay, LAN, or deferred entirely), and what auth that exposure then requires.

Resolve HITL; the answer becomes the security section of the spec.

## Resolution

Decided with Oscar on 2026-08-27.

### Remote access

- Tailscale overlay: the app binds localhost plus the Tailscale interface; Oscar's phone joins the tailnet and gets the full web UI anywhere.
- WireGuard-authenticated, zero public exposure, no port forwarding.

### App-level auth

- Network boundary only: no login.
- Localhost and the tailnet are the trust boundary; both already authenticate the device and user.
- MCP and REST stay authless locally, consistent with [Decision: AI integration architecture](007-ai-integration-decision.md).

### Browser-side hardening

- Middleware rejects requests whose Origin/Host headers are not the app's own, closing DNS-rebinding and cross-site XHR against localhost.
- Standard CSRF tokens on HTMX form posts.

### Push relay

- Managed ntfy.sh with an unguessable topic name plus access token.
- Task titles transiting ntfy's server is accepted for personal use; self-hosting ntfy on the tailnet remains a drop-in swap later (same protocol).

### Data at rest

- The SQLite file, hook spool, and backup snapshots are protected by OS user permissions; no additional encryption mandated.
- Backup snapshots land in Oscar's own cloud-synced folder per [Architecture](009-architecture.md).
