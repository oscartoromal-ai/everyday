---
id: 3
title: "Research: Google Calendar integration options"
labels: [wayfinder:research]
status: closed
assignee: claude (charting session)
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

## Resolution

Full findings: [google-calendar.md](../research/google-calendar.md).
Gist: integration is workable but the auth wall is real for a personal Gmail account (External project; Testing mode expires refresh tokens every 7 days; the standard fix is publishing unverified and clicking through one warning).
Push notifications are off the table for a local app (public HTTPS with CA cert required); syncToken polling every 1-5 minutes is the intended pattern and trivially within quota.
Effort ladder: no sync (zero), ICS secret-address read-only overlay (very low, no OAuth, freshness unverified), API read-only (about a day), full two-way sync (a real sync engine: ID mapping, tombstones, conflicts, recurring-event exceptions).
Recommended frame: start read-only if Google events just need to be visible; commit to two-way only if editing Google events from the app is a hard requirement, preferring an "own-events-only push" middle ground first.
