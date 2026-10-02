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
- **Hues:** the contract's eight hues colour projects (their flags and their tasks' rules) and, in the notes, habits (`--hue-4`), stays (`--hue-3`) and a habit name that cannot be one (`--hue-8`); inputs use none.

## Type

Neon Signage uses one face, Inter variable, installed in `app/static/design/fonts/` (OFL, licence alongside) and declared in `design.css`; `base.html` preloads it at the same URL, so it is fetched once.
`calt` and `liga` are off, tracking is -0.01em, and weights are 400, 500 and 600 only.
Titles (page, card, week and dialog titles, and the wordmark) use `--font-display` and figures (times, counts, targets, busy hours) use `--font-num`; in Neon Signage both are Inter, so these hooks matter only when another system is installed.
Every font size is a scale token: `--t-caption` 12px, `--t-body-sm` 14px (the default UI size), `--t-body` 16px (inputs, card titles), `--t-sub` 20px (project titles), `--t-h-sm` 24px (page titles).
Dates, times, counts and busy hours are `tabular-nums`.
Field names are 12px/500 graphite Inter, as the notes' "Task" label is: Inter is the only face.

## Shape, space, elevation

- **Radii:** none. Every corner in the app is square (Oscar's call, 2026-09-27): `app.css` sets the system's `--r-tag`, `--r-ctl` and `--r-pill` to 0 after `design.css` loads, and no rule rounds a corner of its own, dots and the now mark included.
- **Inputs are see-through:** every place Oscar writes lets the page show through: a field has no fill, only its line; Today's notepad card and the ruled sheets (Tasks, Me) are the paper at 35%; and checkboxes are unfilled until ticked.
- **Spacing:** the `--s-*` scale (4, 8, 12, 16, 24, 32, 48).
- **Elevation:** resting glass has no shadow; only the block menu, an event's card, the event composer, the add-a-task popover, the task sheet's menus and the toast float, on opaque paper with `--shadow-dropdown`.
  There is one toast, `window.toast` in `shell.js`, for every page; a newer message gets its own full moment.

## Shell

The shell is a 240px matte sidebar plus a content column on the canvas.
The wordmark is Brasa's pattern: the name in 600 followed by a spark period, "Personal Calendar.".
At night the name carries a faint halo (`--ink-glow-text`) and the period glows and strikes once on load, three stutters and then steady, like a tube coming on (`--spark-entrance`).
Nav items are 14px/500 graphite; the active one is ink 600 with Brasa's 3px spark bar, glowing at night, inset 8px from the viewport edge.
Nav is grouped in the Brasa manner: the planning pages (Tasks, Today, Calendar, Weeks) sit under a 12px pewter "Planner" group label, Tasks first since the app opens on it; Projects follows as a second group, Health (Nutrition, Me, Garmin) a third, and Finances (Spending, Accounts, Bills, Goals) a fourth, each under its own label.
The foot carries Brasa's shipped light/dark toggle: the current mode's sun or moon, which rotates and fades into the other, beside the mode's name in 12px pewter.
The names are the installed system's own, read from `design-language.json`: "Day" and "Night" for Neon Signage.
A panel icon beside the wordmark collapses the sidebar to a 64px icon rail (`data-rail="collapsed"` on `<html>`, saved as `pc-rail`, applied before paint).
The shell animates its column width on `--ease` over 220ms.
When collapsed, the wordmark and labels hide, each link keeps its name as a tooltip, group labels become hairlines, and the spark bar stays.
Below 720px the sidebar becomes a bottom tab bar on `--glass-tab-bar`, the spark bar moves above the active tab's icon, and the mode toggle ends the bar as a 44px sun or moon icon past a hairline, with no label; the collapse control stays desktop-only.
Under 600px each tab is its icon, 44px wide; the tabs scroll sideways past the bar's width, it opens with the current page's tab in its middle, and an edge with tabs past it fades (`data-more`, `shell.js`).
Content is 800px wide for list pages (Tasks, Projects), where more width only lengthens a row, and up to 1600px for Today, Calendar and Weeks, so a wide window or a zoomed-out page widens them rather than their margins.
Compact rows (the rail's toggle above the mode's, or C) set Tasks' sheet and Today's notes 28px a row rather than 36px, the text its size: 3px above a 20px line, 4px below; the toggle's three lines close up while it is on, its label the state (Roomy, Compact).
On Today a panel icon at the day header's right (or Ctrl+\) folds the timeline away, the notes taking its column, and back.

## Components

**List cards.** Each project, each week in Rows, the nudge center (at the top of Tasks) and the trays are glass cards; Tasks' groups are not, but rows of its ruled sheet (see Tasks).
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
It is written on the line (see Inputs), shaped like the row it becomes: the row's box (or, to add, a plus in steel, ink once writing), then the title in 14px/500 ink, which wraps as a line of text.
The do-date, time, due, repeat and estimate fields trail the title's last word as small icons in `--steel`, 14px, with the value beside the icon in 12px graphite once set ("tomorrow", "15:00–16:00", "Fri 2 Oct", "1h 30m"); repeat stays an icon, its rule in the tooltip.
The estimate's icon is a stopwatch; its menu offers 15m to 4h, the current length ticked, and No estimate.
A task's estimate shows on its row's meta line in 12px graphite figures while it has no time of its own, and on the trays' cards.
The gaps before and between them are the line's own spaces, widened, so when they wrap they start flush with the title's text.
Each is a 24px target that opens a small menu on paper with the dropdown shadow: Today, Tomorrow, Next week, Pick a date (the native picker) and No date; for the time, Pick a time, then Change the start, Change the end and No time (native pickers, 15-minute steps; a new start keeps the length); or the repeat presets.
The current choice is 600 with a tick, and choosing hands the caret back to where it was.
Writing sets them too: "today", "tomorrow", a weekday's name or "next week" followed by a space becomes the do-date, "at 3", "3pm", "15:30" or "9-10:30am" the time (an hour when no end is given; a bare number stays a word), "due friday" the due date, "every day", "every weekday", "every week" or "every month" the repeat, and "45m", "1h", "1.5h", "1h30" or "2 hours" the estimate.
A time is the task's block on its do-date: set, it books that time on the calendar; changed, it moves it, with the day if the day changes; cleared, it frees it.
The words leave the title as they convert, and Backspace straight after puts them back as words, which then stay words.
The description follows under the title, aligned with its text.
Editing adds an end line under the description: the project (its flag, filled in the project's colour with the project and workstream named on hover; an outline and "No project" when there is none; one menu of open projects, each after its flag, with their open workstreams indented), a person icon that names Claude when the task is Claude's, its status once it is Claude's or beyond the box, History, and the bin.
History opens under the end line, above a hairline: each change newest first, a 12px pewter line of when and who ("Today 14:02 · Claude"), then a 12px graphite line per field that moved ("Do date: tomorrow → Fri 2 Oct", "Ticked “oil”", "Description edited").
Project and workstream live only there, since the list a task is written in already says which project it belongs to.

To add, each list card ends in the sheet's plus and a pewter placeholder, filed by the card it sits in (a project card's is in that project).
Typing a title opens the icons and the description (focus alone does not, so a composer that folds away never shifts the page under a click), and a line under them: a pewter "Ctrl+Enter to add" hint (hidden on touch), then Cancel in 12px graphite and "Add task" in 12px/600 ink, words on the line with the fog under them on hover, not boxes.
Enter in the title moves to the description, and Ctrl+Enter adds the task and returns to an empty title for the next one.
A task dated away from the list it was written in does not join it; the page regroups instead.

To edit, the row's title swaps the sheet in place, on the row hover fill with its rules above and below in ink (as the notes' task the caret is in), with the caret at the end of the title.
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
A task's "- [ ] " rows are its sub-tasks, each with the task box inline before its words; a ticked sub-task, and a ticked task (title and every row), is crossed out in pewter, its box, "Task" and icons not struck.
A task (or reflection, habit, stay) right under another shares that one's rule, one line between them: it draws none above itself, and the shared rule takes its colour while the caret is in it.
A task with rows under its title has a 12px pewter chevron after "Task" (ink on hover; pointing down when open, right when folded): folded, the task shows its title alone, its hidden rows counted in a pewter caption tag after it ("2 rows") and its row numbers skipping them, and it stays folded with the notes.
At the right of a task's title come its controls, 12px or more after its last word: the task sheet's icons (do date, time, due, repeat, project), each a pewter icon with its value beside it once set, in graphite, and last the rows' trash bin (steel, red on hover).
They stand on the title's last line when they fit there, and when not, on a line of their own under it, still at the right: the row grows by a line, and no row is added to the notes.
A reflection is drawn as a task's rows are, without a box or controls: "Reflection" in 12px `--signal-deep` in its first row's indent, its words in the body grey, and its rules light blue (`--signal` 45% into the paper; the signal itself while the caret is in it).
A habit is drawn as a task is: in its indent its box (ticked by default, filled green) and "Habit" in green (`--hue-4` 85% into ink; pewter once unticked, with its name), then its name in ink at 500 and its note in the body grey, its rules green (`--hue-4` 45% into the paper; the green itself while the caret is in it), and at its row's right its days' icon, the task sheet's repeat icon with its days beside it once set ("Every day", "Weekdays", "Tue, Thu"); a name that cannot be one is underlined in a wavy `--hue-8`.
A stay is drawn as a reflection is, in amber (`--hue-3`: 45% into the paper for its rules, the amber itself while the caret is in it, 85% into ink for "Stay"): each item row its box (the task box, inline, 8px before the words) and its name up to its colon in graphite at 500, amber while unsorted.
A task in a project has its rules in the project's colour, 55% into the paper (the colour itself while the caret is in it; the rule it shares with the task above takes the upper task's colour, and the lower's while the caret is in the lower), and its project control is the flag alone, filled in that colour.
Light blue for reflection, green for habits, amber for stays and the projects' colours are the only colours in the notes that are not ink or grey.
Under the date, a day with a stay lists it item by item on one wrapping line: a 10px box (ink once sorted, amber-ruled until), the name in pewter caption, the value in 14px ink (amber while unsorted, "not sorted" when it has none); each is a button to its row.
Under the card, "Habits not yet written" in pewter caption and each habit due that day not written yet: its name (14px ink at 500) and its days' icon, on the see-through paper inside a 1px green rule; none due, the line is gone.
What is offered while writing (after "/" at a row's start, and after "/habit ") is drawn as the icons' menus are: the paper, a hairline, the dropdown shadow, 32px rows, the matched letters in 600 and a pewter caption beside a command.
No border, no focus ring and no resize handle; the pewter placeholder "Anything on your mind today."
When the notes were saved in another window, a line under the card says so, with Show that version and Keep mine as secondary buttons.

**Tasks.** A page header ("Tasks", the open and undated counts, and a By date / By project segmented control on the right), then the tasks on one sheet ruled as Today's notepad is, its first row the composer ("Add a task…" after the plus), above the first group's rule.
The page runs to the window's foot and the sheet takes what is left of it (at least 420px).
It is the notepad card's paper at 35%, with the same metrics: every row at least 36px tall with its text in the middle (7px above a 22px line, 6px below), on its own `--hairline` rule, and the 44px column of row numbers (12px pewter, tabular) on a fog wash behind a hairline (34px on phones).
Every row is numbered, headers and composers included, and empty numbered rows fill the sheet under the last group, the last of them cut at its edge; a Done fold's hidden rows are not counted.
Each group is bracketed as a notepad task is: a 2px graphite rule above its title row and below its last row, across the row numbers too, one rule between two groups; the group the keyboard is in has its rules in ink, as has the cursor row's number.
A group's title row is its name in 14px/600 ink with its count in pewter; a task row is the notepad's box (square, 14px, graphite-ruled, ink with a paper tick once done) 8px before its title, the meta line and an opened description on the row's own 22px lines, the row growing with them.
By date is one group per do-date group; By project is Projects' cards drawn as groups (their title rows 14px/600, without their status control, which moves cards between Projects' shelves, and with a neutral badge on a parked project that still holds open work), a workstream's tasks one 24px step in, each project's composer a row of its own, then a No project group in the same form, its empty edit slot keeping the counts in line.
The rows are Projects' own markup, so the sheet restyles them under `.tasks-sheet` and Projects keeps its cards.
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

