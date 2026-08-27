---
id: 12
title: "Decision: work calendar integration mechanism"
labels: [wayfinder:grilling]
status: open
assignee:
blocked-by: [11]
parent: map
---

## Question

Pick the mechanism for showing Oscar's corporate Microsoft 365 work events read-only in the app, using the findings from [Research: Outlook/Microsoft 365 work calendar read integration](011-research-outlook-calendar.md).

Decide HITL:

- Which route (Graph API, published ICS link, or other), given what the tenant actually allows.
- How much work-event detail is stored in the personal app's database (full details vs busy/free only), since employer data-sensitivity constraints are unknown.
- Freshness expectations and the polling approach.
- What, if anything, Oscar needs to request from IT first (which may spawn a task ticket).

Scoped by the [Google sync decision](006-google-sync-decision.md): read-only visibility only; no pushing personal items to the work calendar, no editing work events from the app.
