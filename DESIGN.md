# DESIGN.md

This documents the visual system actually built for Personal Calendar, grounded in `app/static/app.css` and `app/templates/`.
It is descriptive, not aspirational: every claim below traces to a rule or a template in the repo.

## The world: calm paper planner

The app is built as an analog day-planner made digital, not a dashboard of cards.
`app/templates/base.html` states the thesis in an HTML comment above the shell: warm paper ground, ink text, leather-green action ink, red urgency ink, copper for Claude's work, a serif display over a system sans, hairline rules instead of boxes.
The layout backs this up structurally: task lists are ruled lines (`.task-row` has a `border-bottom`, not a card boundary), and the few boxed surfaces (project cards, the task editor, the calendar grid) are reserved for things that are genuinely objects, not list rows.

## Color: light and dark tokens

All color lives in CSS custom properties on `:root` in `app/static/app.css`, redefined under `@media (prefers-color-scheme: dark)`.
There is no separate dark stylesheet or class toggle; the app follows the system theme (`color-scheme: light dark` is set explicitly).

| Token | Light | Dark | Role |
|---|---|---|---|
| `--paper` | `#f3efe5` | `#191611` | Page background: the desk. |
| `--sheet` | `#fbf9f3` | `#211d16` | Card and panel surfaces (project cards, tray, calendar grid). |
| `--sheet-raised` | `#fffdf8` | `#272219` | Elevated surfaces: the nav's active tab, the task editor, checkboxes, buttons. |
| `--ink` | `#292418` | `#ece4d0` | Primary text. |
| `--ink-2` | `#6d6551` | `#a89d85` | Secondary text: meta rows, nav links, project status. |
| `--ink-3` | `#9a9180` | `#776e5b` | Tertiary text: placeholders, counts, empty-state copy, disabled-ish chrome. |
| `--rule` | `#e3dcc9` | `#35301f` | Hairline dividers (task rows, day groups). |
| `--rule-strong` | `#c9bfa6` | `#4c4530` | Heavier dividers (section headers, grid head), input/button borders. |
| `--act` | `#43604b` | `#a3c6a7` | "Leather green": links, the checked state, primary buttons, today's date dot, focus rings. |
| `--act-soft` | `#43604b1f` | `#a3c6a726` | Tinted backgrounds for active nav, local-event chips, focus glow. |
| `--red-ink` | `#a03a26` | `#d98f76` | Urgency: missed blocks, due-soon, the now-line on the calendar. |
| `--red-soft` | `#a03a2617` | `#d98f7621` | Tinted background for the `needs_review` chip. |
| `--copper` | `#925430` | `#cf9a68` | Claude's ink: the running chip, work-calendar events, nudge icons. |
| `--copper-soft` | `#9254301a` | `#cf9a6824` | Tinted background for the running chip and work-event blocks. |
| `--shadow` | two-layer soft shadow, dark at low opacity | same shape, higher opacity for a darker ground | Elevation for cards, the tray, the task editor, the calendar grid, the block menu. |

Semantically the palette has exactly three "inks" beyond neutral text: green for action/human intent, copper for Claude's work, red for urgency and the past going wrong (missed blocks, overdue dates).
Every colored surface (`*-soft` tokens) is a low-alpha tint of its ink, never a separate flat color, so light and dark stay in the same family automatically.

## Type

Two families, declared as `--serif` and `--sans` custom properties:

- **Display serif**: `"Source Serif 4", "Iowan Old Style", Georgia, serif`, loaded from Google Fonts in `base.html` (weights 400-700, italic included).
  Used for `h1`/`h2`/`h3`, the weekday header (`.day-header .weekday`, 2rem/700), project card titles, the task editor's title field, and italic empty-state copy.
- **Body sans**: `"Seravek", "Segoe UI", system-ui, sans-serif`.
  Used for everything else: body text at `0.9375rem`/1.5 line-height, meta rows, chips, buttons, form fields.

The serif is reserved for moments that read as "written," not chrome: page titles, task/project names in their display form, and the italic placeholder text in quick-add (`font-style: italic; font-family: var(--serif)`), which reads like a prompt penciled at the bottom of a page.
Numbers that need to line up (dates, times, counts, progress) get `font-variant-numeric: tabular-nums` throughout rather than a separate mono face.

## Component language

**Ruled rows, not boxes.** `.task-row`, `.milestone`, `.nudge`, `.list-section > h2` all use a `border-bottom` (or `border-top`) hairline against `--rule` or `--rule-strong` rather than a card wrapper. This is the dominant pattern for lists: today's tasks, next-days groups, project milestones, and the nudge inbox all read as a ruled page, not stacked cards.

**Sheet cards for objects.** A small set of things are genuinely boxed, on `--sheet`/`--sheet-raised` with a `1px solid var(--rule)` border, `border-radius` in the 10-12px range, and `--shadow`: the project card, the task editor, the tray, the calendar grid, the nudge center, and the block-menu popover. These are used for things with their own identity (a project, an editable form, the calendar surface), never for a single list item.