**Me** (Health).
A page header, then one sheet ruled as Tasks' is, each part a group: At a glance (Weight, Age, BMI and Daily energy, read-only in ink at 500, "Not yet" in pewter, then a graphite row saying how the energy is estimated), Weight, Body, Activity and goal, Diet, and Health notes.
Each field is a row: its name in a 112px indent (96px on phones), then its value written on the line, a number followed by its unit in graphite once set; the row takes the click and the hover fill.
Diet, allergies and foods avoided wrap as a notes row does, the row growing, and Enter ends them; Health notes is one row that grows, with its placeholder as its name.
The Weight group's first row writes a weigh-in (the weight, "on" and its day, and a quiet Log; Enter logs it), and each weigh-in follows as a row: its day in the indent, the weight in ink at 500, and the rows' bin on hover.
The page saves each field as it changes.

**Nutrition** (Health).
A day's page, wide as Today's: the day's header (its name at 24px, the chevrons, a pill back to Today on any other day, the date, and a key line), then at the left the day's log on a ruled sheet as Me's, and at the right, 400px, the day's chat with Claude, a glass card as tall as the window (sticky), as the timeline is on Today.
The sheet's first group is The day: a row per nutrient (Energy, Protein, Fat, Saturated fat, Carbs, Fibre), its name in the 112px indent, what was eaten in ink at 500, then the plan's target in graphite ("of 2,500 kcal", "of at least 130 g", "of at most 20 g"), what is planned after it as a pewter caption ("+910 planned"), and at the row's right a 200px meter: a 4px hairline track, what is eaten in ink, what is planned after it in steel.
A ceiling passed takes a badge: err "Over" when what was eaten passes it, warn "Over, with planned" when only what is planned would.
Then a group per meal, the first opening with a header row naming the columns in pewter caption (Meals, kcal, protein, fat, sat fat, carbs, fibre); the meal's title row is its name at 600 (a neutral "Planned" badge when it is not eaten yet) and its sums in ink at 500, each item a row of its food in ink, its amount in graphite (wrapping as one piece) with "assumed" in pewter caption when no amount was given, and its figures in graphite, 56px right-aligned tabular columns.
Then the file's notes: a group per section (Notes, Next), a row per line, graphite, a list item after a 4px steel square; a link to one of the folder's own files is its words.
Nothing logged yet, the sheet says so; a file that cannot be read shows an err "Cannot read it" badge and why.
On phones the columns keep energy and protein, and the meters go.

