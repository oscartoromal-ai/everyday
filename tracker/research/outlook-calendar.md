# Outlook/Microsoft 365 work calendar read integration

Findings for ticket [Research: Outlook/Microsoft 365 work calendar read integration](../tickets/011-research-outlook-calendar.md).

Scope: a locally-run, single-user Python web app on Windows 11 needs a READ-ONLY view of Oscar's work calendar in a corporate Microsoft 365 tenant that Oscar does not administer.
Tenant policies are unknown, so every route below is framed as "works if the tenant allows X", with a detection checklist at the end.
All web sources below were fetched on 2026-08-27.

## 1. Microsoft Graph API with delegated auth

### 1.1 App registration by an ordinary user

By default, member users in a Microsoft Entra tenant can register applications.
[Default user permissions](https://learn.microsoft.com/en-us/entra/fundamentals/users-default-permissions) states: "Member users can register applications, manage their own profile photo and mobile phone number, change their own password, and invite B2B guests."
The same page documents the admin off-switch: "Setting this option to No prevents users from creating application registrations. You can then grant the ability back to specific individuals, by adding them to the application developer role."
So whether Oscar can self-register an app in the work tenant is purely a tenant setting.
How commonly the setting is disabled is not documented by Microsoft; security-hardening guides widely recommend disabling it (for example [Trend Micro's cloud posture rule](https://www.trendmicro.com/trendaivisiononecloudriskmanagement/knowledge-base/azure/ActiveDirectory/users-can-register-applications.html)), so in a locked-down tenant expect it to be off (uncertain, to confirm empirically).

Registration itself only needs the Entra portal (App registrations > New registration), a name, and for a local app a public-client redirect URI such as `http://localhost` - no paid subscription is required.
That mechanical detail is from the [app registration quickstart](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) (not fetched in full here, to confirm during implementation).

### 1.2 User consent vs admin consent policies

Even a registered (or third-party) app only gets data after consent.
[Configure how users consent to applications](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-user-consent) describes the baseline: "By default, all users are allowed to consent to applications for permissions that don't require administrator consent."
The [user and admin consent overview](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview) lists the three built-in postures an admin can choose:

- Disable user consent entirely ("Users can't grant permissions to applications").
- "Users can consent to applications from verified publishers or your organization, but only for permissions you select", limited to permissions classified as low impact.
- "Users can consent to all applications" (any permission that doesn't require admin consent).

Important 2025 change: per Microsoft 365 message center notice [MC1097272](https://mc.merill.net/message/MC1097272) (June 2025, "Secure by Default" changes rolled out mid-July through August 2025), Microsoft's managed default consent settings were tightened so that non-privileged users can no longer consent to third-party apps requesting access to files and sites by default; see also [this third-party summary](https://www.appgovscore.com/blog/microsoft-disables-user-consent-by-default-are-you-ready-for-mc1097272).
Whether that managed policy also blocks user consent for calendar scopes (as opposed to Files/Sites scopes) is not confirmed in the sources fetched here - to confirm by simply trying it.
Practical consequence: in many corporate tenants a consent attempt will end in a "Need admin approval" dialog even for a low-privilege scope.

When a user is not allowed to consent, the [admin consent request workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview#admin-consent-workflow) is the sanctioned escape hatch: "The admin consent workflow gives users a way to request admin consent for applications when they aren't allowed to consent themselves. When the admin consent workflow is enabled, users are presented with an 'Approval required' window for requesting admin approval for access to the application."
The workflow itself must be enabled by an admin; if it is not enabled, the user is simply blocked with no request button (implied by the docs, to confirm in Oscar's tenant).

### 1.3 Registering the app in a personal tenant does NOT bypass work-tenant consent

Oscar could create a free personal Entra tenant, register a multi-tenant app there, and sign in with the work account.
This does not bypass anything.
Per [Apps and service principals in Microsoft Entra ID](https://learn.microsoft.com/en-us/entra/identity-platform/app-objects-and-service-principals): "A service principal must be created in each tenant where the application is used ... A multitenant application also has a service principal created in each tenant where a user from that tenant has consented to its use."
Consent for the work account is evaluated inside the work tenant, against the work tenant's consent policies, and creates a service principal there that IT can see and revoke.
To the work tenant, Oscar's personal-tenant app is exactly a third-party app, which is the category the 2025 secure-by-default changes restrict hardest.
So the personal-tenant route changes nothing about permissions; its only benefit is that Oscar controls the app registration object itself.

### 1.4 Permission scopes

The needed delegated scope is `Calendars.Read` ("Allows the app to read events in user calendars").
Per the community mirror of the Graph permissions reference, [graphpermissions.merill.net/permission/Calendars.Read](https://graphpermissions.merill.net/permission/Calendars.Read), the delegated `Calendars.Read` permission has AdminConsentRequired: No (the application-permission variant does require admin consent).
The authoritative list is the [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference).
Caveat: "admin consent not required" only means the scope is eligible for user consent; the tenant's consent policy (section 1.2) can still forbid user consent for it.
`offline_access` should be requested too, so a refresh token is issued (see the token table in the [device code flow doc](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code): "refresh_token ... Issued if the original scope parameter included offline_access").
`Calendars.Read.Shared` exists for delegate/shared calendars but is not needed for reading one's own calendar (to confirm against the final feature set).

### 1.5 Auth flow for a local app: auth code + PKCE vs device code

Both flows work for a public client with no secret, and MSAL for Python implements both.

Device code flow is simple (print a code, user signs in elsewhere) and is documented in [OAuth 2.0 device authorization grant](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code); it returns access, refresh, and ID tokens like other flows.
However, it is exactly the flow Microsoft tells admins to block.
[Block authentication flows with Conditional Access policy](https://learn.microsoft.com/en-us/entra/identity/conditional-access/policy-block-authentication-flows) says: "We recommend organizations get as close as possible to a unilateral block on device code flow. ... Only allow device code flow in well documented and secured use cases, like legacy tooling that can't be updated."
A security-conscious tenant therefore quite plausibly blocks device code flow via the Conditional Access "Authentication flows" condition.

Authorization code with PKCE using a `http://localhost` redirect is the better default for this app: the machine has a browser, and the Conditional Access authentication-flows condition documented above targets only device code flow and authentication transfer, not the ordinary browser-based auth code flow.
Recommendation grounded in the above: implement auth code + PKCE first, keep device code as a fallback.

### 1.6 Tokens, silent refresh, and an always-running local app

Per [Refresh tokens in the Microsoft identity platform](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens), the default refresh token lifetime is "90 days for all other scenarios" (the 24-hour figures apply to SPAs and email-OTP flows, not a native/public client), and "Refresh tokens replace themselves with a fresh token upon every use."
So a local app that polls at least once every 90 days and persists its token cache can normally run indefinitely without re-prompting.
Access tokens themselves are short-lived (the device-code doc's example shows `expires_in: 3599`, about one hour), so the app must silently redeem the refresh token regularly; MSAL's `acquire_token_silent` plus a serialized token cache handles this (MSAL Python behavior per its own docs, not fetched here - to confirm in implementation).

Gotchas that can break "runs forever":

- Revocation: the [refresh token revocation table](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens#token-revocation) shows admin password resets and explicit "revoke all refresh tokens" kill public-client tokens; password expiry alone does not.
- Conditional Access sign-in frequency: per [Conditional Access session lifetime](https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-session-lifetime), "The Microsoft Entra ID default configuration for user sign-in frequency is a rolling window of 90 days", but admins can shorten it (for example to 1 day or 1 hour), after which token refresh fails until the user reauthenticates interactively.
  Note the same doc says enforcement on non-interactive sign-ins is deferred "until the next interactive sign-in" on confidential clients; how aggressively it hits a background public client is tenant-specific (to confirm empirically).
- The app must therefore treat `interaction_required` errors as a normal state: surface a "please sign in again" banner rather than crashing.

## 2. The Outlook "publish calendar" ICS/HTML link route

The feature exists for Microsoft 365 work accounts in new Outlook and Outlook on the web.
Per [Share an Outlook calendar as view-only with others (Microsoft Support)](https://support.microsoft.com/en-us/office/share-an-outlook-calendar-as-view-only-with-others-353ed2c1-3ec5-449d-8c73-6931a0adab88), publishing lives under Calendar settings > Shared calendars > "Publish a calendar", and produces two links: an HTML link "if you want recipients to view the calendar in a browser" and an ICS link "if you want them to subscribe to your calendar".
The ICS URL is anonymous (no auth), which makes it trivially consumable by a local Python app with plain HTTP GET.

Detail levels: the publish dropdown offers the same tiers as sharing, commonly labeled "Can view when I'm busy", "Can view titles and locations", and "Can view all details" (UI labels reported in [a Microsoft Q&A thread](https://learn.microsoft.com/en-us/answers/questions/4695885/how-do-i-publish-my-calendar-to-show-more-than-can), to confirm in Oscar's own UI).
On the admin side these map to the sharing-policy access levels in [Sharing policies in Exchange Online](https://learn.microsoft.com/en-us/exchange/sharing/sharing-policies/sharing-policies): "Free/busy information with time only", "Free/busy information with time, subject, and location", and "Free/busy information, including time, subject, location, and title".

Admins can disable this route.
The support KB [Publish Calendar option is missing from Calendar](https://learn.microsoft.com/en-us/troubleshoot/exchange/outlook-on-the-web-issues/publish-calendar-option-missing-from-calendar-settings) confirms: "This problem can occur if the Anonymous domain isn't set in the sharing policy that's assigned to the user."
So the presence or absence of the "Publish a calendar" control in OWA settings is itself a reliable, self-service policy probe.
The sharing-policies doc also notes: "An admin can also disable a user's sharing policy to prevent external access to calendars."

Feed freshness: Microsoft does not document a server-side refresh SLA for published feeds.
Community reporting from [CalendarBridge](https://calendarbridge.com/blog/how-to-share-an-outlook-calendar/) says published calendars are "always view-only and usually slower to refresh", that "Outlook checks every 3 hours, but in practice we often see updates taking more than 24 hours", and that Google checks subscribed calendars "every 24 to 48 hours".
Those figures are about subscriber clients polling; whether the published ICS document itself is regenerated live on each GET or served from a lagging server-side cache is not documented anywhere authoritative that was found - to confirm empirically by editing an event and re-fetching the URL.
Plan for staleness on the order of minutes-to-hours, not seconds.

## 3. Other routes

- EWS (Exchange Web Services): ruled out.
  The official [deprecation page](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-ews-exchange-online) timeline says: "October 2026: EWS starts to be disabled globally for all organizations. ... April 2027: EWS is fully disabled."
  Building new EWS integration one month before global disablement starts would be malpractice.
- Share the work calendar to an external/personal address: viable if policy allows, and interesting as an indirection.
  Per [Sharing policies in Exchange Online](https://learn.microsoft.com/en-us/exchange/sharing/sharing-policies/sharing-policies): "If you don't change anything, then all users can invite anyone with an email address to view their calendar", with the admin-chosen detail level, and "Users share their calendar by sending an email invitation to the external user. The calendar can be opened through a URL link, or can be accessed as an additional calendar folder."
  Concretely: share the work calendar to a personal outlook.com account, then read it from that personal account, where Oscar faces zero corporate API restrictions (personal Graph access or republish from the personal account).
  Fidelity and detail level of externally shared calendars, and whether the corporate policy allows more than free/busy externally, are to confirm; the maximum level named in the sharing-policy doc tops out at "time, subject, location, and title", i.e. not bodies/attendees.
- Manual .ics export: always works (Outlook on the web can download the calendar as an .ics file), but it is a one-shot snapshot with no updates, so it is only a stopgap for prototyping the parser (export UI location to confirm; not sourced here).
- Power Automate: worth keeping on the list.
  The [Office 365 Outlook connector](https://learn.microsoft.com/en-us/power-automate/email-overview) can trigger on calendar events and read calendar events, and Power Automate is commonly licensed for all M365 employees even where app registration is blocked, because flows run inside the tenant's own governance.
  A flow could, for example, push upcoming events to a webhook or file that the local app reads.
  Caveats: environment DLP policies can block connectors or outbound HTTP actions, and the "commonly available" claim is not confirmed in a fetched source - both to confirm in Oscar's tenant.
- Outlook desktop local data (OST): ruled out.
  The OST is a proprietary, MAPI-oriented cache format with no supported external read API, may be encrypted/locked by the running Outlook process, and parsing it would be fragile and possibly against corporate endpoint policy (reasoning, not sourced).

## 4. Python libraries (versions checked directly against the PyPI JSON API on 2026-08-27)

- [msal](https://pypi.org/project/msal/) 1.38.0, released 2026-08-24: Microsoft's official auth library, clearly actively maintained; the right choice for token acquisition in the Graph route.
- [msgraph-sdk](https://pypi.org/project/msgraph-sdk/) 1.61.0, released 2026-08-05: the official Microsoft Graph SDK for Python, actively maintained but heavyweight (Kiota-generated, large dependency tree).
  For a read-only calendar view, plain `requests` against `GET /me/calendarView` with an msal token is a defensible lighter alternative (opinion, not sourced).
- [O365](https://pypi.org/project/O365/) 2.1.9, released 2026-01-30: popular community wrapper over Graph with pleasant calendar ergonomics; maintained but community-run, so it should be treated as a convenience layer, not a foundation.
- [icalendar](https://pypi.org/project/icalendar/) 7.3.0, released 2026-08-19: the standard ICS parser, very actively maintained; needed for the published-ICS route.
- [recurring-ical-events](https://pypi.org/project/recurring-ical-events/) 3.8.2, released 2026-04-30: expands RRULE recurrences from icalendar data into concrete occurrences; maintained, and effectively mandatory for the ICS route because corporate calendars are full of recurring meetings.

## 5. Checklist: self-detect vs ask IT

### (a) Oscar can detect himself, without IT

- Open Outlook on the web > Settings > Calendar > Shared calendars and look for "Publish a calendar".
  Present with detail-level choices means the ICS route is open at those levels; absent means the sharing policy blocks anonymous publishing ([KB 3187580](https://learn.microsoft.com/en-us/troubleshoot/exchange/outlook-on-the-web-issues/publish-calendar-option-missing-from-calendar-settings)).
- If publishing works: publish at the highest offered level, fetch the ICS URL from Python, edit a test event, and measure how long the feed takes to reflect the change (settles the freshness question empirically).
- In the same settings, try sharing the calendar to a personal email address and note which permission levels are offered externally (probes the external sharing policy).
- Visit [https://entra.microsoft.com](https://entra.microsoft.com) (aka portal.azure.com) with the work account and try App registrations > New registration.
  Success means self-registration is allowed; a disabled button or error means the "Users can register applications" switch is off ([default user permissions](https://learn.microsoft.com/en-us/entra/fundamentals/users-default-permissions)).
  Note the portal-access restriction switch documented on that same page "does not block programmatic access", so a blocked portal alone is not conclusive.
- Sign in to [Graph Explorer](https://developer.microsoft.com/graph/graph-explorer) with the work account and consent to `Calendars.Read`, then run `GET /me/calendarView`.
  This probes both consent posture and API access; note Graph Explorer is a Microsoft first-party multi-tenant app, so a third-party or self-registered app may still be treated more strictly (uncertain).
- If any consent attempt shows an "Approval required" dialog with a justification box, the admin consent request workflow is enabled and there is a sanctioned path to ask for approval ([consent overview](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview#admin-consent-workflow)).
- Check whether [https://make.powerautomate.com](https://make.powerautomate.com) opens with the work account and whether the Office 365 Outlook connector's calendar triggers are usable.

### (b) Must ask IT for

- If app registration is blocked: either the Application Developer role, or for IT to register a first-party app with delegated `Calendars.Read` + `offline_access` and hand over the client ID.
- If user consent is blocked and the workflow is off: admin consent for the specific app (single user, read-only delegated scope is the easiest possible ask).
- If the publish option is missing and the Graph route fails: a sharing-policy change adding the Anonymous domain, or a higher external sharing detail level.
- Whether any Conditional Access policy blocks device code flow or sets a short sign-in frequency (affects how often the local app forces reauthentication).
- If Power Automate is blocked: DLP/connector policy exceptions.

## Bottom line for the decision

Two realistic primary routes emerged, plus one hybrid fallback; none can be chosen definitively until the self-detect probes in section 5a are run against the actual tenant.

- Published ICS feed: lowest effort (anonymous GET + icalendar + recurring-ical-events, no auth code at all), zero IT interaction if the option is present, but it is policy-gated per user, may be capped below "full details", freshness is undocumented and community-reported at hours of lag, and IT can silently disable it later.
- Microsoft Graph with delegated auth (auth code + PKCE via msal): the technically best product (fresh data, full event detail, stable contract, EWS-successor API Microsoft is actively investing in), but it stacks two policy gates (app registration and consent) that 2025-era "Secure by Default" tenants often close, and an always-running app must handle refresh-token revocation and sign-in-frequency interruptions gracefully.
  Registering the app in a personal tenant does not dodge the work tenant's consent gate, so the worst case genuinely requires one IT interaction (an admin consent for a single read-only scope, which is a small and reasonable request).
- Fallbacks if both gates are closed: share the work calendar to a personal outlook.com account and read it from the personal side (policy-gated on external sharing, detail level likely capped), or a Power Automate flow pushing events out of the tenant (governance-dependent, more moving parts).
- EWS and OST parsing are ruled out (EWS disablement begins October 2026; OST has no supported read path).

The decision therefore hinges on empirical facts Oscar can gather in under an hour with the section 5a checklist, and a sensible architecture would isolate the calendar source behind a small interface so the ICS route can ship first and the Graph route can replace it without touching the rest of the app.