**Chips as stamps.** `.chip` (task status: queued/running/needs_review/blocked/in_progress) is a pill (`border-radius: 99px`) with a `1px solid currentColor` outline and uppercase, letter-spaced, small-caps-weight text, deliberately reading as a rubber stamp rather than a filled badge. The `running` chip additionally carries `.dot`, a small filled circle. `.allday-pill` on the calendar is the same idea flattened for a denser context (filled tint, no outline).

**Hairlines over boxes, everywhere.** Even inside boxed components, internal structure is hairlines: `.milestone` rows inside a project card use `border-top: 1px solid var(--rule)` between them rather than their own boxes; `.nudge + .nudge` likewise.

**Ghost-outline convention.** A missed calendar block that started today renders as `.cal-item.ghost`: transparent fill, `1.5px dashed var(--rule-strong)` border, `--ink-3` text, `opacity: 0.8`, and `pointer-events: none` (per SPEC section 3, it is not interactive, just an honest trace of the day). This is the only dashed-border element in the system, which keeps it legible as "this didn't happen" rather than another interactive block.

**Missed / red-ink convention.** Anything signaling lateness or urgency uses `--red-ink` text directly rather than a background fill: `.task-meta .missed` (bold red-ink label), `.task-meta .due.soon`, `.milestone .target.soon`, `.tray-task .tray-meta .due`. The one filled exception is the `needs_review` chip, which gets `--red-soft` as a background because it is a status stamp, not an inline warning.

**Icons.** Every icon in the app is an inline SVG, 20x20 viewBox, `stroke-width="1.6"`, `stroke-linecap/linejoin="round"`, `fill="none"` and colored via `stroke="currentColor"` (so they inherit ink/act/copper/red-ink from context) -- see the five nav icons in `base.html` (today, next days, backlog, calendar, projects), the milestone flag and pin icons, and the nudge/dismiss icons in `partials/nudges.html`. They read as drawn, single-weight line marks, matching the pen-and-paper metaphor, never as filled glyphs.

## Spacing and radius

Spacing is rem-based off the `0.9375rem` (15px) body size, with no separate spacing scale file; values cluster at `0.25rem` steps for tight gaps (chip padding, icon gaps) up through `0.75rem`-`1.25rem` for row/card padding and `1.5rem`-`3rem` for section and page-level rhythm (`.list-section` bottom margin `2.5rem`, `.main` page padding `3rem` on desktop).

Radius scales with a component's weight, not a single fixed value:

- `5px` -- small controls: the task checkbox, allday pills.
- `7px`-`8px` -- everyday interactive chrome: nav links, form fields, buttons, calendar items, tray tasks.
- `10px` -- popovers and the inline task editor.
- `12px` -- the top-level sheet surfaces: project cards, the tray, the calendar grid, the nudge center.
- `99px` -- pills: status chips only.

## Interaction grammar

**Checkbox draw-in.** `.task-check` is a custom checkbox: unchecked it's an outlined square; `:checked` fills with `--act` and a checkmark (`clip-path: polygon(...)`) scales in from `0` to `1` over `160ms` with a `cubic-bezier(0.22, 1, 0.36, 1)` overshoot easing, i.e. the mark draws itself in rather than popping or fading.

**Breathing running dot.** The `running` chip's `.dot` animates `opacity` between `0.35` and `1` on a `2.4s ease-in-out infinite` cycle (`@keyframes breathe`), read as a slow pulse for "in progress." All animation, including this one, is disabled under `prefers-reduced-motion: reduce` (transition durations collapse to `0.01ms`, the dot animation is removed outright).

**htmx row swaps.** The app is server-rendered with htmx doing the client wiring: checking a task posts to `/ui/tasks/{id}/toggle` and swaps the `<li>` via `hx-target`/`hx-swap="outerHTML"`; clicking a task title fetches its inline editor the same way. Newly swapped-in rows fade in (`.task-list li.htmx-added { opacity: 0 }` transitioning to `1` over `240ms`), so list changes settle rather than snap. A CSRF token is threaded through every htmx request via an `htmx:configRequest` listener in `base.html` that reads the double-submit cookie and sets the `X-CSRF` header (`app/security.py` enforces it server-side).

**Calendar drag (the one JS island).** `app/static/calendar.js` is vanilla JS with all listeners bound to `document` (so they survive htmx swaps of the grid). Four gestures, all snapping to 15-minute increments against the grid's per-day columns:

1. **Drag from the tray**: dragging a `.tray-task` onto a `.day-col` shows a live `.cal-item.preview` (dashed act-colored outline) and creates a block on drop.
2. **Move a block**: pointer-down on a planned `.cal-item.block` and drag; the block dims to `opacity: 0.45` while a preview tracks the pointer, snapped to 15-minute slots.
3. **Resize a block**: dragging its `.resize-handle` (bottom edge) adjusts only the end time, floored at one snap increment.
4. **Click opens a menu**: a pointer-down/up with no movement (or a click on a completed block) opens `.block-menu`, a small positioned popover with complete/remove actions.

Every mutation posts through `fetch` with the same CSRF header helper as htmx, then dispatches a `calendar:refresh` custom event that triggers an htmx-driven re-render of the grid -- the JS island never hand-maintains DOM state past the gesture itself, it just re-asks the server for the truth.