The chat's header is "Claude" at 16px/600 over a pewter caption; its messages are rows divided by hairlines, each a 12px graphite name ("You", "Claude") and pewter time over the words in 14px ink (Oscar's at 500, Claude's as Markdown: paragraphs, lists, and tables in 12px whose cells break only between words).
While Claude answers, its row names what it is doing in pewter ("Reading the plan…") and its words arrive as written; a failed answer keeps what was said, in graphite, with an err "Did not finish" badge.
The composer ends the card: the message written on the line (a textarea that grows to eight lines), and the spark "Send", the card's one primary, faded while an answer is on its way.
Under 1100px the page is one column: the header, the chat (its messages up to half the window's height), then the log.

**Finances.**
Spending is a month's page laid out as Nutrition's day is (the chat page, `.chat-page`): the month's header ("This month", or the month's name, the chevrons, a pill back to This month, the month and year, and a key line), the month on a ruled sheet at the left, and the month's chat with Claude at the right, the same card as Nutrition's.
The sheet's first group is The month: Spent (with "of $X budgeted" in graphite, a 160px meter and an err "Over" once past it), Came in, Left over, Moved (only when money moved between his accounts) and Not sorted (the count in ink, what is out and in in graphite, "Ask Claude to sort them" in pewter caption), a row each, the name in the 112px indent.
Then Budgets: a spending category a row, those spent in first, most first, the rest by name in pewter; what was spent in ink at 500, then the budget written on the line after "of $" (an empty one is its pewter placeholder, "no budget", alone), what is left in pewter caption or an err "Over", the meter, and the rows' bin on hover; the group ends in a row to add a category.
Came in lists the income categories that had money.
Then a group a day, newest first: its title row the day ("Yesterday", "Mon 28 Sep") and its sum at the right; each transaction a row of its words in ink (its account in pewter caption when there are several), its category chosen on the line (a 180px select in graphite, "Not sorted" in pewter), and its amount at the right, signed, tabular, money in at 500.
Choosing a category saves it and the month's figures follow; on phones the category goes under the words.
Accounts, Bills and Goals are ruled sheets as Me's is, redrawn in place after each change.
Accounts: At a glance (net worth with its change since last month, what he has, what he owes), Import (the file, the account it goes into, Import; then what the import did, or why the file cannot be read in err text, and the latest imports), each account's name and kind written on the line with its balance at the right, balances written by hand, net worth by month, and the sorting rules (their words in `--font-num` ink, their category in graphite).
Bills: At a glance (a month, the next 30 days), Coming up (each payment in the next 30 days, its day in the indent), a group to write a new bill, then a group a bill: its name the head row, written in 600 ink, with an ok "Paid Mon 14 Sep", a warn "Not seen yet" or an err "Not seen for ..." badge; its amount, cadence and next due day on one row (a non-monthly bill's cost a month in pewter caption); and the words its payment says.
Goals: a group to write a new goal, then a group a goal: its name, its target and by when, where it is kept (an account, or "counted by hand" with what is saved), and So far: what is saved in ink, "of $X" in graphite, what is to go and what a month gets there in pewter caption, and a meter; an ok "Reached" or a warn "Past its day" badge on its name.
The ok, warn and err badges are `.chip.ok`, `.chip.warn` and `.chip.err`.

**Done fold.** Finished tasks fold away under a list: a pewter "Done" summary with its count and a steel chevron that turns when open, then the rows, checked and struck through, ready to untick.
On Tasks it is the sheet's last group, noting "last 14 days".
Which folds are open is remembered per tab (`sessionStorage` key `pc-open-folds`).

**Keys dialog.** `?` on any page opens every key, grouped Anywhere, Writing a task and Lists, on the confirm dialog's paper, 760px wide in two columns (one under 640px).
Each column is one grid, so all its descriptions start on one line; keys are 12px graphite in hairline boxes.
The dialog takes focus itself, so no control opens ringed; Esc closes it.

**Capture window.** N or Shift+N writes a new task from any page: on Tasks and Projects into the page's own list, and on Today, Calendar and Weeks, which have no list to write in, in a window holding the task sheet (600px, 15vh from the top, on the confirm dialog's paper).
It stays open for the next task, and a toast says where each one went ("Added “Call the plumber” for Fri 2 Oct", or "to No date"), since no list on the page shows it; Weeks' Unplanned tray catches up.
Esc closes it and keeps a half-written draft for the next time.

