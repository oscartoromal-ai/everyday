# Google Calendar integration for a local, single-user Python app: research findings

Findings for ticket [Research: Google Calendar integration options](../tickets/003-research-google-calendar.md).

Scope of this report: facts gathered from Google's official documentation and library sources in August 2026, to inform a "sync vs self-contained" decision for a locally-run, Python-backed personal web app on Windows 11 with a personal Gmail account.

## 1. Auth: OAuth 2.0 for a personal/local app

### Setup steps

The required setup is: create a Google Cloud project, enable the Calendar API, configure the OAuth consent screen (now under "Google Auth Platform" branding), create an OAuth client, and download `credentials.json` ([Python quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)).
The quickstart's consent-screen step shows an "Internal" audience, but Internal is only available for projects "associated with a Google Cloud Organization"; a personal Gmail account must use the **External** user type, which makes the app "available to any user with a Google Account" ([Manage app audience](https://support.google.com/cloud/answer/15549945)).

### Client type

For a local app, create a **Desktop app** client and use the loopback redirect (`http://127.0.0.1:port`) ([OAuth for installed apps](https://developers.google.com/identity/protocols/oauth2/native-app)).
For installed apps the client secret is not actually secret: "it is assumed that these apps cannot keep secrets," and `client_secret` is optional in the token exchange (same source).
PKCE with S256 is recommended for the installed-app flow (same source).
A "Web application" client would also work since the app is a local web app, but the Desktop client is the documented path for the quickstart flow and avoids managing exact-match redirect URIs.

### Token storage and refresh in Python

The standard flow is `google-auth-oauthlib`'s `InstalledAppFlow` with `flow.run_local_server(port=0)`, which opens a browser once; credentials are then saved to `token.json`, and on later runs the library silently refreshes when `creds.expired and creds.refresh_token` ([Python quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)).
So after one browser consent, the app runs headless indefinitely, subject to the expiry rules below.

### The critical expiry gotcha: Testing mode = 7-day refresh tokens

An External project with publishing status **Testing** "is issued a refresh token expiring in 7 days" unless it only requests basic profile scopes ([OAuth 2.0 overview, token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)).
The audience doc confirms: "Authorizations by a test user will expire seven days from the time of consent," and the refresh token "will also expire" ([Manage app audience](https://support.google.com/cloud/answer/15549945)).
Testing mode allows "up to 100 test users listed in the OAuth consent screen" (same source).
Consequence: staying in Testing means re-doing the browser consent every week, which is annoying but workable for a personal tool; the fix is to publish the app.

### Publishing without verification

A project becomes "In production" simply by clicking "Publish app" ([Manage app audience](https://support.google.com/cloud/answer/15549945)).
Calendar scopes are sensitive scopes, so an unverified published app shows an "Unverified apps warning message" at consent (same source; note the [verification requirements page](https://support.google.com/cloud/answer/13464321) lists Gmail/Drive/Fit/Photos examples and does not explicitly name Calendar, so the exact classification of each Calendar scope was not confirmed in a fetched source - treat as very likely but not directly quoted).
Unverified apps carry a cap of "100 new users in total, after the app presents the unverified app screen" ([Unverified apps](https://support.google.com/cloud/answer/7454865)), which is irrelevant for a single user.
Google's verification FAQ notes "if your app is experimental or a test build, you don't need to go through verification unless you decide to launch it to the public" (same source).
The commonly used bypass on the warning screen ("Advanced" then "Go to app (unsafe)") is widely reported in the community but was not stated in the fetched Google pages; mark it as uncertain, though the practical pattern (publish to production, click through the warning once, get a non-expiring refresh token) is the standard route for personal self-hosted apps.

### Other expiry triggers to know

There is "a limit of 100 refresh tokens per Google Account per OAuth 2.0 client ID"; exceeding it silently invalidates the oldest token ([token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)).
Refresh tokens also die if unused for six months, if the user revokes access, or (for Gmail scopes) on password change (same source).
For a single-user always-running app, none of these should bite in practice as long as the app is used regularly and does not mint a new token file on every run.

## 2. Sync patterns

### One-way pull (Google to local)

Simplest API-based pattern: `events.list` on the calendars of interest, render locally, never write back.
No conflict handling needed; local app treats Google as the source of truth for Google-originated events.

### One-way push (local to Google)

`events.insert`/`update`/`delete` from the local app; also conflict-free if the local app owns the events it creates (e.g. tag them with a private extended property and only ever touch those).

### Two-way sync

Requires stable ID mapping (local id to Google event id), change detection on both sides, tombstone handling for deletions, and a conflict policy.
The Events resource carries `etag`, `sequence`, and `updated` fields that support optimistic concurrency, and the usual policy for a personal app is last-writer-wins by `updated` timestamp; the specifics of etag/If-Match conditional updates were not re-verified in a fetched page, so mark the exact conditional-request mechanics as to-confirm during implementation.

### Incremental sync with syncToken

The documented pattern ([sync guide](https://developers.google.com/workspace/calendar/api/guides/sync)) is:
Do an initial full `events.list`, persist the `nextSyncToken` from the last page ("the nextSyncToken field is present only on the last page").
On each poll, pass it as `syncToken`; the response contains only changes, including "deleted entries, so clients can remove them from storage."
If many changes occurred you get a `pageToken` and must "paginate through subsequent requests until you find another syncToken on the last page."
On HTTP `410 GONE` (expired token, ACL change), "clear the client storage and perform a new full sync."
Restriction: incremental syncs allow only a restricted parameter set, and every list request must use the same parameters as the initial one, or you get a `400`.
Specifically, `syncToken` cannot be combined with `iCalUID`, `orderBy`, `privateExtendedProperty`, `q`, `sharedExtendedProperty`, `timeMin`, `timeMax`, or `updatedMin` ([events.list reference](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)).
That means a syncToken-based sync covers the whole calendar history, not a time window; windowed queries (`timeMin`/`timeMax`) force full re-fetch each time instead of incremental sync.

### Push notifications (watch channels)

Watch channels POST to a webhook that must be HTTPS with a valid certificate: "the Google Calendar API is able to send notifications to this HTTPS address only if there's a valid SSL certificate installed on your web server," and self-signed or untrusted certificates are explicitly invalid ([push guide](https://developers.google.com/workspace/calendar/api/guides/push)).
For a local Windows app this means exposing a public HTTPS endpoint via a tunnel (ngrok/Cloudflare Tunnel) or a small relay server; a purely local machine behind NAT cannot receive them directly.
Notifications are also content-free: "Notification messages don't contain specific information about updated resources; you must make another API call to see full change details," so push only saves you the polling trigger, not the sync logic (same source).
Channels expire and "there's no automatic way to renew a notification channel"; you must re-issue `watch` calls before expiry (same source).
Verdict for this project: push channels are a poor fit for a local app; polling is the right trigger.

### Polling intervals

Google does not mandate a polling interval; given the per-user quota of 600 requests/min (section 4), polling `events.list` with a `syncToken` every 30-60 seconds is far inside quota, and every 5 minutes is more than enough for a personal calendar.
Incremental responses are tiny when nothing changed, so polling cost is negligible.

### Recurring-event pitfalls

Recurring events are stored as a single parent event with an RRULE in the `recurrence` field, and require timezone-qualified start/end ([recurring events guide](https://developers.google.com/workspace/calendar/api/guides/recurringevents)).
Modified instances ("exceptions") are separate event resources carrying `recurringEventId` and `originalStartTime` (same source).
`singleEvents=true` expands recurrences: "all individual instances appear in the result, but underlying recurring events don't" ([events.list reference](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)).
With `syncToken` plus `singleEvents=true` and `showDeleted=true`, "only single instances of deleted events (but not the underlying recurring events) are returned," a subtle deletion-tracking gotcha (same source).
"This series and following" edits are not atomic: they require trimming the old RRULE with UNTIL/COUNT and creating a new recurring event ([recurring events guide](https://developers.google.com/workspace/calendar/api/guides/recurringevents)).
Google also warns: "Don't modify instances individually when you want to modify the entire recurring event," as mass exceptions degrade performance (same source).
Practical takeaway: if the local app writes recurring events or syncs them two-way, the data model must handle parent+exception pairs; if it only displays, `singleEvents=true` expansion sidesteps most of this.

## 3. Python libraries

### google-api-python-client (official)

Latest release 2.199.0 on 2026-08-20; supports Python 3.10-3.14 ([PyPI](https://pypi.org/project/google-api-python-client/)).
Officially in maintenance mode: "This library is considered complete and is in maintenance mode... we will address critical bugs and security issues but will not add any new features," and "google-api-python-client will continue to be supported" (same source).
For the Calendar API this is fine; the API surface is stable and the recommended Cloud Client Libraries do not cover Workspace APIs like Calendar.
Ergonomics: dynamic `service.events().list(...).execute()` discovery-based calls, dict-shaped payloads, no typing; paired with `google-auth-oauthlib` for the OAuth flow and `google-auth-httplib2` for transport ([quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)).

### gcsa (google-calendar-simple-api)

"A Pythonic object oriented adapter for the official API" built on top of google-api-python-client; MIT license, 684 stars ([GitHub](https://github.com/kuzmoyev/google-calendar-simple-api)).
Actively maintained: latest version 2.7.0 released 2026-07-14, requires Python 3.9+, depends on google-api-python-client and google-auth-oauthlib ([PyPI JSON](https://pypi.org/pypi/gcsa/json)).
Offers typed Event/Calendar objects, recurrence helpers, reminders, attendees, and handles the OAuth token flow for you (GitHub readme).
Caveat: gcsa is oriented at CRUD ergonomics; syncToken-based incremental sync is not an advertised feature, so a real sync engine would likely drop to the underlying client for `events.list(syncToken=...)` (uncertain: not verified against gcsa's full API docs).

### Other options

No other well-maintained general-purpose Calendar API wrapper stands out; the practical choice is the official client (possibly wrapped thinly yourself) or gcsa on top of it.
For the ICS path (section 5), the `icalendar` and `recurring-ical-events` packages are the usual parsers (not individually verified here; mark maintenance state as to-confirm if that path is chosen).

## 4. Quotas and rate limits

From the [official quota page](https://developers.google.com/workspace/calendar/api/guides/quota):
Per-project: 10,000 requests/minute.
Per-user per-project: 600 requests/minute.
Free tier: 1,000,000 requests/day per project at no cost; "All standard use of the Google Calendar API is available at no additional cost," with overage charges only beginning later in 2026 with 90 days' notice.
On quota exhaustion you get 403 or 429; Google prescribes exponential backoff (min of `2^n + random ms` and a 32-64 s max backoff).
For a single-user app polling every minute plus occasional writes, usage will be several orders of magnitude below every limit; quotas are a non-issue for this project.

## 5. Effort/risk profile of the options

### Option A: no sync (self-contained)

Effort: zero integration work; no Google Cloud project, no OAuth, no token lifecycle.
Risk: none technically; the cost is purely product-side (calendar data lives in two places, manual double entry).

### Option B: read-only overlay via ICS secret address (low-effort pull)

Every Google calendar has a "Secret address in iCal format" under Settings, Integrate calendar, of the form `https://calendar.google.com/calendar/ical/CALENDAR_ID/private-TOKEN/basic.ics` ([OneCal guide](https://www.onecal.io/blog/how-to-get-an-ics-url-for-your-calendar), [Google Calendar Help](https://support.google.com/calendar/answer/37648)).
No OAuth, no Cloud project: fetch the URL with `requests`, parse with an ICS library, display.
Caveats: it is read-only by nature; the URL is a bearer secret (anyone with it can read the calendar, and regenerating it invalidates old subscriptions) ([usecarly](https://www.usecarly.com/blog/how-to-get-google-calendar-ics-url/)); freshness of the feed Google serves is not officially documented, and community reports of staleness/caching exist, so treat "how fresh is the ICS" as uncertain and verify empirically (the well-documented 12-24 h throttle is for the opposite direction, Google consuming external ICS feeds - [MoonCal](https://usemooncal.com/en/guides/google-calendar-ics-refresh)).
Recurring events arrive as raw RRULEs that the app must expand itself.
Verdict: viable and genuinely low-effort for display-only, with freshness as the one open question.

### Option C: read-only overlay via the API (moderate)

One-time setup (Cloud project, consent screen, Desktop client, quickstart flow), then `events.list` with `singleEvents=true` over a time window, or a syncToken loop for a proper local cache.
Effort: roughly a day including the OAuth setup ceremony; ongoing risk limited to the token-expiry regime chosen (weekly re-consent in Testing, or publish-unverified once).
No conflict handling, and recurring events can be delegated to server-side expansion.

### Option D: full two-way sync (high)

All of Option C plus: write path, ID mapping, tombstones, conflict policy, the syncToken parameter restrictions (no time-window incremental sync), the deleted-recurring-instance gotcha, and the exception/RRULE model for recurring edits.
This is the classic underestimated project; the sync engine, not the API calls, is the work.
Risk concentrates in edge cases (recurring exceptions, 410 full-resync correctness, offline edits on both sides).

### Middle-ground note

A useful intermediate is Option C plus "push only what the app creates" (tag app-created events with a private extended property and never touch foreign events), which gets most two-way value at a fraction of the conflict surface.

## Bottom line for the decision

- The auth wall is real but one-time: a personal Gmail app must be an External project, and Testing mode kills refresh tokens every 7 days ([source](https://developers.google.com/identity/protocols/oauth2#expiration)); the standard personal-app workaround is to publish to production unverified and accept the one-time warning screen, after which tokens persist.
- Push notifications are effectively off the table for a local Windows app (public HTTPS endpoint with a CA-signed certificate required, plus manual channel renewal, and notifications carry no payload anyway - [source](https://developers.google.com/workspace/calendar/api/guides/push)); syncToken polling every 1-5 minutes is the intended pattern and is trivially within the 600 req/min/user free quota ([source](https://developers.google.com/workspace/calendar/api/guides/quota)).
- Read-only integration is cheap two ways: the ICS secret address needs no auth at all (freshness unverified), and the API read path is about a day of setup with mature, maintained libraries (google-api-python-client 2.199.0, gcsa 2.7.0, both released mid-2026).
- Full two-way sync is a different category of effort: the API supports it well (syncToken, tombstones, etags), but the cost lives in the sync engine - ID mapping, conflicts, the syncToken parameter restrictions, and the recurring-event exception model ([source](https://developers.google.com/workspace/calendar/api/guides/sync)).
- Recommended decision frame: if Google events only need to be visible, start with ICS (Option B) and upgrade to API read-only (Option C) if freshness disappoints; commit to two-way sync (Option D) only if editing Google events from the app is a hard requirement, and prefer the "own-events-only push" middle ground first.
