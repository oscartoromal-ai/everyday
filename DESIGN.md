# DESIGN.md

This describes the visual system actually built for Personal Calendar, grounded in `app/static/app.css` and `app/templates/`.
It is descriptive, not aspirational: every claim below traces to a rule or a template in the repo.

## The system: "Brasa" v2

Since 2026-09-25 the planner wears Oscar's own design system, "Brasa" v2, at his request.
Its source of truth lives in the design-workspace workspace: `design-language/systems/brasa/SYSTEM.md` for the rules, and `another-app/src/assets/main.css` for the executable tokens.
`app/static/app.css` copies those token values rather than inventing near-misses, and the top comment in `base.html` names the source.
It replaced the earlier "calm paper planner" look (warm paper, serif headings, leather green and copper).

The system's rules, as they apply here:

- **Ink draws the interface.** Text, icons, checkboxes and the plan's own blocks are ink; there is no decorative colour in the chrome.
- **One spark per region.** The ember accent `--brasa` marks exactly one thing per region: the active nav item in the sidebar, the primary button in a form, "now" on a time grid, today on the Weeks board.
- **Aurora and glass.** The canvas is Brasa's warm Basico aurora; resting surfaces are translucent glass with no shadow; only floating UI is opaque and casts a shadow.
- **Quiet status, loud action.** Status colour (ok, warn, err, neutral pairs) appears only inside badges, never as coloured text runs or large fills.
- **The graphic never carries the meaning alone.** The now-line's time is written in the gutter, and deadlines carry the word "due".

## Colour

All colour is custom properties on `:root`, redefined for dark mode ("Carbon") under `:root[data-theme="dark"]`, the same mechanism Brasa uses.
An inline script at the top of `<head>` sets that attribute before first paint: the choice saved by the sidebar's theme toggle (`localStorage` key `pc-theme`), or else the system theme.
With no saved choice, `shell.js` keeps following the system live.

- **Neutrals:** `--paper`, `--fog`, `--hairline`, `--mist`, `--steel`, `--pewter`, `--graphite`, `--ink`, `--carbon`, with Brasa's exact light and dark values.
  Headings and primary data are ink, secondary text graphite or pewter, placeholders and muted labels steel.