**Buttons.** `.btn.primary` is the spark primary, glowing at night, `.btn.quiet` the glass secondary, `.btn.danger-quiet` the destructive secondary with an err border.
Week navigation and nudge actions are secondary-style controls.

**Inputs: written on the line, as Today's notes are** (Oscar's call, 2026-09-30, replacing the settei plates of 2026-09-27).
Every place Oscar writes is a line of the notebook: no box, no fill and no focus ring, the words straight on a rule, 22px of 14px ink on a 36px line as the notes' rows are, pewter placeholders, date and time in `--font-num`, a select's words followed by a small steel chevron, and an empty date in pewter.
On a ruled sheet (Tasks, Me) the rows are the lines: a field is a row, its name in the row's indent in 12px/500 graphite, and the field in use has its row number in ink 600 and its group's rules in ink, as the notes' caret row does.
Elsewhere (the event, workstream and new-project forms, the project editor, Weeks' quick add) a field is its name in 12px/500 graphite over a 1px steel line (3:1 as a field's edge), the line 2px ink and the name ink while it is in use.
Their buttons are the app's own, 36px beside a form's fields; the task sheet's are words on its line (see Task sheet).
Projects' status select is its words in 12px/500 graphite and the steel chevron, the fog under it on hover.
Focus elsewhere in the app is unchanged: every other focus ring is `--spark-deep`, not `--spark`, since accent text holds 4.5:1 on every surface where the bright spark can sink into a glow of its own colour.

