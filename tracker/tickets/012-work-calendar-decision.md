---
id: 12
title: "Decision: work calendar integration mechanism"
labels: [wayfinder:grilling]
status: closed
assignee: claude (work-calendar session)
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

## Resolution

Decided with Oscar on 2026-08-27.
The tenant has not been probed yet, so the decision is a conditional strategy whose branch is picked by a probe task, not by a further decision.

### Route: ICS first, Graph as fallback

- Preferred route: the OWA published-calendar ICS feed.
  Oscar's freshness need is a morning snapshot (intraday changes are seen in Outlook anyway), so the hours-scale publish lag stops mattering, and ICS wins on simplicity and sustainability: an anonymous GET plus icalendar parsing, no auth code, no token lifecycle.
- Fallback branch: Microsoft Graph delegated `Calendars.Read` via auth code + PKCE with a persisted MSAL token cache, taken only if the publish option is absent from OWA settings and the probe shows self-registration and consent get through.
- If the probe finds both routes blocked: that becomes its own small decision with the probe facts in hand; Oscar chose not to pre-commit to an IT ask.

### Detail stored

- Titles + times + location only: subject, start/end, location.
- No bodies, attendee lists, or attachments in the personal database, regardless of what the route offers.
- Rows land in the unified Event entity from [Domain model](008-domain-model.md): source=work, read-only, upserted by external id.

### Polling

- A few times a day, morning-weighted (for example early morning, midday, late afternoon).
- The work-calendar source sits behind a small interface, as the research recommended, so ICS can ship first and Graph can swap in without touching the rest of the app.

### IT ask

- Nothing requested from IT now; the self-service probe comes first, as [Probe the work tenant's calendar routes](014-probe-work-tenant.md).
- That task ticket blocks [Assemble the build-ready spec](010-write-spec.md) so the spec records the actual branch, not the conditional.