- **Accent:** `--brasa` (#ff5900) with `--brasa-deep` for hover and for ember text, and `--brasa-tint` for selection and drop-target state only.
- **Status pairs:** `--ok-*`, `--warn-*`, `--err-*`, `--neutral-*`, rendered on glass through the `--badge-*-glass` fills.
- **Aurora and glass:** `--shell-bg` (the canvas, fixed to the viewport), `--chrome-flank` (the matte sidebar), `--glass-card`, `--glass-border`, `--glass-input`, `--glass-btn`, `--glass-hover`, `--glass-row-hover`, and ink-alpha hairlines `--hairline-on-glass(-strong)`.
- **Planner additions:** `--block-bg`, `--block-fg` and `--block-handle` make task blocks solid ink in both themes: near-black in light, near-white in dark.
  Without the inversion, dark-mode blocks sat at almost the same grey as work meetings.

## Type

One face, Inter variable, self-hosted from `app/static/fonts/` (OFL, licence alongside) and declared inline in `base.html`, so its URL carries the same cache-busting version as the preload.
`calt` and `liga` are off, tracking is -0.01em, and weights are 400, 500 and 600 only.
Every font size is a scale token: `--t-caption` 12px, `--t-body-sm` 14px (the default UI size), `--t-body` 16px (inputs, card titles), `--t-sub` 20px (project titles), `--t-h-sm` 24px (page titles).
Dates, times, counts and busy hours are `tabular-nums`.

## Shape, space, elevation

- **Radii:** only `--r-tag` 6px (badges, checkboxes, calendar items), `--r-ctl` 12px (buttons, inputs, cards, nav items) and `--r-pill` (status badges, the segmented control).
- **Spacing:** the `--s-*` scale (4, 8, 12, 16, 24, 32, 48).
- **Elevation:** resting glass has no shadow; only the block menu, the add-a-task popover and the toast float, on opaque paper with `--shadow-dropdown`.

## Shell

The shell is a 240px matte sidebar plus a content column on the aurora.
The wordmark is Brasa's pattern: the name in Inter 600 followed by an ember period, "Personal Calendar.".
Nav items are 14px/500 graphite; the active one is ink 600 with Brasa's 3px ember bar, inset 8px from the viewport edge.
Nav is grouped in the Brasa manner: the planning pages (Tasks, Today, Calendar, Weeks) sit under a 12px steel "Planner" group label, Tasks first since the app opens on it; Projects follows as a second group.
The foot carries Brasa's shipped light/dark toggle: the current mode's sun or moon, which rotates and fades into the other, beside its name ("Light mode" or "Dark mode") in 12px pewter.
A panel icon beside the wordmark collapses the sidebar to a 64px icon rail (`data-rail="collapsed"` on `<html>`, saved as `pc-rail`, applied before paint).
The shell animates its column width on `--ease` over 220ms, the way Brasa animates expanding panels.
When collapsed, the wordmark and labels hide, each link keeps its name as a tooltip, group labels become hairlines, and the ember bar stays.
Below 720px the sidebar becomes a bottom tab bar on `--glass-tab-bar`, the ember bar moves above the active tab's icon, and the collapse and theme controls stay desktop-only (a saved theme still applies).
Content is 800px wide for list pages (Tasks, Projects) and 1200px for Today, Calendar and Weeks.

## Components

**List cards.** Today, Delegated to Claude, each project, each week in Rows and the trays are glass cards.
A title row sits on a stronger hairline, and rows below are full-bleed, dividing with hairlines and lighting on hover with `--glass-row-hover`.

**Task rows.** An 18px checkbox with a 6px radius fills with ink when checked; there is no draw-in animation, since Brasa animates colour only.
The title is 14px/500 ink, and the meta line is 12px pewter.
Today's block time is ink 500, and a do-date off Today is graphite.
"Due soon" and "missed" are warn and err badges.
Claude's statuses are badges too: Queued neutral, Running ok (with a static dot), Needs review warn, Blocked err.
A task with a description adds a steel disclosure to the start of its meta line: a chevron and the sub-task count ("1/3"), or "Notes" when it has none.
Opened, the description sits under the meta line in 14px graphite: context lines as written, sub-tasks as 14px ink checkboxes that fill like the row's own, and a done sub-task steel with a strikethrough.
An indented line under a sub-task is its note, hung 22px in so it aligns with the sub-task's words.
Which descriptions are open is remembered per tab (`sessionStorage` key `pc-open-notes`), so Today's live refreshes never fold them shut.
A small trash bin ends each row, steel and hidden until the row is hovered or focused (always shown on touch), and err-tinted on hover.
It, and the editor's Delete button, open the confirm dialog: opaque paper over the scrim with the modal shadow, titled "Delete task?".
The dialog restates the task's name in ink 600 and offers a Ghost Cancel (focused first) beside a destructive-secondary Delete, never a red primary.
It is the one handler behind every `hx-confirm` that carries `data-confirm-*` attributes (`shell.js`), so the browser's native confirm box never appears.

**Composer.** Each list card ends in a quick-add row: a steel plus and a borderless title.
Typing a title opens the description underneath (focus alone does not, so a composer that folds away never shifts the page under a click), aligned with the title's text, with a steel "Ctrl+Enter to add" hint (hidden on touch), a secondary Cancel and the ember "Add task".
Enter in the title moves to the description, and Ctrl+Enter adds the task and returns to an empty title for the next one.

**Description editor.** One line per block, in 14px graphite (16px ink inside the task editor's field).
A line typed as "- words" turns into a sub-task when Enter is pressed: a 14px box, drawn as the line's own `::before`, that fills ink when clicked, with the words in ink, or steel and struck through once ticked.
Enter on a sub-task starts the next one, Enter on an empty one steps out of the list, and Backspace at a sub-task's start turns it back into plain text.
Shift+Enter under a sub-task writes a note hung 22px in, under its words; Enter on a note starts the next sub-task.
Tab and Shift+Tab nest and un-nest by 22px; pasted "- " lines arrive as sub-tasks; the editor keeps its own undo.
Esc steps away but keeps a written draft open; Cancel clears it.
The task editor puts the same editor directly under the title, above the other fields, styled as a field.
The empty-list note hides once the list has a row.

**Tasks.** A page header ("Tasks", the open and undated counts, and a By date / By project segmented control on the right), the composer alone in its own card, then the tasks.
By date is one list card per do-date group; By project is Projects' cards (without their status control, which moves cards between Projects' shelves, and with a neutral badge on a parked project that still holds open work), then a No project card in the same form, its empty edit slot keeping the counts in line.
While planning, every row names its do-date, "today" included, whichever way it is grouped.
Each row ends in quiet do-date buttons, always shown since dating is the page's job: "Today" and "Tomorrow" in 12px pewter, and a calendar icon that opens the native date picker.
They darken to graphite on row hover and ink on their own hover; a button for the day the task already has leaves its slot empty, so the columns line up down the page.
On phones they take their own line under the title's text, without empty slots.
Dating a task regroups the page from the server.

**Done fold.** Finished tasks fold away under a list: a pewter "Done" summary with its count and a steel chevron that turns when open, then the rows, checked and struck through, ready to untick.
On Today it is the last row of the Today card; on Tasks it is its own card at the foot, noting "last 14 days".
Which folds are open is remembered per tab (`sessionStorage` key `pc-open-folds`).

**Buttons.** `.btn.primary` is the ember primary, `.btn.quiet` the glass secondary, `.btn.danger-quiet` the destructive secondary with an err border.
Week navigation and nudge actions are secondary-style controls.

**Inputs.** 16px text, a 12px radius and a hairline border on glass; focus clears the border and draws Brasa's 2px ember ring.

**Time grid** (Calendar's week and Today's one-day timeline, one partial).
Day heads are 12px steel over a 14px/600 number, with today in `--brasa-deep`.
Weekend columns carry `--ink-tint-weekend-cell`.
Items are 6px-radius tags with a 2px gap below, so back-to-back items never merge:

- work meetings are a quiet ink tint in graphite;
- personal events are glass with a hairline;
- task blocks are solid `--block-bg`;
- completed blocks are fog with a strikethrough;
- today's missed blocks are a dashed mist ghost;
- a drag preview is `--brasa-tint` with a dashed ember edge.

Titles wrap over the lines an item's height allows.
The grid's one spark is the ember now-line, whose time is written in ember in the gutter.

**Weeks.** The Grid/Rows switch is Brasa's segmented control: a pill track, the active option carbon with white text.
*Grid* is a card of six weeks by seven days, in the manner of Brasa's month calendar: 12px steel weekday heads, cells at least 112px tall, tinted weekends, past day numbers in steel, and today's number in the 2px ember ring, the board's one spark.
*Rows* is one card per week, a 14px/600 date column and wrapped entries, with the week's meeting load right-aligned over the days' figures.
Entries are one line each:

- milestones are ink 600 with a flag;
- all-day events are glass or ink-tint tags;
- deadlines are the title with a warn "due" badge;
- personal events are graphite with a steel dot;
- tasks are ink 500 behind a 10-12px box that fills ink when done.

The work calendar shows only as each day's load (meetings and busy hours): pewter, or ink 600 from 4 hours up.
A drop target lights with `--brasa-tint` and an inset ember ring.
The add-a-task plus shows on hover, or always on touch, and opens an opaque popover.

**Project cards.** The title is 20px/600, followed by the open count, a secondary-style status select, and a ghost pencil that swaps in the inline editor.
Milestone rows are 14px/600 with steel circles that turn ink when reached, and a warn badge when the target is close.
Each milestone's open tasks are indented beneath it; the other tasks follow under a steel caption, then the project's quick-add row.
Paused and done projects sit on collapsible shelves.

**Nudges.** A glass card of rows with graphite icons, a secondary "Replan" or "Open" action and a steel dismiss control.

## Interaction grammar

Motion follows Brasa's table: colour, border and background transitions at `--dur` 150ms on `--ease`, and nothing else in the signed-in UI.
The earlier checkbox draw-in, the breathing running dot and the row fade-in were removed.
Beyond that, only the entrances Brasa itself uses move: the toast, the confirm dialog (an 8px rise with fade), the theme icon's morph, and the sidebar's width when it collapses.
`prefers-reduced-motion` collapses every transition.

**Calendar drag** (`app/static/calendar.js`, vanilla, listeners on `document` so they survive htmx swaps).
A tray card, or an open Today row inside a `[data-drag-to-grid]` list, can be dropped on a day column to create a block, with a live preview.
Planned blocks move and resize, snapping to 15-minute increments.
A click opens the opaque block menu.
Every mutation re-asks the server by firing `calendar:refresh`; on Today that re-renders the list too.
A height-capped timeline opens an hour and a half before now and keeps its scroll position across refreshes.

**Weeks drag** (`app/static/weeks.js`, native HTML5 drag and drop).
Any `[data-plan-task]` can be dropped on a future day to set its do-date, or on the Unplanned tray to clear it.
Past days refuse drops.
After the PATCH, `weeks:refresh` re-renders the board.

**Writing tasks** (`app/static/tasks.js` and `app/static/notes-editor.js`, vanilla, listeners on `document`).
`tasks.js` runs the composer, the row disclosures and the Done folds.
Lists that re-render from the server take any half-written composer with them: `tasks.js` carries its title, description and focus across the swap to the fresh composer with the same `data-composer-key`.
`notes-editor.js` is the description editor: a contenteditable whose structure is always its own, since every edit that could split, merge or restyle a line is cancelled in `beforeinput` and redone on a line model.
It writes the same plain text the server stores into a hidden `notes` textarea, so forms and the server never see the editor.

**Assets.** Static URLs go through `asset()`, which appends the file's mtime (`?v=`), so a browser never pairs new templates with a stale stylesheet.
The favicon is the Today icon in ink on a white tile, its dot the ember spark.