**Time grid** (Calendar's day, three days and week, and Today's one-day timeline, one partial).
The page title names the days shown ("Friday 2 October 2026", "2–4 October 2026", "28 Sep – 4 Oct 2026"), and the header's Day, 3 days and Week is the segmented control, as Weeks' Grid and Rows is; on a phone its options take 10px sides so it fits beside the steps.
New event, a quiet "+" line as Add a workstream is, starts the tools row under the title, Sync work at its right.
The grid runs the whole day, 48px an hour, in a card that scrolls within the window; the day heads and all-day events stay on paper at its top as the hours pass under them.
Day heads are 12px pewter over a 14px/600 number, with today in `--spark-deep`, glowing at night.
Under the number, a day to come carries its load in 12px figures: "45m planned" in graphite over "3h free" in pewter, one to a line; when the planned is more than the free, both sit in the warn badge.
Today's timeline, which has no heads, carries the same on one line ("45m planned · 3h free") above its hours.
Weekend columns carry `--ink-tint-faint`, whichever days are shown.
Items are square tags with a 2px gap below, so back-to-back items never merge:

- work meetings are a quiet ink tint in graphite;
- personal events are glass with a hairline;
- task blocks are solid `--solid`, with `--solid-glow`;
- completed blocks are fog with a strikethrough;
- a cancelled meeting is a hairline outline, its title pewter and struck through;
- today's missed blocks are a dashed mist ghost;
- a drag preview, and the time being written in the composer, is `--spark-tint` with a dashed spark edge.

Items starting within half an hour of each other share the column in lanes; one starting later is laid over the items still running, 14px further in for each step (three at most), opaque and ringed in 1px of paper, so neither blurs into the other.
Titles wrap between words over the lines an item's height allows, stopping above any item laid over it; a word too long for its lane is cut, never broken.
A five-minute meeting is still drawn 20px tall, and laid out as drawn.
The grid's one light is the now-line in `--signal` (cyan in Neon Signage, glowing at night), whose time is written in `--signal-deep` in the gutter.
An hour label whose digits the time would overlap (centres within 12px) is hidden, so the gutter never shows a clipped "06:00" behind "06:21".

**Weeks.** The Grid/Rows switch is Brasa's segmented control: a pill track, the active option `--carbon` with `--on-carbon` text (deep violet at night, never the spark's pink).
*Grid* is a card of six weeks by seven days, in the manner of Brasa's month calendar: 12px pewter weekday heads, cells at least 112px tall, tinted weekends, past day numbers and entries in pewter, and today's number in the 2px spark ring, glowing at night, the board's one spark.
*Rows* is one card per week, a 14px/600 date column and wrapped entries, with the week's meeting load right-aligned over the days' figures.
Entries are one line each:

- all-day events are glass or ink-tint tags;
- deadlines are the title with a warn "due" badge;
- personal events are graphite with a steel dot;
- tasks are ink 500 behind a 10-12px box that fills ink when done.

The work calendar shows only as each day's load (meetings and busy hours): pewter, or ink 600 from 4 hours up.
A drop target lights with `--spark-tint` and an inset spark ring.
The add-a-task plus shows on hover, or always on touch, and opens an opaque popover.

