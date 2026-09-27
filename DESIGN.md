# DESIGN.md

This describes the visual system actually built for Personal Calendar, grounded in `app/static/app.css` and `app/templates/`.
It is descriptive, not aspirational: every claim below traces to a rule or a template in the repo.

## The system: Neon Signage, from design-language

Since 2026-09-26 the planner wears "Neon Signage", at Oscar's request, picked from three Tokyo Night prototypes (kept on the branch `prototype/tokyo-night`).
It replaced Brasa v2, which the planner wore from 2026-09-25; before that it had its own "calm paper planner" look.

The system is not defined here.
It lives in Oscar's central repo `C:/Users/me/design-language`, beside Brasa, Tokyo Night and Sumi & Neon, all filling one token contract (`CONTRACT.md` there).
Its rules are in that repo's `systems/neon-signage/SYSTEM.md`.
`app/static/design/` holds the installed copy: `design.css` (fonts, shared scales and the system's tokens), the fonts, and `design-language.json` (which system, which version, its mode names, the fonts to preload).
That folder is generated: never edit it; switch or update it with the repo's tool:

```sh
node ../design-language/bin/design-language.mjs use <system> app/static/design
node ../design-language/bin/design-language.mjs update app/static/design
```

`app/static/app.css` holds only components and reads only contract tokens, so a switch changes nothing in it.
`base.html` links `design.css` before `app.css`, preloads the fonts the lock file lists, and names the installed system in its top comment; `design_system()` in `app/ui/views.py` reads the lock file on each render.

The system's rules, as they apply here:

- **Ink draws the interface.** Text, icons, checkboxes and the plan's own blocks are ink; there is no decorative colour in the chrome.
- **Two lights with two jobs.** Pink, `--spark`, is you: the active nav item in the sidebar, the primary button in a form, focus, today on a time grid and on the Weeks board.
  Cyan, `--signal`, is time: the now-line and its label.
  Each still marks one thing per region.
- **Night emits, Day prints.** At night the spark elements glow (`--spark-glow`), the now-line glows (`--signal-glow`), and the plan's own blocks are white tubes with a soft bloom (`--solid-glow`).
  By day every glow is flat, and the same roles are printed colour on a pale sky.
- **Glass.** The canvas (`--canvas`) is the system's: sign glow over black by night, a pale pink-and-sky wash by day; resting surfaces are translucent glass with no shadow; only floating UI is opaque and casts a shadow.
- **Quiet status, loud action.** Status colour (ok, warn, err, neutral pairs) appears only inside badges, never as coloured text runs or large fills.
- **The graphic never carries the meaning alone.** The now-line's time is written in the gutter, and deadlines carry the word "due".

## Colour

All colour is contract tokens from `design.css`: light mode ("Day") on `:root`, dark mode ("Night") under `:root[data-theme="dark"]`.
An inline script at the top of `<head>` sets that attribute before first paint: the choice saved by the sidebar's theme toggle (`localStorage` key `pc-theme`), or else the system theme.
With no saved choice, `shell.js` keeps following the system live.

- **Neutrals:** `--paper`, `--fog`, `--hairline`, `--mist`, `--steel`, `--pewter`, `--graphite`, `--ink`, and `--carbon` for dark chrome with `--on-carbon` text.
  Headings and primary data are ink, secondary text graphite, and placeholders and muted labels pewter.
  `--steel` never draws text: it is for marks (empty checkboxes, muted icons, grips) at 3:1 or more.
- **Spark:** `--spark` with `--spark-deep` for hover and for spark-coloured text, `--spark-tint` for selection and drop-target state only, and `--on-spark` for text on it (near-black at night, since white on neon pink fails contrast).
- **Signal:** `--signal` draws the now-line, `--signal-deep` writes its time.
- **Solid:** `--solid`, `--on-solid` and `--solid-handle` make task blocks solid ink in both modes: deep indigo by day, white tubes at night.
  Without the inversion, dark-mode blocks sat at almost the same grey as work meetings.
- **Status pairs:** `--ok-*`, `--warn-*`, `--err-*`, `--neutral-*`, rendered on glass through the `--badge-*-glass` fills.
- **Canvas and glass:** `--canvas` (fixed to the viewport), `--chrome-flank` (the matte sidebar), `--glass-card`, `--glass-border`, `--glass-input`, `--glass-btn`, `--glass-hover`, `--glass-row-hover`, and ink-alpha hairlines `--hairline-on-glass(-strong)`; `--ink-tint-faint` tints weekends.
- **Hues:** two of the contract's hues draw the inputs (see Inputs): `--hue-6` is the drafting blue of their rules, `--hue-8` the red pencil of the field in use; the other six are installed but not used yet.

## Type

Neon Signage uses one face, Inter variable, installed in `app/static/design/fonts/` (OFL, licence alongside) and declared in `design.css`; `base.html` preloads it at the same URL, so it is fetched once.
`calt` and `liga` are off, tracking is -0.01em, and weights are 400, 500 and 600 only.
Titles (page, card, week and dialog titles, and the wordmark) use `--font-display` and figures (times, counts, targets, busy hours) use `--font-num`; in Neon Signage both are Inter, so these hooks matter only when another system is installed.
Every font size is a scale token: `--t-caption` 12px, `--t-body-sm` 14px (the default UI size), `--t-body` 16px (inputs, card titles), `--t-sub` 20px (project titles), `--t-h-sm` 24px (page titles).
Dates, times, counts and busy hours are `tabular-nums`.
Input captions and the buttons that finish writing are set in Barlow Condensed 600 (`--font-label`), uppercase with 0.16 to 0.18em tracking: the one face beside Inter, self-hosted as a Latin subset in `app/static/fonts/` (OFL) by `scripts/fetch-label-fonts.py`.

## Shape, space, elevation

- **Radii:** none. Every corner in the app is square (Oscar's call, 2026-09-27): `app.css` sets the system's `--r-tag`, `--r-ctl` and `--r-pill` to 0 after `design.css` loads, and no rule rounds a corner of its own, dots and the now mark included.
- **Inputs are see-through:** every place Oscar writes lets the page show through: drafted plates fill with `--draft-fill` (their paper at 40%) under the graph grid, Today's notepad card is the paper at 35%, and checkboxes are unfilled until ticked. The field in use takes its red pencil as a 1px outline 2px clear of its rule, so the gap between them is see-through too.
- **Spacing:** the `--s-*` scale (4, 8, 12, 16, 24, 32, 48).
- **Elevation:** resting glass has no shadow; only the block menu, the add-a-task popover, the task sheet's menus and the toast float, on opaque paper with `--shadow-dropdown`.
  There is one toast, `window.toast` in `shell.js`, for every page; a newer message gets its own full moment.

## Shell

The shell is a 240px matte sidebar plus a content column on the canvas.
The wordmark is Brasa's pattern: the name in 600 followed by a spark period, "Personal Calendar.".
At night the name carries a faint halo (`--ink-glow-text`) and the period glows and strikes once on load, three stutters and then steady, like a tube coming on (`--spark-entrance`).
Nav items are 14px/500 graphite; the active one is ink 600 with Brasa's 3px spark bar, glowing at night, inset 8px from the viewport edge.
Nav is grouped in the Brasa manner: the planning pages (Tasks, Today, Calendar, Weeks) sit under a 12px pewter "Planner" group label, Tasks first since the app opens on it; Projects follows as a second group.
The foot carries Brasa's shipped light/dark toggle: the current mode's sun or moon, which rotates and fades into the other, beside the mode's name in 12px pewter.
The names are the installed system's own, read from `design-language.json`: "Day" and "Night" for Neon Signage.
A panel icon beside the wordmark collapses the sidebar to a 64px icon rail (`data-rail="collapsed"` on `<html>`, saved as `pc-rail`, applied before paint).
The shell animates its column width on `--ease` over 220ms.
When collapsed, the wordmark and labels hide, each link keeps its name as a tooltip, group labels become hairlines, and the spark bar stays.
Below 720px the sidebar becomes a bottom tab bar on `--glass-tab-bar`, the spark bar moves above the active tab's icon, and the mode toggle ends the bar as a 44px sun or moon icon past a hairline, with no label; the collapse control stays desktop-only.
Content is 800px wide for list pages (Tasks, Projects) and 1200px for Today, Calendar and Weeks.

## Components

**List cards.** Tasks' groups, each project, each week in Rows, the nudge center (at the top of Tasks) and the trays are glass cards.
A title row sits on a stronger hairline, and rows below are full-bleed, dividing with hairlines and lighting on hover with `--glass-row-hover`.

**Task rows.** An 18px checkbox with a 6px radius fills with ink when checked; there is no draw-in animation.
Every empty box (rows, sub-tasks, the description editor, Weeks' mini boxes) is drawn in `--steel`, not `--mist`: mist falls under the 3:1 a control needs against the cards, in both modes.
The box the user has just ticked plays the system's `--check-pulse` once (in Neon Signage, a ring of spark light that fades in 640ms); `tasks.js` marks the fresh row `.just-done` for it.
The title is 14px/500 ink, and the meta line is 12px pewter.
Today's block time is ink 500, and a do-date off Today is graphite.
"Due soon" and "missed" are warn and err badges.
A missed task offers one step back onto the plan beside its badge, a quiet 12px pewter button like the do-date buttons: "Replan at 16:30" books the missed block's length into the next free quarter-hour slot today (past timed events and other blocks, before 22:00), or "Move to tomorrow" gives it tomorrow as its do-date when today has no room.
The meta line sits 4px under the title, so the description disclosure can take a full 24px target (WCAG 2.5.8) without touching the title's.
Claude's statuses are badges too: Queued neutral, Running ok (with a static dot), Needs review warn, Blocked err.
A task with a description adds a pewter disclosure to the start of its meta line: a chevron and the sub-task count ("1/3"), or "Notes" when it has none.
Opened, the description sits under the meta line in 14px graphite: context lines as written, sub-tasks as 14px ink checkboxes that fill like the row's own, and a done sub-task pewter with a strikethrough.
An indented line under a sub-task is its note, hung 22px in so it aligns with the sub-task's words.
Which descriptions are open is remembered per tab (`sessionStorage` key `pc-open-notes`), so Today's live refreshes never fold them shut.
A small trash bin ends each row, steel and hidden until the row is hovered or focused (always shown on touch), and err-tinted on hover.
It, and the task sheet's own bin, open the confirm dialog: opaque paper over the scrim with the modal shadow, titled "Delete task?".
The dialog restates the task's name in ink 600 and offers a Ghost Cancel (focused first) beside a destructive-secondary Delete, never a red primary.
It is the one handler behind every `hx-confirm` that carries `data-confirm-*` attributes (`shell.js`), so the browser's native confirm box never appears.
Each opening hears only its own answer: a dialog's close arrives a moment after it closes, and an Esc followed at once by another Delete must not hand the new question the old one's cancel.

**Task sheet.** Adding a task and editing one are the same sheet, written like a document rather than filled in like a form.
It is a drafted plate (see Inputs) under its caption, shaped inside like the row it becomes: the row's box (or, to add, a plus in the rule's blue, red once writing), then the title in 14px/500 ink, which wraps as a line of text.
The do-date, time, due and repeat fields trail the title's last word as small icons in `--steel`, 14px, with the value beside the icon in 12px graphite once set ("tomorrow", "15:00–16:00", "Fri 2 Oct"); repeat stays an icon, its rule in the tooltip.
The gaps before and between them are the line's own spaces, widened, so when they wrap they start flush with the title's text.
Each is a 24px target that opens a small menu on paper with the dropdown shadow: Today, Tomorrow, Next week, Pick a date (the native picker) and No date; for the time, Pick a time, then Change the start, Change the end and No time (native pickers, 15-minute steps; a new start keeps the length); or the repeat presets.
The current choice is 600 with a tick, and choosing hands the caret back to where it was.
Writing sets them too: "today", "tomorrow", a weekday's name or "next week" followed by a space becomes the do-date, "at 3", "3pm", "15:30" or "9-10:30am" the time (an hour when no end is given; a bare number stays a word), "due friday" the due date, and "every day", "every weekday", "every week" or "every month" the repeat.
A time is the task's block on its do-date: set, it books that time on the calendar; changed, it moves it, with the day if the day changes; cleared, it frees it.
The words leave the title as they convert, and Backspace straight after puts them back as words, which then stay words.
The description follows under the title, aligned with its text.
Editing adds an end line under the description: Project › Milestone (a flag, "Project" when there is none, one menu of open projects with their open milestones indented), a person icon that names Claude when the task is Claude's, its status once it is Claude's or beyond the box, History, and the bin.
History opens under the end line, above a hairline: each change newest first, a 12px pewter line of when and who ("Today 14:02 · Claude"), then a 12px graphite line per field that moved ("Do date: tomorrow → Fri 2 Oct", "Ticked “oil”", "Description edited").
Project and milestone live only there, since the list a task is written in already says which project it belongs to.

To add, each list card ends in the sheet's plus and a pewter placeholder, filed by the card it sits in (a project card's is in that project).
Typing a title opens the icons and the description (focus alone does not, so a composer that folds away never shifts the page under a click), with a pewter "Ctrl+Enter to add" hint (hidden on touch), a drafted Cancel and the red-pencil "Add task".
Enter in the title moves to the description, and Ctrl+Enter adds the task and returns to an empty title for the next one.
A task dated away from the list it was written in does not join it; the page regroups instead.

To edit, the row's title swaps the sheet in place, on the row hover fill, with the caret at the end of the title.
There is no Save: the sheet saves when focus leaves it (a click elsewhere, Tab past its last control, Esc or Ctrl+Enter), and if nothing changed it goes back to its row without a save.
Tab past its last control leaves it even where nothing on the page follows to take the focus; the window losing focus does not.

**Description editor.** One line per block, in 14px graphite.
A line typed as "- words" turns into a sub-task when Enter is pressed: a 14px box, drawn as the line's own `::before`, that fills ink when clicked, with the words in ink, or pewter and struck through once ticked.
Enter on a sub-task starts the next one, Enter on an empty one steps out of the list, and Backspace at a sub-task's start turns it back into plain text.
Shift+Enter under a sub-task writes a note hung 22px in, under its words; Enter on a note starts the next sub-task.
Tab and Shift+Tab nest and un-nest by 22px, at most one level under the line above; where Tab cannot nest it moves focus on, so the keyboard never gets stuck in a description.
Pasted "- " lines arrive as sub-tasks; the editor keeps its own undo.
Esc steps away but keeps a written draft open; Cancel clears it.
The empty-list note hides once the list has a row.

**Notepad.** Today, and every day's page (`/day/2026-09-25`), is a notepad beside the day's timeline.
The header is the day's name at 24px ("Today" on today's), a pair of 32px chevrons for the day before and after, and on any other day a pill back to Today; the line under it gives the date, and the key line names - [ ], Ctrl+Enter, the arrows and "? all keys".
The rest of the left column is one card, the paper at 35% (see-through, as every input), as tall as the window allows (at least 420px; 55vh once the timeline stacks under it), holding the notes ruled like a spreadsheet, written in 14px: the body grey (`--ink` 55% into `--graphite`, darker than the Task label), a task's first line in ink.
Every row is 36px tall with its text in the middle (7px above a 22px line, 6px below), on its own `--hairline` rule from the box's very top, and a 44px column of row numbers (12px pewter, tabular) runs down the left on a fog wash behind a hairline, like a spreadsheet's row headers (34px on phones); empty numbered rows fill the card under the last, the last of them cut at its edge, so a short page never scrolls.
A row too long for the box wraps inside it, its lines 22px apart, and the row grows, its number level with its first line; nothing scrolls sideways.
Plain rows start right after the numbers; a task's rows start one indent in, 76px (70px on phones), their wrapped lines too: in a task row's indent the page draws the task's box (square, 14px, graphite-ruled, ink with a paper tick once done) and "Task" in 12px graphite (struck through in pewter once done), neither of them text nor editable, and its other rows' indent is empty.
Every task is bracketed by a 2px graphite rule above its title and below its last row, across the row numbers too, always; the task the caret is in has its rules and row numbers in ink, as has the caret's row.
At the right of a task's title come its controls, 12px or more after its last word: the task sheet's icons (do date, time, due, repeat, project), each a pewter icon with its value beside it once set, in graphite rather than the sheet's red pencil, with no plate around them, and last the rows' trash bin (steel, red on hover).
They stand on the title's last line when they fit there, and when not, on a line of their own under it, still at the right: the row grows by a line, and no row is added to the notes.
A reflection is drawn as a task's rows are, without a box or controls: "Reflection" in 12px `--signal-deep` in its first row's indent, its words in the body grey, and its rules light blue (`--signal` 45% into the paper; the signal itself while the caret is in it).
A habit is drawn as a task is: in its indent its box (ticked by default, filled green) and "Habit" in green (`--hue-4` 85% into ink; pewter once unticked, with its name), then its name in ink at 500 and its note in the body grey, its rules green (`--hue-4` 45% into the paper; the green itself while the caret is in it), and at its row's right its days' icon, the task sheet's repeat icon with its days beside it once set ("Every day", "Weekdays", "Tue, Thu"); a name that cannot be one is underlined in a wavy `--hue-8`.
Light blue for reflection and green for habits are the only colours in the notes that are not ink or grey.
Under the card, "Habits not yet written" in pewter caption and each habit due that day not written yet: its name (14px ink at 500) and its days' icon, on the see-through paper inside a 1px green rule; none due, the line is gone.
What is offered while writing (after "/" at a row's start, and after "/habit ") is drawn as the icons' menus are: the paper, a hairline, the dropdown shadow, 32px rows, the matched letters in 600 and a pewter caption beside a command.
No border, no focus ring and no resize handle; the pewter placeholder "Anything on your mind today."
When the notes were saved in another window, a line under the card says so, with Show that version and Keep mine as secondary buttons.

**Tasks.** A page header ("Tasks", the open and undated counts, and a By date / By project segmented control on the right), the composer alone in its own card, then the tasks.
By date is one list card per do-date group; By project is Projects' cards (without their status control, which moves cards between Projects' shelves, and with a neutral badge on a parked project that still holds open work), then a No project card in the same form, its empty edit slot keeping the counts in line.
While planning, every row names its do-date, "today" included, whichever way it is grouped.
Each row ends in quiet do-date buttons, always shown since dating is the page's job: "Today" and "Tomorrow" in 12px pewter, and a calendar icon that opens the native date picker.
They darken to graphite on row hover and ink on their own hover; a button for the day the task already has leaves its slot empty, so the columns line up down the page.
On phones they take their own line under the title's text, without empty slots.
Dating a task regroups the page from the server.
The page works from the keyboard alone, as do Today and Projects (each marks its lists' area `data-cursor`).
A 12px pewter line under each of their headers names the page's first keys and ends in "? all keys" (hidden on touch and phones); the focused row is the cursor, drawn as the nav's own marker, a 3px spark bar inset on its left edge with the spark glow, over the row hover fill.
The bar shows for keyboard focus only (`:focus-visible`), never after a click.
It is the one cursor the app draws: a Done fold's header, a Projects shelf's header (as an inset shadow, since its `::before` is the +/− sign) and the item under the keyboard in a task sheet's menu take the same bar (on `--fog` in the menu, which is opaque paper).
Projects' shelves remember being open like the Done folds, so a key acting inside one never folds it away.

**Done fold.** Finished tasks fold away under a list: a pewter "Done" summary with its count and a steel chevron that turns when open, then the rows, checked and struck through, ready to untick.
On Today it is the last row of the Today card; on Tasks it is its own card at the foot, noting "last 14 days".
Which folds are open is remembered per tab (`sessionStorage` key `pc-open-folds`).

**Keys dialog.** `?` on any page opens every key, grouped Anywhere, Writing a task and Lists, on the confirm dialog's paper, 760px wide in two columns (one under 640px).
Each column is one grid, so all its descriptions start on one line; keys are 12px graphite in hairline boxes.
The dialog takes focus itself, so no control opens ringed; Esc closes it.

**Capture window.** N or Shift+N writes a new task from any page: on Tasks and Projects into the page's own list, and on Today, Calendar and Weeks, which have no list to write in, in a window holding the task sheet (600px, 15vh from the top, on the confirm dialog's paper).
It stays open for the next task, and a toast says where each one went ("Added “Call the plumber” for Fri 2 Oct", or "to No date"), since no list on the page shows it; Weeks' Unplanned tray catches up.
Esc closes it and keeps a half-written draft for the next time.

