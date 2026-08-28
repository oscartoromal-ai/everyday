---
id: 14
title: "Probe the work tenant's calendar routes"
labels: [wayfinder:task]
status: closed
assignee: oscar (probe session)
blocked-by: []
parent: map
---

## Question

HITL task for Oscar: run the self-service probe (about an hour, at the work account, no IT contact) that picks the branch of [Decision: work calendar integration mechanism](012-work-calendar-decision.md).
Full detection detail lives in section 5a of the [research report](../research/outlook-calendar.md).

Checklist, in priority order (stop as soon as the ICS route is confirmed):

1. Outlook on the web > Settings > Calendar > Shared calendars: is "Publish a calendar" present, and which detail levels does it offer?
   Present at titles+locations or better = ICS route confirmed; the remaining steps become optional.
2. If present: publish, fetch the ICS URL (plain GET), edit a test event, and note roughly how long the feed takes to reflect it.
3. If absent: at entra.microsoft.com with the work account, try App registrations > New registration (does self-registration work?).
4. If absent: in Graph Explorer, consent to `Calendars.Read` and run `GET /me/calendarView`; note whether an "Approval required" dialog with a justification box appears (that means a sanctioned admin-consent request path exists).

Resolution records: which branch is live (ICS / Graph / both blocked), the detail levels offered, the measured ICS lag if applicable, and the ICS URL location (store it in the app's config, not in this tracker).
If both routes are blocked, a follow-up decision ticket spawns instead of a branch.

## Resolution

Probe run 2026-08-28. **Branch live: ICS.** Step 1 succeeded, so steps 3-4 (Entra self-registration, Graph Explorer consent) were not run.

- "Publish a calendar" is present in Outlook settings for the work tenant; Oscar published the calendar.
- Detail level chosen: "Can view titles and locations".
- Feed verified from this machine: anonymous plain GET, HTTP 200, ~450 KB.
  555 VEVENTs spanning to Feb 2027, all with SUMMARY, 541 with LOCATION, 40 RRULEs.
  No DESCRIPTION or ATTENDEE lines, matching the chosen detail level and exactly the titles+times+location scope decision 012 stores.
- ICS URL location: `local/work-calendar-ics-url.txt` in this repo, git-ignored via the new `.gitignore` (`local/`). Not recorded in this tracker.
- Freshness lag: not measured, deliberately skipped. [Decision: work calendar integration mechanism](012-work-calendar-decision.md) already ruled lag moot under morning-snapshot freshness; measure later during implementation if it ever matters.

Consequence for the map: the ICS-first branch of decision 012 is confirmed, no Graph fallback work and no IT ask needed for v1. [Assemble the build-ready spec](010-write-spec.md) is now fully unblocked.