**Projects' colours.** A project is one of the eight hues (`--hue-1` to `--hue-8`), shown wherever its tasks are as its flag: a 14px flag filled in the colour, the name said on hover and to a screen reader, never written beside it (task rows, the trays, the task sheet, the notes).
On Tasks a task in a project also has its rule below it in that colour, 55% into the paper (the colour itself under the keyboard's cursor).
A new project takes the hue fewest open projects have; the project editor offers the eight flags in a row, the chosen one ringed in its colour.

**Project cards.** The title is 20px/600, after the project's flag, and opens the project's Gantt (underlined on hover, as a task's title is); it is followed by the open count, a secondary-style status select, and a ghost pencil that swaps in the inline editor.
Workstream rows are 14px/600 with steel circles that turn ink when done (the name then pewter at 500), and their done count.
Each workstream's open tasks are indented beneath it; the other tasks follow under a pewter caption, then the project's task sheet for adding.
Paused and done projects sit on collapsible shelves.
A task files by drag: onto a workstream group, into that workstream; onto another card, into that project with no workstream; onto No project, out of any.
The row in hand fades to 40%, and the target under it lights like a Weeks drop target, `--spark-tint` with an inset 1.5px spark ring.

A ghost bars icon, before the pencil, opens the project as a Gantt chart.

**Gantt** (a project's page, `/projects/<id>`, as wide as Weeks).
A page header (a pewter "‹ Projects", the project's flag and name at 24px, the task counts and the plan's span, the key line) with, at its right, the Weeks / Days segmented control and a quiet This week (or Today) button, then one sheet, ruled as Tasks' is (36px rows, 28px compact, the row numbers on the fog), that runs to the window's foot and scrolls both ways inside itself.
Its header row (48px) and its frozen pane stay put while it scrolls, as a spreadsheet's do: the numbers, a 32px box column, Task (280px, widened by dragging its header's edge, remembered as `pc-gantt-title`), Start, the length (Wks or Days) and Due, on opaque paper edged by a mist line, while the time is the sheet's see-through paper.
Its time is a 52px column a week, or drilled down, a 36px column a day (Start then 112px, for its date).
Column names are 12px/500 graphite; a week's head is its ISO week in 12px/600 ink over its Monday's day in pewter (graphite, with the month, where the month turns); a day's is its initial in pewter and its date in ink (pewter at weekends), under its week's name and Monday ("W41 · 5 Oct") running across the week from its Monday; now's head is `--spark-deep`, glowing at night.
Cells carry hairline rules both ways, as a spreadsheet's; the time's columns are ruled by the table's background, so the empty numbered rows under the last are too, now's column (this week, or today) is tinted `--ink-tint-faint`, and in days so are weekends, each week's Monday ruled in mist.
A workstream's row is 600 with the task box (`--ok-fg` once done, as a task's), a 12px steel chevron before its name that folds it (turned right while folded, its tasks and add row gone, a pewter caption counting them after its name, its row numbers skipping them), and its Start, length and Due its tasks' in pewter (read-only); its tasks are one 24px step in; "Other tasks" heads the rest when there are workstreams; each group ends in a pewter "Add a task…" row after a steel plus, and the sheet in "Add a workstream…".
Groups are bracketed by 2px graphite rules, in ink round the cursor's group, as on every sheet.
A task's bar is 20px of `--solid` (white tubes at night) from its start's day to its due's, in either scale (so a Monday-to-Friday week leaves its weekend), inset 2px and never under 4px, with 8px grips at its ends; done, it is the system's ok green (`--ok-fg` 30% into `--ok-bg`, on a 1.5px `--ok-fg` edge), its box `--ok-fg`, and its title pewter and struck through.
A task due with no start is a 2px, 20px ink tick on its due; a workstream's lane is a 6px graphite summary with 11px end ticks spanning its tasks (`--ok-fg` once done).
Due soon (three days) is a warn badge in Due.
The now-line is the signal, 2px, down through the weeks at today, glowing at night.
The cursor is a 2px `--spark-deep` ring on its cell (glowing at night), over any bar, with the row's number in ink 600 and its week's head on the fog; while the sheet does not have focus it is a 1px steel ring.
A range is `--spark-tint`; a bar being drawn is that tint edged top and bottom in the spark, as a calendar drag's preview.
A cell being written takes its words on its own line (500 ink, on the paper), the ring kept.
A task's row number is its grip (a steel six-dot mark beside it on hover): dragged, the row fades to 40%, a 2px spark line (glowing at night) marks where it would land, and the group it would land in takes `--spark-deep` rules.
On phones the Task column narrows to 150px and Start, Wks and Due fold away; the bars are still drawn and dragged.

**Nudges.** A glass card of rows with graphite icons, a secondary "Replan" or "Open" action and a steel dismiss control.

## Interaction grammar

Motion is colour, border and background transitions at `--dur` 150ms on `--ease`, and nothing else in the signed-in UI.
The earlier checkbox draw-in, the breathing running dot and the row fade-in were removed.
Beyond that, only these move: the toast, the confirm dialog (an 8px rise with fade), the theme icon's morph, the sidebar's width when it collapses, and the system's two one-shot animations, the wordmark's `--spark-entrance` and a ticked box's `--check-pulse`.
`prefers-reduced-motion` collapses every transition.

**Calendar drag** (`app/static/calendar.js`, vanilla, listeners on `document` so they survive htmx swaps).
A tray card, or an open Today row inside a `[data-drag-to-grid]` list, can be dropped on a day column to create a block, with a live preview.
Planned blocks and Oscar's own events move and resize, snapping to 15-minute increments, an item keeping the place it was held by; on events the resize grip is steel, on blocks `--solid-handle`.
A click on a block opens the opaque block menu; it loads the task's sub-tasks under its title (a caption with the done count, then the checklist, scrolling past 40% of the viewport), so they tick off while in the block, and it re-fits to the viewport once they arrive.
Context lines stay in the task's description; only the sub-tasks come along.
A click on an event, or an all-day event, opens its card (380px, beside the item): a work meeting's title in 16px/600, its day and times, its place, its link as the primary "Join on zoom.us" and a pewter note that it is read-only; a cancelled one has the neutral Cancelled chip and no Join.
One of Oscar's own is written on its card instead: its title in 16px/600 on its line, its repeat and place in graphite, Date, Starts and Ends on lines, then Save and Delete (for a series, Delete this one and This and later), each delete asking first.
Dragging down an empty column draws a new event's time; a click takes the half hour it lands in, for an hour; on touch only a tap writes one, so the grid still scrolls.
Either opens the composer (380px) beside the time: the title on its line in 16px/600, Date, Starts and Ends, Repeat on a line of its own, the length (or "No time: all day") in 12px pewter beside Add event.
Over a time, "Or give a task this time" lists the tasks to schedule, a row each with its badges and flag at the right, the arrow keys lighting one in fog.
New event and E open the composer under the button, on today if it is shown.
Only one card floats at a time; a press outside closes it and does nothing else, and Esc closes it.
Each tray card ends in Book, at its top right in 12px/500 pewter (graphite on the card's hover, ink with the hover fill on its own), as quiet as the do-date buttons; its tooltip names the length it books.
Every mutation re-asks the server by firing `calendar:refresh`; the grid, the tray and on Today the list re-render.
A height-capped grid opens on the usual day, 06:00 at its top, or with now in view an hour and a half under the top as far as 22:00 allows, and keeps its scroll position across refreshes.

**Weeks drag** (`app/static/weeks.js`, native HTML5 drag and drop).
Any `[data-plan-task]` can be dropped on a future day to set its do-date, or on the Unplanned tray to clear it.
Past days refuse drops.
After the PATCH, `weeks:refresh` re-renders the board.

**Writing tasks** (`app/static/task-sheet.js`, `app/static/tasks.js` and `app/static/notes-editor.js`, vanilla, listeners on `document`).
`task-sheet.js` runs the task sheet: the title line, its field icons and their menus, typed words becoming fields, adding, and saving an edit when focus leaves it.
Every field is a hidden input the form posts, so the icons and menus only read and write those inputs; the menus live in the body, since list cards clip what overflows them.
`tasks.js` runs the row disclosures, the Done folds, the cursor on Tasks, Today and Projects, and filing by drag; `shell.js` the keys that work on every page, 1 to 9 for the nav's pages and ? for the keys dialog, and Left and Right (outside a field) on a page of days, a day back or on, and on Calendar, the days it shows.
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
"- [ ] " on a task's row makes it a sub-task, its box one piece like a task's (the caret never in it); Enter on one starts the next, on an empty one takes its box away, and Backspace at its first word too. Its box edits its "[ ]", and an added task has its description written at once (`- [x] ` done, as the task sheet's checklist reads it).
"/stay" at a row's start makes the row a stay, labelled like a reflection; Enter at its end, with nothing under it yet, writes its items (the last stay's names, from the server; place and accommodation the first time), the caret at the first value, as choosing /stay from what is offered does. Enter on an item starts the next ("\t- [ ] "), on an empty item takes its box away, and its box edits its "[ ]"; after an item's box its names are offered. The line under the date follows the notes as they are written.
"/habit name" at a row's start checks a habit (its name the first word, the rest of the row and the tabbed rows under it its note); its box is its row's own lead, "/habit " when done and "/habit [ ] " when unticked, so ticking it edits the row (and undo takes it back).
Its days' icon is the task sheet's (`data-sheet="props"`, one field, `days`): its menu offers Any day, Every day and Weekdays, then each weekday to tick on or off, the menu staying open; a change is written to the habit (`POST /ui/habits/<name>`) and shown in its other place on the page.
The strip under the notes follows the notes as they are written; a name in it writes its row at the notes' end (on their last row, when empty), the caret after it for a note.
What is offered comes from CodeMirror's autocompletion: the commands after "/" at a row's start (choosing /habit goes on to the names) and, after "/habit ", the habits' names and those the page has. Esc belongs to the notes except while an offer is on screen, when it closes it.
A folded task's hidden rows follow its title on one line: a caret landing after them goes to the title's end, and an edit that would reach them (a row added under the title, Delete at its end, a selection across it) unfolds the task instead, the next edit doing what was meant; an undo goes through and unfolds it, and Ctrl+Enter leaves it folded. Folded task rows save with the notes (a text block's `folded`, by row).
Home on a task's, reflection's or habit's row goes to its first word, a selection drawn back to a row's start stops there, Left from there goes on to the row above, and Backspace there takes its box, label or tab away, so the row is plain again.
Ctrl+Enter or Esc in a task saves it: added for the day ("Task added: <title>"), or its title and description written to the task it made ("Task saved: <title>"); Ctrl+Enter then goes on to a fresh plain row.
Ticking a task's box ticks its task; the box shows the task as it stands, wherever it was ticked.
A task's controls open the task sheet's menus (task-sheet.js, `data-sheet="props"`): a field set before the task is added goes with it when it is (a new task's do date is the page's day), and once added each change is written to the task at once, with its words.
Its bin takes its rows out of the notes, an undo step of its own (undo brings the words back, as a task not yet added); a task already added is deleted with them, once the app's "Delete task?" dialog is confirmed (`window.confirmAction`, shell.js, the dialog hx-confirm opens).
The notes save as a whole 600ms after a change, when the tab is hidden, and when the page is left (with every task written or changed since its last save): the text between reflections as text blocks, a task row as "- [ ] " or "- [x] " and the task it made by row (a text block's `links`), each reflection as a reflection block of its words (its first row after "/reflection", its other rows without their tab), each habit as a habit block (its name, done or not, its note), and each stay as a stay block of its rows (as a reflection's), which read back as those rows; saving the page writes the day's habit checks.
A task row keeps the task it made through edits around it (its start mapped through each change) and loses it with its box; an undo that brings a task's rows back brings its task back with them.
A save names the version it was made from; refused (another window saved since), the page stops saving and asks; returning to the tab shows a newer version when nothing here is unsaved.
Esc outside a task steps out of the text; Left and Right, outside it, go a day back or on.

**Gantt** (`app/static/gantt.js`, vanilla, on the sheet itself so its keys come before the page's).
A roving cell cursor (the cursor's cell alone is in the tab order), kept through every redraw by row key and column, and scrolled clear of the frozen pane and header.
Every edit is one JSON POST of ops (`/ui/projects/<id>/gantt`, `app.services.gantt.apply`), answered with the sheet drawn again; requests go one at a time, and a sheet that now starts earlier keeps the same weeks in view.
Right (or Tab) from Due enters the time where the row's work is, not at the sheet's first column: a task's start (or its due), a workstream's first day, and for a task with no days, or a group's add row, the next workday after the dated task above it in its group, never before today (today with none); a day out of sight scrolls in a lead from the pane.
Ctrl+arrows go as a spreadsheet's do: from a filled cell along its run to the run's last, from an empty one to the next filled, else to the sheet's edge; a column of time is filled under a bar, tick or lane, a pane cell by its box or words.
Typing writes over a cell and the arrows then leave it (Excel's Enter mode); Enter, F2 or a double-click write in it with the arrows moving in the words; Enter keeps it and goes down, Tab across, Esc drops it, and a click elsewhere keeps it.
A value the server refuses is said in the toast and the cell opens again on the words.
Every printable key is the sheet's while it has focus (the page's number and letter keys do not fire), except ? for the keys.
Undo keeps the rows' fields as they were before each edit (taken when its turn in the queue comes) and redoes to how they were after; a new task undoes by deleting it, and a deleted task cannot come back, so deleting clears the history.
The pointer: a click moves the cursor (Shift holds a range), a drag over a task's time draws its bar there, a bar's middle drags it and its grips stretch it, a tick drags its due, all by whole columns (weeks, or days), previewed as they move; a row dragged by its number drops before the row it is over (above its middle) or after it, at a workstream's top over its row, and at a group's end over its add row, and undoes back where it was.
Weeks / Days (or V outside the sheet's cells) fetches the sheet in the other scale and keeps the same days in view and the cursor on its day's column; it is remembered (a `gantt_scale` cookie), and edits answer in the scale they were made in.

**The chats** (`app/static/chat.js`, vanilla; Nutrition's and Spending's).
Enter sends and Shift+Enter starts a new line; Left and Right, outside the message, go a day (a month, on Spending) back or on.
Sending draws Oscar's message and Claude's row at once, then reads the answer as it streams (newline-delimited JSON: the words, what Claude is doing, then done), following it down the chat while the chat is scrolled to its end.
Done, the chat and what Claude changed are drawn again from the server (the composer's `data-changed` event: `nutrition:changed`, `money:changed`), the answer as Markdown and the log or the month as Claude left it.
A page opened while an answer is on its way shows it so far and asks after it every two seconds; once it lands, the log or the month is drawn again too (`nutrition:answered`, `money:answered`).
A refused message (empty, or one while Claude is still answering) is said in the toast, and its words go back in the composer.

**Assets.** Static URLs go through `asset()`, which appends the file's mtime (`?v=`), so a browser never pairs new templates with a stale stylesheet.
The favicon is the Today icon in ink on a white tile, its dot the spark (Neon Signage's day pink, `#e5006e`).
It is the one system colour outside `design/`: change it by hand when switching systems.
