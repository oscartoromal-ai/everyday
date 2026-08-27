---
id: 6
title: "Decision: sync with Google Calendar or self-contained"
labels: [wayfinder:grilling]
status: closed
assignee: oscar
blocked-by: [3]
parent: map
---

## Question

Should the app sync with Oscar's Google Calendar (and if so, one-way or two-way), or be the self-contained single source of truth?
Decide HITL using the findings from [Research: Google Calendar integration options](003-research-google-calendar.md), weighing robustness and long-term sustainability over build cost.

## Resolution

Decided 2026-08-27, HITL.

**No Google Calendar integration.**
The app is self-contained with respect to Google: no OAuth ceremony, no sync engine, no ICS overlay.
The [Google research findings](../research/google-calendar.md) remain as reference but no option from them is taken.

Grilling surfaced that the calendar that actually matters is Oscar's **work calendar on corporate Microsoft 365 (Outlook)**, which the charting had not seen.
The scoped goal there is read-only: see work events in the app so personal planning happens around them.
Employer/tenant constraints are unknown and need checking before a mechanism can be chosen.

Follow-up tickets created:

- [Research: Outlook/Microsoft 365 work calendar read integration](011-research-outlook-calendar.md) (AFK).
- [Decision: work calendar integration mechanism](012-work-calendar-decision.md) (HITL, blocked on the research).

The architecture ticket now depends on the work-calendar decision instead of this one.
