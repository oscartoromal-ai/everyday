---
id: 11
title: "Research: Outlook/Microsoft 365 work calendar read integration"
labels: [wayfinder:research]
status: open
assignee: oscar
blocked-by: []
parent: map
---

## Question

How can a locally-run, single-user Python web app get a read-only view of Oscar's work calendar, which lives in a corporate Microsoft 365 tenant he does not administer?

Cover:

- Microsoft Graph API with delegated auth from a personal/local app: what app registration requires, how tenant admin-consent policies commonly restrict third-party or self-registered apps, device-code vs PKCE flows, token lifetime for an always-running local app.
- The Outlook "publish calendar" ICS link route: whether org policy commonly allows it, available detail levels (full details vs limited vs availability-only), and feed freshness.
- Any other viable routes (EWS, Outlook desktop exports, add-ins) worth considering or explicitly ruling out.
- Python libraries for whichever routes are viable, and their maintenance state.
- A concrete checklist of what Oscar can detect himself versus what he must ask his IT department.

Findings go to `tracker/research/outlook-calendar.md`, linked from this ticket.
Context: surfaced by the [Google sync decision](006-google-sync-decision.md), which ruled Google out and identified the work calendar as the real integration target.