**Buttons.** `.btn.primary` is the spark primary, glowing at night, `.btn.quiet` the glass secondary, `.btn.danger-quiet` the destructive secondary with an err border.
Week navigation and nudge actions are secondary-style controls.

**Inputs: drafted, like a settei sheet** (Oscar's pick, 2026-09-27, from three 90s-anime directions in `tracker/prototypes/input-boxes.html`).
Every place Oscar writes is drawn like the model sheets anime of the 90s was animated from: a *plate*.
A plate is square, ruled with a 1px line in drafting blue (`--draft-rule`: `--hue-6`, softened toward paper by day so a resting field blends in while its edge holds 3:1, and lifted toward ink by night), filled with faint graph paper (16px squares in `--draft-grid` over `--draft-paper`, a hint of blue in paper by day, the sheet's cyanotype by night), with a registration cross just outside each corner.
Above it, a caption: an 11px leader line in the rule's blue, then the field's name in 11px Barlow Condensed caps, graphite.
The field in use is re-marked in red pencil (`--hue-8`): its rule gains a 1px paper gap and a 1px red line around it, its crosses turn red, and its caption turns red with them.
Inside a plate, controls draw nothing of their own: 16px ink text, 40px tall, pewter placeholders, date and time in `--font-num`, a select's chevron drawn in the rule's blue.
Plates are the task sheet (composer and edit, captioned Add a task, then New task once writing; Edit task), the event, milestone and new-project forms, the project editor, Weeks' quick add, and, rule only, Projects' status select.
In a task sheet a set field's value is written in red pencil, and a dashed blue rule divides the title line from the description.
The buttons that finish writing (the sheet's, and those of the inline forms and the project editor) are drafted too: square, 34px (40px beside a form's fields), captions in Barlow Condensed caps; the secondary is a blue-ruled outline, the primary a red-pencil fill with paper-coloured text (deepened by day for 4.5:1).
Everything that holds a plate leaves the 5px its crosses need.
Focus elsewhere in the app is unchanged: every other focus ring is `--spark-deep`, not `--spark`, since accent text holds 4.5:1 on every surface where the bright spark can sink into a glow of its own colour.

**Time grid** (Calendar's week and Today's one-day timeline, one partial).
Day heads are 12px pewter over a 14px/600 number, with today in `--spark-deep`, glowing at night.
Weekend columns carry `--ink-tint-faint`.
Items are 6px-radius tags with a 2px gap below, so back-to-back items never merge:

- work meetings are a quiet ink tint in graphite;
- personal events are glass with a hairline;
- task blocks are solid `--solid`, with `--solid-glow`;
- completed blocks are fog with a strikethrough;
- today's missed blocks are a dashed mist ghost;
- a drag preview is `--spark-tint` with a dashed spark edge.

Titles wrap over the lines an item's height allows.
The grid's one light is the now-line in `--signal` (cyan in Neon Signage, glowing at night), whose time is written in `--signal-deep` in the gutter.
An hour label whose digits the time would overlap (centres within 12px) is hidden, so the gutter never shows a clipped "06:00" behind "06:21".

**Weeks.** The Grid/Rows switch is Brasa's segmented control: a pill track, the active option `--carbon` with `--on-carbon` text (deep violet at night, never the spark's pink).
*Grid* is a card of six weeks by seven days, in the manner of Brasa's month calendar: 12px pewter weekday heads, cells at least 112px tall, tinted weekends, past day numbers and entries in pewter, and today's number in the 2px spark ring, glowing at night, the board's one spark.
*Rows* is one card per week, a 14px/600 date column and wrapped entries, with the week's meeting load right-aligned over the days' figures.
Entries are one line each:

- milestones are ink 600 with a flag;
- all-day events are glass or ink-tint tags;
- deadlines are the title with a warn "due" badge;
- personal events are graphite with a steel dot;
- tasks are ink 500 behind a 10-12px box that fills ink when done.

The work calendar shows only as each day's load (meetings and busy hours): pewter, or ink 600 from 4 hours up.
A drop target lights with `--spark-tint` and an inset spark ring.
The add-a-task plus shows on hover, or always on touch, and opens an opaque popover.

**Project cards.** The title is 20px/600, followed by the open count, a secondary-style status select, and a ghost pencil that swaps in the inline editor.
Milestone rows are 14px/600 with steel circles that turn ink when reached, and a warn badge when the target is close.
Each milestone's open tasks are indented beneath it; the other tasks follow under a pewter caption, then the project's task sheet for adding.
Paused and done projects sit on collapsible shelves.
A task files by drag: onto a milestone group, into that milestone; onto another card, into that project with no milestone; onto No project, out of any.
The row in hand fades to 40%, and the target under it lights like a Weeks drop target, `--spark-tint` with an inset 1.5px spark ring.

**Nudges.** A glass card of rows with graphite icons, a secondary "Replan" or "Open" action and a steel dismiss control.

## Interaction grammar

Motion is colour, border and background transitions at `--dur` 150ms on `--ease`, and nothing else in the signed-in UI.
The earlier checkbox draw-in, the breathing running dot and the row fade-in were removed.
Beyond that, only these move: the toast, the confirm dialog (an 8px rise with fade), the theme icon's morph, the sidebar's width when it collapses, and the system's two one-shot animations, the wordmark's `--spark-entrance` and a ticked box's `--check-pulse`.
`prefers-reduced-motion` collapses every transition.

**Calendar drag** (`app/static/calendar.js`, vanilla, listeners on `document` so they survive htmx swaps).
A tray card, or an open Today row inside a `[data-drag-to-grid]` list, can be dropped on a day column to create a block, with a live preview.
Planned blocks move and resize, snapping to 15-minute increments.
A click opens the opaque block menu; it loads the task's sub-tasks under its title (a caption with the done count, then the checklist, scrolling past 40% of the viewport), so they tick off while in the block, and it re-fits to the viewport once they arrive.
Context lines stay in the task's description; only the sub-tasks come along.
Every mutation re-asks the server by firing `calendar:refresh`; on Today that re-renders the list too.
A height-capped timeline opens an hour and a half before now and keeps its scroll position across refreshes.

**Weeks drag** (`app/static/weeks.js`, native HTML5 drag and drop).
Any `[data-plan-task]` can be dropped on a future day to set its do-date, or on the Unplanned tray to clear it.
Past days refuse drops.
After the PATCH, `weeks:refresh` re-renders the board.

**Writing tasks** (`app/static/task-sheet.js`, `app/static/tasks.js` and `app/static/notes-editor.js`, vanilla, listeners on `document`).
`task-sheet.js` runs the task sheet: the title line, its field icons and their menus, typed words becoming fields, adding, and saving an edit when focus leaves it.
Every field is a hidden input the form posts, so the icons and menus only read and write those inputs; the menus live in the body, since list cards clip what overflows them.
`tasks.js` runs the row disclosures, the Done folds, the cursor on Tasks, Today and Projects, and filing by drag; `shell.js` the keys that work on every page, 1 to 5 for the nav's pages and ? for the keys dialog.
The list keys: Up/Down or J/K move (a Done fold's or shelf's header is a stop, opened by Enter or Space), Shift jumps a group (a project, on Projects), Home and End go to the ends; Enter or E edits, N writes a new task (into the cursor's project where it has one, else the page's own composer), X done, T today, M tomorrow (posted directly where rows have no do-date buttons), B books the next free hour today (the keyboard's drop on Today's timeline; a toast says what it booked, or that today is full), R replans a missed task, D and P open the task sheet on its day or project menu, Space opens the description, Delete deletes after asking, V switches Tasks' views, Esc leaves.
The cursor lands where the work leaves it: on the row that followed one dated, filed, finished or deleted away; on the same task after an edit, wherever it regrouped to; on a task just added when Esc leaves the composer; and on the same task across V's reload (`sessionStorage` key `pc-task-cursor`).
htmx wires up swapped-in content in the same step as the swap (`defaultSettleDelay: 0`, in base.html): with its default 20ms settle, a re-rendered list missed a refresh fired in that gap, and keys and submits met controls not yet wired up. Keys are never queued, since a replayed key cannot type; a sheet htmx has not taken over never submits natively and leaves the page; an open edit caught in a list's re-render keeps its sheet, words, fields and caret where the task's new row lands.
Keys never fire while typing in a field or over a dialog, and reaching for the mouse ends the pass.
Lists that re-render from the server take any half-written task with them: `task-sheet.js` carries its title, description, fields and focus across the swap to the fresh sheet with the same `data-composer-key`.
A task whose add is in flight is not a draft: only the focus moves over, so it is never offered to be added twice, and if its list re-rendered from a moment before the add landed, the lists render again so the new task shows.
`notes-editor.js` is the description editor: a contenteditable whose structure is always its own, since every edit that could split, merge or restyle a line is cancelled in `beforeinput` and redone on a line model.
It writes the same plain text the server stores into a hidden `notes` textarea, so forms and the server never see the editor.
The confirm dialog answers the row it was asked about even when a late list refresh swapped that row while it was open: focus goes back to the row's live twin, and a confirmed delete is sent from it rather than silently dropped with the detached one.

**Notepad** (`app/static/notepad.js`, on CodeMirror 6).
The editor is `app/static/vendor/codemirror.js` (window.CM), built from `scripts/vendor/codemirror` (`npm install`, `npm run build`) and committed, so the app itself has no build step; it takes the page's textarea's place, the textarea holding the notes as the server sends them.
The notes are the text as stored: a task row is its "- [ ] " or "- [x] " line, drawn as its box (one piece: the caret never stands in it), and a task's other rows start with a tab, drawn as its indent; the rows are line decorations, the box, indent and controls widgets, the controls a float at the title's end (so they wrap to their own line by themselves).
"- [ ] " at a row's start makes the row a task, and Enter in a task starts its next row with a tab, under its title ("- " rows its sub-tasks); Enter on an empty tabbed row steps back out to a plain row, and Enter at a title's first word puts a plain row above it.
"/reflection" at a row's start makes the row a reflection, drawn as its label (one piece, like a task's box); Enter in it starts its next row with a tab, as in a task, and Ctrl+Enter goes on to a plain row after it.
"/habit name" at a row's start checks a habit (its name the first word, the rest of the row and the tabbed rows under it its note); its box is its row's own lead, "/habit " when done and "/habit [ ] " when unticked, so ticking it edits the row (and undo takes it back).
Its days' icon is the task sheet's (`data-sheet="props"`, one field, `days`): its menu offers Any day, Every day and Weekdays, then each weekday to tick on or off, the menu staying open; a change is written to the habit (`POST /ui/habits/<name>`) and shown in its other place on the page.
The strip under the notes follows the notes as they are written; a name in it writes its row at the notes' end (on their last row, when empty), the caret after it for a note.
What is offered comes from CodeMirror's autocompletion: the commands after "/" at a row's start (choosing /habit goes on to the names) and, after "/habit ", the habits' names and those the page has. Esc belongs to the notes except while an offer is on screen, when it closes it.
Home on a task's, reflection's or habit's row goes to its first word, a selection drawn back to a row's start stops there, Left from there goes on to the row above, and Backspace there takes its box, label or tab away, so the row is plain again.
Ctrl+Enter or Esc in a task saves it: added for the day ("Task added: <title>"), or its title and description written to the task it made ("Task saved: <title>"); Ctrl+Enter then goes on to a fresh plain row.
Ticking a task's box ticks its task; the box shows the task as it stands, wherever it was ticked.
A task's controls open the task sheet's menus (task-sheet.js, `data-sheet="props"`): a field set before the task is added goes with it when it is (a new task's do date is the page's day), and once added each change is written to the task at once, with its words.
Its bin takes its rows out of the notes, an undo step of its own (undo brings the words back, as a task not yet added); a task already added is deleted with them, once the app's "Delete task?" dialog is confirmed (`window.confirmAction`, shell.js, the dialog hx-confirm opens).
The notes save as a whole 600ms after a change, when the tab is hidden, and when the page is left (with every task written or changed since its last save): the text between reflections as text blocks, a task row as "- [ ] " or "- [x] " and the task it made by row (a text block's `links`), each reflection as a reflection block of its words (its first row after "/reflection", its other rows without their tab), and each habit as a habit block (its name, done or not, its note), which read back as those rows; saving the page writes the day's habit checks.
A task row keeps the task it made through edits around it (its start mapped through each change) and loses it with its box; an undo that brings a task's rows back brings its task back with them.
A save names the version it was made from; refused (another window saved since), the page stops saving and asks; returning to the tab shows a newer version when nothing here is unsaved.
Esc outside a task steps out of the text; Left and Right, outside it, go a day back or on.

**Assets.** Static URLs go through `asset()`, which appends the file's mtime (`?v=`), so a browser never pairs new templates with a stale stylesheet.
The favicon is the Today icon in ink on a white tile, its dot the spark (Neon Signage's day pink, `#e5006e`).
It is the one system colour outside `design/`: change it by hand when switching systems.
