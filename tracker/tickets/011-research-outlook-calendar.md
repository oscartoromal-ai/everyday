---
id: 11
title: "Research: Outlook/Microsoft 365 work calendar read integration"
labels: [wayfinder:research]
status: closed
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

## Resolution

Resolved 2026-08-27, AFK.
Full findings: [Outlook/Microsoft 365 work calendar read integration](../research/outlook-calendar.md).

Key facts:

- Graph API delegated `Calendars.Read` needs no admin consent by itself, but two tenant gates apply: the "Users can register applications" switch and the consent policy; Microsoft's 2025 "Secure by Default" change makes a "Need admin approval" wall likely for third-party apps.
- Registering the app in a personal Entra tenant does not bypass this: a multi-tenant app's consent is evaluated in the work tenant.
- If Graph is used, auth code + PKCE with a localhost redirect beats device code flow (admins are told to block device code via Conditional Access); public-client refresh tokens roll for 90 days per use, so a persisted MSAL token cache keeps an always-running app alive, barring Conditional Access interrupts.
- The OWA "publish calendar" ICS route exists with three detail tiers (busy-only, titles+locations, full details) and is gated by the Exchange sharing policy; the option simply being present in settings is a perfect self-service probe. Freshness is undocumented, community-reported at hours to 24h+ lag, so it needs empirical testing.
- EWS is ruled out (disablement starts October 2026, retirement April 2027); OST parsing ruled out; sharing to a personal account and Power Automate are policy-dependent fallbacks.
- Python libraries all healthy: msal 1.38.0, msgraph-sdk 1.61.0, icalendar 7.3.0, recurring-ical-events 3.8.2, O365 2.1.9.
- About an hour of self-service probing (checklist in the report) settles which routes the tenant actually allows before any IT ask.
- Report suggests isolating the calendar source behind a small interface so ICS can ship first and Graph can swap in later; the choice itself is [the work calendar decision](012-work-calendar-decision.md).
