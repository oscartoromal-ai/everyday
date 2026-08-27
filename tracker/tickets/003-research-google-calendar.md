---
id: 3
title: "Research: Google Calendar integration options"
labels: [wayfinder:research]
status: open
assignee:
blocked-by: []
parent: map
---

## Question

What would it actually take for a locally-run Python web app to integrate with Google Calendar (his personal account)?
Surface the facts the sync-vs-self-contained decision waits on:

- Auth model for a personal/local app (OAuth flow, credential storage, token refresh, Google Cloud project requirements, verification hurdles for personal use).
- Sync patterns: one-way pull, one-way push, two-way; incremental sync via sync tokens; push notifications/webhooks vs polling; conflict handling.
- Mature Python libraries and their maintenance state.
- Quotas, rate limits, and known pain points.
- Effort and risk profile of each option, including "no sync" and "read-only overlay" middle grounds.
