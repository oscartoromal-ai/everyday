# DESIGN.md

This describes the visual system actually built for Personal Calendar, grounded in `app/static/app.css` and `app/templates/`.
It is descriptive, not aspirational: every claim below traces to a rule or a template in the repo.

## The system: Neon Signage, from design-language

Since 2026-09-26 the planner wears "Neon Signage", at Oscar's request, picked from three Tokyo Night prototypes (kept on the branch `prototype/tokyo-night`).
It replaced Brasa v2, which the planner wore from 2026-09-25; before that it had its own "calm paper planner" look.

The system is not defined here.
It lives in Oscar's central repo `design-language`, beside Brasa, Tokyo Night and Sumi & Neon, all filling one token contract (`CONTRACT.md` there).
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

- **Ink draws the interface.** Text, icons, checkboxes and the plan's own bars are ink; there is no decorative colour in the chrome.
- **Two lights with two jobs.** Pink, `--spark`, is you: the active nav item in the sidebar, the primary button in a form, focus, today on a time grid.
  Cyan, `--signal`, is time: the now-line and its label.
  Each still marks one thing per region.
- **Night emits, Day prints.** At night the spark elements glow (`--spark-glow`), the now-line glows (`--signal-glow`), and the plan's own bars are white tubes with a soft bloom (`--solid-glow`).
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
- **Solid:** `--solid` makes a Gantt's bars solid ink in both modes: deep indigo by day, white tubes at night.
- **Status pairs:** `--ok-*`, `--warn-*`, `--err-*`, `--neutral-*`, rendered on glass through the `--badge-*-glass` fills.
- **Canvas and glass:** `--canvas` (fixed to the viewport), `--chrome-flank` (the matte sidebar), `--glass-card`, `--glass-border`, `--glass-input`, `--glass-btn`, `--glass-hover`, `--glass-row-hover`, and ink-alpha hairlines `--hairline-on-glass(-strong)`; `--ink-tint-faint` tints weekends.
- **Hues:** the contract's eight hues colour projects (their flags and their tasks' rules), habits (`--hue-4`: their boxes, days and comments) and, in the notes, stays (`--hue-3`); inputs use none.

## Type

Neon Signage uses one face, Inter variable, installed in `app/static/design/fonts/` (OFL, licence alongside) and declared in `design.css`; `base.html` preloads it at the same URL, so it is fetched once.
`calt` and `liga` are off, tracking is -0.01em, and weights are 400, 500 and 600 only.
Titles (page, card, week and dialog titles, and the wordmark) use `--font-display` and figures (times, counts, targets, busy hours) use `--font-num`; in Neon Signage both are Inter, so these hooks matter only when another system is installed.
Every font size is a scale token: `--t-caption` 12px, `--t-body-sm` 14px (the default UI size), `--t-body` 16px (inputs, card titles), `--t-sub` 20px (project titles), `--t-h-sm` 24px (page titles).
Dates, times, counts and busy hours are `tabular-nums`.
Field names are 12px/500 graphite Inter, as the notes' "Task" label is: Inter is the only face, but for code in Markdown (see the Markdown engine).

## Shape, space, elevation

- **Radii:** none. Every corner in the app is square (Oscar's call, 2026-09-27): `app.css` sets the system's `--r-tag`, `--r-ctl` and `--r-pill` to 0 after `design.css` loads, and no rule rounds a corner of its own, dots and the now mark included.
- **Inputs are see-through:** every place Oscar writes lets the page show through: a field has no fill, only its line; Today's notepad card and the ruled sheets (Me, Garmin, Finances) are the paper at 35%; and checkboxes are unfilled until ticked.
- **Spacing:** the `--s-*` scale (4, 8, 12, 16, 24, 32, 48).
- **Elevation:** resting glass has no shadow; only an event's card, the event composer, the add-a-task popover, the task sheet's menus and the toast float, on opaque paper with `--shadow-dropdown`.
  There is one toast, `window.toast` in `shell.js`, for every page; a newer message gets its own full moment.

## Shell

The shell is a 240px matte sidebar plus a content column on the canvas, and at the right the agent window's column while it is docked open.
The wordmark is Brasa's pattern: the name in 600 followed by a spark period, "Personal Calendar.".
At night the name carries a faint halo (`--ink-glow-text`) and the period glows and strikes once on load, three stutters and then steady, like a tube coming on (`--spark-entrance`).
Under the wordmark and Back, New task is the sidebar's one action, from any page: an 18px spark disc with a plus in `--on-spark` (pink is you; glowing at night), then "New task" in 14px/500 ink and its key ("N") in a hairline box at the right, on a nav item's metrics; it opens the capture window (see Capture window).
The icon rail keeps the disc alone, and the phone's tab bar ends its tabs with it, 28px in a 44px target, before the foot's hairline.
Nav items are 14px/500 graphite; the active one is ink 600 with Brasa's 3px spark bar, glowing at night, inset 8px from the viewport edge.
Nav is grouped in the Brasa manner: the planning pages (Today, Calendar) sit under a 12px pewter "Planner" group label, Today first since the app opens on it; Projects follows as a second group, Health (Nutrition, Me, Garmin) a third, Finances (Spending, Accounts, Bills, Goals) a fourth, and Code (Repositories) a fifth, each under its own label.
That is the order the code lists; Oscar's own is kept as the `rail` setting in the database (`app/services/rail.py`), so it holds on every device.
A page (a module) is dragged within its section, never out of it; a section by its label, or by its one page when it has one (Projects); a project among the projects, which is Projects' order too.
A press picks the thing up once it moves 5px: it lifts onto `--paper` with `--shadow-dropdown`, follows the pointer, and the others slide out of its way (160ms) as the pointer passes their middles; Esc puts it back, and the drop is never a click.
Alt+Up/Down moves the focused page or project a place, with Shift its whole section.
On hover or focus a page shows an eye at its right (14px, `--steel`, left of Projects' chevron) that hides it; the toast says so with Undo, and the eyes wait for the pointer to move on, so the page sliding up under it is not hidden by a second click.
A hidden page stays in the markup (`hidden`), so the command menu still reaches it, and a section with every page hidden goes, label and all.
The pages showing are Alt+1 to Alt+9, top to bottom, hidden ones skipped; they are numbered again at once as a page is hidden, shown or moved, and a tenth has no number.
A page's number always shows, between its icon and its name: a 12px/500 `--pewter` tabular figure in an 8px column, right-aligned 6px from the name and set on its baseline.
The column holds its place on every page, numbered or not (a hidden page's, the tenth's), so the names stay in line, and the projects' names under Projects move over with them.
Like the names, the numbers give way on the icon rail and the phone's tab bar.
Under Projects sit the active projects, in Projects' order: 400-weight rows 32px tall, each a 12px flag in its colour, with the name in line with "Projects" and cut short with an ellipsis, opening that project's page.
On any of a project's pages (its page, its Tasks, its Gantt, a document of its context) the project's own row holds the spark, and Projects is `aria-current="true"`.
A chevron at the right of Projects folds the list away and back (`data-rail-projects="folded"`, saved as `pc-rail-projects`, applied before paint); while the list is out of sight (folded, the icon rail, the phone's tab bar), Projects holds the spark on a project's pages.
The list is drawn again when a project is added, renamed, recoloured or shelved (`projects:changed`).
On a desktop rail too short for every page, the nav scrolls between the head and the foot with no scrollbar, and an edge with pages past it fades (`data-more`).
The foot starts with Agent, a sparkle, its name and its key ("A") drawn as Search's are, which expands and collapses the agent window (see The agent window); ink while the window is open, and a 6px spark dot after its name, the Update button's, while an answer is on its way, on the icon's shoulder in the icon rail and the phone's tab bar.
Then Search, its magnifier and name, and its key ("Ctrl K") in a hairline box at the right, as the keys dialog draws keys; it opens the command menu.
Then Brasa's shipped light/dark toggle: the current mode's sun or moon, which rotates and fades into the other, beside the mode's name in 12px pewter.
The names are the installed system's own, read from `design-language.json`: "Day" and "Night" for Neon Signage.
Settings ends the foot, two sliders and its name; it opens the keys dialog's paper, 480px wide, whose Modules section lists the hidden pages, each its icon, its name, its section in pewter and a quiet Show, or says every page is in the sidebar.
On a machine installed without some modules, a line in 14px graphite, as the hint's, 12px under the list, names them and says the installer adds them back ("Not installed on this machine: Finances. Run the installer again to add it.").
Such a module's section is not in the sidebar at all, so its pages take no number.
Its Version section, 24px under, is one 48px row between hairlines: the version in 14px/600 ink, "built from" (or "run from") its commit in 12px pewter, and "Changelog ›" in 12px/500 graphite at the right, ink on hover, the whole row the link.
Back sits under the wordmark, 12px under the date and 24px above the first section, drawn as a foot button: a 16px arrow and "Back to" the page before by its title ("Back to Garden Planner · Gantt"), in 12px/500 pewter, ink on a glass hover, cut short with an ellipsis and whole in its tooltip with its key (Alt+←).
With no page before it (the window's first), it stays, faint in `--mist`, as "Back", so the sidebar under it never moves.
A panel icon beside the wordmark collapses the sidebar to a 64px icon rail (`data-rail="collapsed"` on `<html>`, saved as `pc-rail`, applied before paint).
The shell animates its column width on `--ease` over 220ms.
When collapsed, the wordmark and labels hide, each link keeps its name as a tooltip, group labels become hairlines, and the spark bar stays.
Below 720px the sidebar becomes a bottom tab bar on `--glass-tab-bar`, the spark bar moves above the active tab's icon, and the mode toggle ends the bar as a 44px sun or moon icon past a hairline, with no label; the collapse control and Back stay desktop-only (the phone's browser has its own Back).
Under 600px each tab is its icon, 44px wide; the tabs scroll sideways past the bar's width, it opens with the current page's tab in its middle, and an edge with tabs past it fades (`data-more`, `shell.js`).
Content is 800px wide for list pages (Plan among them), where more width only lengthens a row; 1040px for a project's page, whose sections sit beside each other, and its Tasks; and up to 1600px for Projects, whose timeline lays its projects over weeks, and for Today and Calendar, so a wide window or a zoomed-out page widens them rather than their margins.
Compact rows (the rail's toggle above the mode's, or C) set the ruled sheets and Today's notes 28px a row rather than 36px, the text its size: 3px above a 20px line, 4px below; the toggle's three lines close up while it is on, its label the state (Roomy, Compact).
On Today two panel icons at the day header's right fold the side columns away, the middle taking their room, and back: the left (Alt+P), and the right (Ctrl+\).

## Components

**List cards.** The sections of a project's page and the task lists (a project's Tasks, Plan) are glass cards, as Today's panes are.
A title row sits on a stronger hairline, and rows below are full-bleed, dividing with hairlines and lighting on hover with `--glass-row-hover`.

**Task rows.** An 18px checkbox with a 6px radius fills with ink when checked; there is no draw-in animation.
Every empty box (rows, sub-tasks, the description editor) is drawn in `--steel`, not `--mist`: mist falls under the 3:1 a control needs against the cards, in both modes.
The box the user has just ticked plays the system's `--check-pulse` once (in Neon Signage, a ring of spark light that fades in 640ms); `tasks.js` marks the fresh row `.just-done` for it.
The title is 14px/500 ink, and the meta line is 12px pewter.
A do-date off Today is graphite.
"Due soon" is a warn badge.
The meta line sits 4px under the title, so the description disclosure can take a full 24px target (WCAG 2.5.8) without touching the title's.
Claude's statuses are badges too: Queued neutral, Running ok (with a static dot), Needs review warn, Blocked err.
A task with a description adds a pewter disclosure to the start of its meta line: a chevron and the sub-task count ("1/3"), or "Notes" when it has none.
Opened, the description sits under the meta line in 14px graphite: context lines as written, sub-tasks as 14px ink checkboxes that fill like the row's own, a done sub-task pewter with a strikethrough, and bullets as a graphite dot in the box's place.
An indented line under a sub-task is its note, hung 22px in so it aligns with the sub-task's words.
Which descriptions are open is remembered per tab (`sessionStorage` key `pc-open-notes`), so Today's live refreshes never fold them shut.
A small trash bin ends each row, steel and hidden until the row is hovered or focused (always shown on touch), and err-tinted on hover.
It, and the task sheet's own bin, open the confirm dialog: opaque paper over the scrim with the modal shadow, titled "Delete task?".
The dialog restates the task's name in ink 600 and offers a Ghost Cancel (focused first) beside a destructive-secondary Delete, never a red primary.
It is the one handler behind every `hx-confirm` that carries `data-confirm-*` attributes (`shell.js`), so the browser's native confirm box never appears.
Each opening hears only its own answer: a dialog's close arrives a moment after it closes, and an Esc followed at once by another Delete must not hand the new question the old one's cancel.

**Task sheet.** Adding a task and editing one are the same sheet, written like a document rather than filled in like a form.
It is written on the line (see Inputs), shaped like the row it becomes: the row's box (or, to add, a plus in steel, ink once writing), then the title in 14px/500 ink, which wraps as a line of text.
The do-date, due, repeat, estimate and priority fields trail the title's last word as small icons in `--steel`, 14px, with the value beside the icon in 12px graphite once set ("tomorrow", "Fri 2 Oct", "1h 30m", "High"); repeat stays an icon, its rule in the tooltip.
The estimate's icon is a stopwatch; its menu offers 15m to 4h, the current length ticked, and No estimate.
A task's estimate shows on its row's meta line in 12px graphite figures.
The priority's icon is three rising bars (`partials/priority.html`, drawn by `.priority-icon` from its `data-priority`): low fills the first in graphite, medium two, high all three, the rest in mist; urgent is a 14px `--err-fg` square with a paper "!", the only colour, and the bars all steel mean none.
Its menu lists Urgent, High, Medium and Low, each after its icon with its P1 to P4 in pewter, then No priority.
A task's priority shows on its row's meta line, first, as its icon and its word in 12px graphite ("Urgent"), the word on hover too.
The gaps before and between them are the line's own spaces, widened, so when they wrap they start flush with the title's text.
Each is a 24px target that opens a small menu on paper with the dropdown shadow: Today, Tomorrow, Next week, Pick a date (the native picker) and No date; or the repeat presets.
The current choice is 600 with a tick, and choosing hands the caret back to where it was.
Writing sets them too: "today", "tomorrow", a weekday's name or "next week" followed by a space becomes the do-date, "due friday" the due date, "every day", "every weekday", "every week" or "every month" the repeat, "45m", "1h", "1.5h", "1h30" or "2 hours" the estimate (a bare number stays a word), and "p1" to "p4" the priority, urgent to low.
A task has no time of its own, so "at 3pm" stays words; in an event's title (the calendar's composer) "at 3", "3pm", "15:30" or "9-10:30am" is its time, an hour when no end is given.
The words leave the title as they convert, and Backspace straight after puts them back as words, which then stay words.
The description follows under the title, aligned with its text.
Editing adds an end line under the description: the project (its flag, filled in the project's colour with the project and workstream named on hover; an outline and "No project" when there is none; one menu of open projects, each after its flag, with their open workstreams indented), a person icon that names Claude when the task is Claude's, its status once it is Claude's or beyond the box, History, and the bin.
History opens under the end line, above a hairline: each change newest first, a 12px pewter line of when and who ("Today 14:02 · Claude"), then a 12px graphite line per field that moved ("Do date: tomorrow → Fri 2 Oct", "Ticked “oil”", "Description edited").
Project and workstream live only there and in the capture window, since the list a task is written in already says which project it belongs to; in either, "#" and a few letters of a name in the title file it too (see Capture window).

To add, each list card ends in the sheet's plus and a pewter placeholder, filed by the card it sits in (a workstream's is in that workstream).
Typing a title opens the icons and the description (focus alone does not, so a composer that folds away never shifts the page under a click), and a line under them: a pewter "Ctrl+Enter to add" hint (hidden on touch), then Cancel in 12px graphite and "Add task" in 12px/600 ink, words on the line with the fog under them on hover, not boxes.
Enter in the title moves to the description, and Ctrl+Enter adds the task and returns to an empty title for the next one.
A task dated away from the list it was written in does not join it; the page regroups instead.

To edit, the row's title swaps the sheet in place, on the row hover fill with its rules above and below in ink (as the notes' task the caret is in), with the caret at the end of the title.
There is no Save: the sheet saves when focus leaves it (a click elsewhere, Tab past its last control, Esc or Ctrl+Enter), and if nothing changed it goes back to its row without a save.
Tab past its last control leaves it even where nothing on the page follows to take the focus; the window losing focus does not.

**Description editor.** One line per block, in 14px graphite.
A line typed as "- [ ] words" is a sub-task (Ctrl+L makes one of any line): a 14px box that fills ink when clicked, with the words in ink, or pewter and struck through once ticked; "- words" is a bullet.
Enter on a sub-task (or a bullet) starts the next one, Enter on an empty one steps out of the list, and Backspace at its start turns it back into plain text.
Shift+Enter under a sub-task writes a note hung 22px in, under its words; Enter on a note starts the next sub-task.
Tab and Shift+Tab nest and un-nest by 22px, at most one level under the line above; where Tab cannot nest it moves focus on, so the keyboard never gets stuck in a description.
Pasted "- [ ] " lines arrive as sub-tasks and "- " lines as bullets; the editor keeps its own undo.
Esc steps away but keeps a written draft open; Cancel clears it.
The empty-list note hides once the list has a row.

**Today's panes.** Today, and every day's page (`/day/2026-09-25`), is a header over panes (Oscar's call, 2026-10-20, replacing the notes stacked over strips) in three columns: the left 340px, the middle the rest, the right 300px.
As the code lists them, the plan over the habits at the left, the notes in the middle, the timeline at the right; Oscar arranges them as he likes (his call, 2026-10-20), kept as the `today` setting in the database (`app/services/today_layout.py`), so it holds on every device and every day's page.
Each pane is a glass card under a 44px title bar: its name in 14px/600 ink at the left, its controls at the right, over a stronger hairline.
On hover or focus, the bar shows the pane's grip in its left edge (14px wide, six steel dots as a Gantt row's grip, ink on hover; in focus the spark tint behind dots in `--spark-deep`) and, right after its name, its eye (14px, `--steel`, in a 24px target), as the sidebar's eye hides a page; both sit in room the bar leaves empty, so the bar at rest is as it was.
A press on the bar (not on its controls) that moves 5px picks the pane up: it goes 40% faint where it was, its name follows the pointer on `--paper` with `--shadow-dropdown`, and a 2px spark line (glowing at night) across the column marks where it would land, before the first pane whose middle is under the pointer; landing where it is, there is no line.
A column not showing gets a 96px drop zone at its place while a pane is in hand, the edge the column would take (the middle's between the two sides), `--spark-tint` at 70% inside a 1.5px dashed spark edge, "A column here" in 12px `--spark-deep`, the tint full while the pointer is in it.
The panes slide to their new places (160ms); Esc puts the pane back; the drop is never a click (the habits' bar does not fold).
With its grip in focus, the arrow keys move the pane up or down its column or into the column beside it, at the same place; Delete hides it.
The eye hides its pane, the toast saying where it comes back ("Habits hidden. Panes, at the day's header, shows it again.") with Undo; a hidden pane keeps its place.
A column with no pane showing goes, its room the middle's; with nothing in the middle, the columns left share the width.
Wide enough for the three (the middle at least 440px between them), the page is as tall as the window (at least 560px) and each pane scrolls inside itself; the notes and the timeline take what their column leaves (at least 360px and 280px), the plan its rows' height, scrolling inside itself when its column is short, and a column with more than the window holds scrolls.
Narrower, the right column goes under the middle one and the page scrolls, the left column staying in view (sticky, unless the notes are in it); and once the middle would be under 405px beside the left, everything goes under one another: the middle, the left, the right.
The widths are the page's own (container queries), so the agent window docked takes from them as a narrow window does.
The header is the day's name at 24px ("Today" on today's), a pair of 32px chevrons for the day before and after, on any other day a pill back to Today, and the date in 14px graphite; then the day's facts, and at the right the two columns' folds' panel icons, graphite, pewter while their column is folded, named for the panes in it ("Fold Plan and Habits away") and gone while it has none; and Panes, a grid of three panels in the same 32px button.
Panes opens a menu on the page's paper: each pane in the code's order, ticked (and at 600) while shown, a click showing or hiding it in its place with the menu kept open; then, under a hairline, "Set them back as they were", which puts every pane where the code lists it, shown and unfolded, the toast offering Undo.
The facts are chips on a wrapping line, beside the name on a wide page and under it on a narrower one: each 28px, an 8px inset, a hairline edge on the glass, 6px apart.
What is on now and next comes first, a chip each, edged in the signal's cyan: "Now, till 19:40" or "Next, in 25m" in `--signal-deep` at 500 (cyan is time), the title in 14px ink at 500 (cut with an ellipsis at 32ch), its times in 12px graphite tabular figures, and a meeting's "Join on zoom.us" as a small edged button.
Then the body's figures (Readiness, Sleep, Body battery), each a 12px pewter name before its value in 14px ink at 500 (tabular) and a 12px graphite note ("high", "score 87"); lengths are written as the task fields write them ("7h 31m").
A low readiness sits in the warn badge, value and note ("31 low, keep the day light"), as an overrun day's load does.
The notes' pane is titled Notes, with Live, Source and Reading at its right; its card is the paper at 35% (see-through, as every input), filling the pane (at least 420px; 55vh once everything stacks), holding the notes ruled like a spreadsheet, written in 14px: the body grey (`--ink` 55% into `--graphite`, darker than the Task label), a task's first line in ink.
Under it, the key line names - [ ], /reflection, /stay, Ctrl+Enter, the arrows and "? all keys".
Every row is 36px tall with its text in the middle (7px above a 22px line, 6px below), on its own `--hairline` rule from the box's very top, and a 44px column of row numbers (12px pewter, tabular) runs down the left on a fog wash behind a hairline, like a spreadsheet's row headers (34px on phones); empty numbered rows fill the card under the last, the last of them cut at its edge, so a short page never scrolls.
A row too long for the box wraps inside it, its lines 22px apart, and the row grows, its number level with its first line; nothing scrolls sideways.
Plain rows start right after the numbers; a task's rows start one indent in, 76px (70px on phones), their wrapped lines too: in a task row's indent the page draws the task's box (square, 14px, graphite-ruled, ink with a paper tick once done) and "Task" in 12px graphite (struck through in pewter once done), neither of them text nor editable, and its other rows' indent is empty.
Every task is bracketed by a 2px graphite rule above its title and below its last row, across the row numbers too, always; the task the caret is in has its rules and row numbers in ink, as has the caret's row.
A task's "- [ ] " rows are its sub-tasks, each with the task box inline before its words; a ticked sub-task, and a ticked task (title and every row), is crossed out in pewter, its box, "Task" and icons not struck.
A task (or reflection, stay) right under another shares that one's rule, one line between them: it draws none above itself, and the shared rule takes its colour while the caret is in it.
A task with rows under its title has a 12px pewter chevron after "Task" (ink on hover; pointing down when open, right when folded): folded, the task shows its title alone, its hidden rows counted in a pewter caption tag after it ("2 rows") and its row numbers skipping them, and it stays folded with the notes.
At the right of a task's title come its controls, 12px or more after its last word: the task sheet's icons (do date, due, repeat, estimate, priority, project), each a pewter icon with its value beside it once set, in graphite, and last the rows' trash bin (steel, red on hover).
They stand on the title's last line when they fit there, and when not, on a line of their own under it, still at the right: the row grows by a line, and no row is added to the notes.
On a line too narrow for them all (a phone) they wrap whole onto a further line, never breaking a value's word.
A reflection is drawn as a task's rows are, without a box or controls: "Reflection" in 12px `--signal-deep` in its first row's indent, its words in the body grey, and its rules light blue (`--signal` 45% into the paper; the signal itself while the caret is in it).
A stay is drawn as a reflection is, in amber (`--hue-3`: 45% into the paper for its rules, the amber itself while the caret is in it, 85% into ink for "Stay"): each item row its box (the task box, inline, 8px before the words) and its name up to its colon in graphite at 500, amber while unsorted.
A task in a project has its rules in the project's colour, 55% into the paper (the colour itself while the caret is in it; the rule it shares with the task above takes the upper task's colour, and the lower's while the caret is in the lower), and its project control is the flag alone, filled in that colour.
Light blue for reflection, amber for stays and the projects' colours are the only colours in the notes that are not ink or grey.
Among the facts, a day with a stay is one chip, edged amber while an item is unsorted, its items side by side 12px apart: a 10px box (ink once sorted, amber-ruled until), the name in pewter caption, the value in 14px ink at 500 (amber while unsorted, "not sorted" when it has none); each is a button to its row.

**The plan.** The left pane, titled Plan, with Bring all at its right (12px graphite, underlined in mist; shown with two tasks or more to bring), holds what the day asks for in groups, each folding under its name and count on a 32px band of fog (12px/500 graphite, the count pewter), its rows full-bleed between hairlines.
Nudges first (today's page only): each its icon, its words wrapping in 14px ink, a small edged Open, and the steel dismiss.
Then the day's tasks not yet written in the notes: under the day's label ("For today"), those planned for it or due on it; under Carried over, those meant for a day before (overdue, or left open on the last page), with Reschedule on the band's right while it is open.
A task's row, 36px: its box (14px, steel, ink on hover, in a 24px target), its project's 10px flag in the project's colour and its priority's bars when it has them, its title in 14px ink at 500 (cut with an ellipsis, underlined on hover), when it was meant for in 12px ("due today" in `--warn-fg` at 500; under Carried over its due in graphite, or "from Mon 19 Oct" in pewter), and a 14px steel calendar shown while the row is hovered or focused (always on touch).
The title writes the task's rows at the notes' end and moves its do-date to the day; the box does that and ticks it; the calendar, and Reschedule for every task carried over, open a menu of days, drawn as the task sheet's: Tomorrow and Next week with the day in pewter at the right, Pick a date (the native picker) and No date.
A task moved leaves the plan, and the toast says where, with Undo.
With nothing in it, the plan says so in 12px pewter ("Nothing planned for today.").

**The habits.** Under the plan, a pane titled Habits, its count of those done on the day it shows ("1/4") in pewter, after it that day's name in 12px ink at 500 when it is not the page's ("Sun 18 Oct"), and over its rows' weeks the seven days' initials in 9px pewter, the picked day's in ink at 700; it folds to its title bar.
Each habit due that day, and each ticked on it, is a 36px row: its box (14px, ruled in the habits' green, filled green with a paper tick once done, pewter-ruled when skipped), its name in 14px ink at 500 (pewter when skipped; green on hover and while its comment is open) with, when the day has a comment, a 14px speech bubble after it (tinted green, ruled `--hue-4` 85% into ink), its last seven days as 9px squares 3px apart (done filled green, skipped green-ruled, missed steel-ruled, nothing mist, the page's day ruled in ink until it is ticked, the picked day ringed in a 1px ink outline 1px out; each a target the row's height), its streak in 12px graphite figures ("7d", the days done in a row, a day not its own passed over), and its days' icon.
The box ticks or unticks the habit for the day shown; a square picks its day for the whole pane; the name opens the comment's drawer under the row: a textarea from the name's left edge to the row's right less 12px, 14px ink on a 1px green line (`--hue-4` 55% into the paper; 2px ink while it is written), growing with what is written, its placeholder "A comment on today: how it went, or why not" in pewter; under it at the right, "Its page and log ›" in 12px graphite, underlined in mist.
The row with its drawer open keeps the hover's glass.
Under the rows, the pane's 36px foot: "+ New habit" in 12px graphite at 500 (a fog under it on hover), which becomes its name's line (14px ink on a 2px ink line, the pewter placeholder "Its name, as morning-skin-care"), and All habits at the right, 12px graphite underlined in mist.
With habits but none due, the pane says "None due this day."; with none at all, "No habits yet. Start one below: it is ticked here, day by day."
What is offered while writing (after "/" at a row's start) is drawn as the icons' menus are: the paper, a hairline, the dropdown shadow, 32px rows, the matched letters in 600 and a pewter caption beside a command.
No border, no focus ring and no resize handle; the pewter placeholder "Anything on your mind today."
When the notes were saved in another window, a line under the card says so, with Show that version and Keep mine as secondary buttons.

**Projects** (`/projects`; an overview since Oscar's call on 2026-10-04, the notepad gone from it).
A page header ("Projects", "4 active · 37 tasks open · 32 without a day", and at its right a new project's name on its line, 200px, with a quiet Add), then what needs attention, then the timeline, then the paused and done projects.
It is as wide as the window allows, up to 1600px, so a wider window widens the weeks.
It lists no tasks: a project's are planned on its Tasks tab, and those without a day on Plan.
It is drawn again whenever a task or a project changes, its counts with it.

**Needs attention.** A glass list card, "Needs attention" with its count, of what asks for Oscar now: open tasks overdue or due within three days, the soonest first, then Claude's work waiting for review; none of a project paused or done.
Each is a 40px row: its badge in a 112px column (err "Overdue", warn "Due soon", warn "Needs review"), its title in 14px/500 ink (opening its page, cut with an ellipsis), its project as a 12px flag and its name in 12px graphite ("No project" in pewter), and its day at the right in 12px graphite tabular figures.
Its last row counts the open tasks without a day after a neutral "No day" badge, with "Plan them ›" in 12px/500 ink at the right, opening Plan.
With nothing to say, the card is not drawn.
Narrower than 640px, a row's project goes under its title.

**The timeline.** A glass card: a row a project, its progress, and its span over sixteen weeks from last week's Monday, ruled a week a column in hairlines.
Its head row names the columns in 12px/500 graphite (Project, Progress) and each week by its Monday's day in 12px pewter tabular figures, a month's name before it in 600 graphite on the month's first week (and on the first column).
Each active project is a group, in Projects' order, a stronger hairline between two.
Its row, 48px, is a chevron that folds its workstreams away (12px steel, ink on hover; an empty slot where there are none), its flag, its name in 14px/600 ink (opening its page, underlined on hover, cut with an ellipsis), its health badge at the column's right (err "1 overdue", warn "Due soon", ok "On track", neutral "No deadline" or "Nothing open"), then "69%" in 14px/600 ink before "20/29" in 12px graphite tabular figures.
Over the weeks its span (its tasks' first start to their last due) is a 12px bar drawn as the Gantt's are, a tube of `--solid-edge` (deep indigo by day, white at night with its glow), its done share filled solid from the left.
Each open deadline is a 7px diamond under the bar, outlined in ink and filled once it has passed, the task and its day in its tooltip; and now is the signal, 2px, down every row, glowing at night.
A project with no dates says "No dates yet" in 12px pewter at the weeks' start.
Under it, each workstream with work open is a 36px row: its name in 14px graphite one step in (opening the project's Tasks at that workstream), its "1/2" under Progress, and its own span an 8px bar of the same kind.
The workstreams marked done, or with every task done, are counted on a last row ("✓ 2 finished", 12px pewter).
A project folded is its row alone; the fold is kept on the project (`folded`, saved as it is clicked, `tasks.js`), and Alt+click folds or unfolds every project.
Narrower than 720px (container queries, so the sidebar counts) the weeks go, and under 420px the badges.
With no active project, the card says so.

The paused and done projects follow, a line each: "Paused" or "Done" in 12px/500 pewter in a 64px column, then each project as a 28px glass chip, its 12px flag and its name in 12px/500 graphite (ink on hover), opening its page.

**Task lists** (a project's Tasks, and Plan).
Not ruled sheets (Oscar's call, 2026-10-04): glass list cards, a list each, 16px apart, their rows full-bleed between hairlines.
A row is the task row (see Task rows), without its project's flag, since its list names the project; a meta line that would hold the flag alone is not drawn.
Every row names its do-date, "today" included.
Each row ends in quiet do-date buttons, always shown since dating is these lists' job: "Today" and "Tomorrow" in 12px pewter, and a calendar icon that opens the native date picker.
They darken to graphite on row hover and ink on their own hover; a button for the day the task already has leaves its slot empty, so the columns line up down the page.
On phones they take their own line under the title's text, without empty slots.
Dating a task redraws the list from the server, which draws itself again whenever a task or a project changes.
A task files by drag: onto a workstream's card, into that workstream; onto another project's list, into that project with no workstream; onto No project, out of any.
The row in hand fades to 40%, and the list under it lights as a drop target, `--spark-tint` with an inset 1.5px spark ring.
The lists work from the keyboard alone (each page marks its lists' area `data-cursor`).
A 12px pewter line under the header (and Today's) names the page's first keys and ends in "? all keys" (hidden on touch and phones); the focused row is the cursor, drawn as the nav's own marker, a 3px spark bar inset on its left edge with the spark glow, over the row hover fill.
The bar shows for keyboard focus only (`:focus-visible`), never after a click.
It is the one cursor the app draws: Done's header and the item under the keyboard in a task sheet's menu take the same bar (on `--fog` in the menu, which is opaque paper).

**Plan** (`/plan`, from Needs attention's "Plan them ›"; `/backlog` goes there too).
Every open task of Oscar's without a day, for giving them days, at a list page's 800px: a pewter "‹ Projects" over "Plan", the count ("32 open tasks without a day") and the key line.
Then a list card a list: No project first, ending in the page's composer ("Add a task…"), then each project's in Projects' order, its title its flag and its name (opening its Tasks) with its count.
A task given a day leaves the page.

**Me** (Health).
A page header, then one ruled sheet that runs to the window's foot (at least 420px): the notepad card's paper at 35%, every row at least 36px tall with its text in the middle (7px above a 22px line, 6px below) on its own `--hairline` rule, numbered down a 44px column (12px pewter, tabular) on a fog wash behind a hairline, empty numbered rows filling it under the last, the last of them cut at its edge.
Each part is a group, bracketed as a notepad task is: a 2px graphite rule above its title row and below its last row, one rule between two groups, in ink while the keyboard is in it.
The parts: At a glance (Weight, Age, BMI and Daily energy, read-only in ink at 500, "Not yet" in pewter, then a graphite row saying how the energy is estimated), Weight, Body, Activity and goal, Diet, and Health notes.
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

**The agent window** (`partials/agent_panel.html`, in `base.html`, beside every page).
A chat with Claude or Codex, the first pane of the sidebar at the right (`.side`), expanded or collapsed by the sidebar's Agent, its own Collapse or A, remembered as `pc-agent` and applied before paint.
A page with panes of its own (a task's) adds them to the sidebar, one shown at a time, with a 44px strip of their 32px steel icons down the sidebar's left edge, the agent window's sparkle last (Oscar's call on 2026-10-11, so the chat and a task's work share the right instead of fighting for it).
On a window 1100px or wider the strip stays when the panes collapse, the column 44px; an icon shows its pane (the sidebar opening on it), and the shown pane's icon, in ink on the glass hover with the sidebar's spark at its edge, collapses them; Up and Down step through the icons.
The pane last shown is remembered (`pc-side-pane`); A and the sidebar's Agent show the chat.
Expanded on a window 1100px or wider it docks as the shell's third column, 400px, the sidebar's matte flank mirrored (`--chrome-flank`, its edge a flank border on its left), the column opening and closing over the sidebar's 220ms; its parts keep their width as the column moves, so it slides rather than reflows, and the page's own column narrows beside it.
Narrower, it floats over the page's right edge instead, 400px of opaque paper with the dropdown shadow, sliding in over the same 220ms; on a phone it takes the whole screen, over the tab bar.
Collapsed it is hidden and inert, out of the tab order.
Its head sits on the sidebar's head line: the agent, a select drawn as the card's title (16px/600 ink, a steel chevron, the glass hover under it, as wide as its name), its model under it in 12px pewter, as Models names it ("Claude Sonnet 5.5 · High", "Default · Claude Opus 5.5"), a link to Models, where it is chosen (graphite and underlined on hover), then New chat (a pencil on a page) and Collapse (the sidebar's collapse control mirrored), 32px steel icons, ink on the glass hover.
In the list an agent not here is named with why ("Codex · Not installed").
Under a flank border, the latest chat, drawn as Nutrition's (rows divided by flank borders, "You" and the agent's name, the answer as Markdown), its empty line saying what the agent can and cannot see; then the composer, as a chat card's.
An agent that is not here (not installed, not signed in) says so in place of the chat's first words: a warn badge ("Not installed", "Not signed in", "Needs attention") and why, in 14px graphite, its commands as code, then "Open Models", underlined; its composer is closed, the placeholder in mist ("Codex is not here yet").

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
On a project's Tasks it is the last card, noting "last 14 days".
Which folds are open is remembered per tab (`sessionStorage` key `pc-open-folds`).

**Keys dialog.** `?` on any page opens every key, grouped by where it works, on the confirm dialog's paper, 760px wide in two columns (one under 640px).
It is drawn from `keys.py`: each action with its keys as they are now, among the keys that stay as they are, and an action with no key is left out.
Each column is one grid, so all its descriptions start on one line; keys are 12px graphite in hairline boxes.
A 12px pewter foot links Keyboard.
The dialog takes focus itself, so no control opens ringed; Esc closes it.

**Keyboard** (`keys.html`, `keys-page.js`). A page as the Changelog is: its heading, a line saying where the keys are kept, and a find field on its line at the right, as Repositories' is; then a list card per scope, an action a 48px row.
A row is its name in ink with its id under it in 12px pewter, its keys at the right as the keys dialog draws them, each with a pewter ×, and a dashed + after them; then, at the far right, Default (a quiet button) for an action chosen over its defaults, or "No key".
Recording, the + says "Press a key…" in spark, as focus is, in a solid spark box, and no other key does anything until one is pressed or Esc lets it go.
Two actions of one scope on one key each say so under their row, after a warn badge, "Clash".
The keys that stay as they are are rows too, all in pewter, saying "Stays".
On a phone the keys go under the name.

**Command menu** (`app/static/command.js`, Ctrl+K). The capture window's paper, 640px wide and 12vh from the top over the scrim: a 16px line to write on, ruled off from what it finds, then the results grouped under 12px/600 pewter names (Days, Pages, Do, Tasks, Projects, Events, Notes), at most 70% of the window tall, and a foot of keys.
A result is a 36px row: its name in 14px/500 ink (a done task or cancelled meeting pewter and struck through, a project after an 8px square of its colour) and its detail at the right in 12px pewter figures (a do-date or due, a meeting's day and time, a page's or action's key in a hairline box); a day's notes give the words found the row's room.
The row Enter opens is in fog, and follows the pointer.
**Capture window (New task).** The sidebar's New task opens it on every page, and so do N and Shift+N, except on a task list (a project's Tasks, Plan), where they write into the page's own list.
It holds the task sheet (600px, 15vh from the top, on the confirm dialog's paper), its foot shown from the start: where the task goes, then the hint and the sheet's Cancel and "Add task", on one line where a long Project › Workstream gives way to an ellipsis (its full name on hover).
On a phone the hint goes, and where the task goes takes a line of its own, Cancel and "Add task" under it at the right.
Where it goes is a chip named in full, "No project", "Note-app" or "Note-app › Design" in 12px/500 (graphite for none, ink once filed), after the project's flag in its colour and before a steel chevron; on a project's pages (its page, its Gantt, a document) it starts in that project.
The chip opens the project menu with a line to find one on at its top, written on the line (a hairline that turns ink while it has the caret); a few letters of each name narrow it ("home kit" leaves Home and its Kitchen), a workstream shown under its project, and a name found nowhere says so in pewter.
The arrows move the active item, drawn as the keyboard's (the fog and the spark bar), and Enter takes it, the menu as wide as its widest name whatever it is narrowed to.
The hint reads "# project · Ctrl+Enter to add": a "#" starting a word in the title drops the same menu down from the "#" itself, without its line, narrowed by the words typed after it while the title keeps the caret; Enter or Tab takes the active item, and the "#" and its words leave the title, Backspace straight after putting them back, as for any field.
Words no name matches ("#42") close it and stay words; Esc closes the menu and leaves the window open.
It stays open for the next task, filed where the last one went, and a toast says where each one went (its project, "Added “Call the plumber” to Home › Kitchen", else its day, "for Fri 2 Oct" or "to No date"), with Open for the task's page, since no list on the page shows it; over the window the toast is in it, so Open can be reached.
Esc closes it and keeps a half-written draft for the next time; opened again empty, it starts afresh.
The sheet's menus open inside the window, over its backdrop.

**Buttons.** `.btn.primary` is the spark primary, glowing at night, `.btn.quiet` the glass secondary, `.btn.danger-quiet` the destructive secondary with an err border.
Week navigation and nudge actions are secondary-style controls.

**Inputs: written on the line, as Today's notes are** (Oscar's call, 2026-09-30, replacing the settei plates of 2026-09-27).
Every place Oscar writes is a line of the notebook: no box, no fill and no focus ring, the words straight on a rule, 22px of 14px ink on a 36px line as the notes' rows are, pewter placeholders, date and time in `--font-num`, a select's words followed by a small steel chevron, and an empty date in pewter.
On a ruled sheet (Me, Garmin, Finances) the rows are the lines: a field is a row, its name in the row's indent in 12px/500 graphite, and the field in use has its row number in ink 600 and its group's rules in ink, as the notes' caret row does.
Elsewhere (the event and new-project forms, a project's Details) a field is its name in 12px/500 graphite over a 1px steel line (3:1 as a field's edge), the line 2px ink and the name ink while it is in use.
Their buttons are the app's own, 36px beside a form's fields; the task sheet's are words on its line (see Task sheet).
Focus elsewhere in the app is unchanged: every other focus ring is `--spark-deep`, not `--spark`, since accent text holds 4.5:1 on every surface where the bright spark can sink into a glow of its own colour.

**Time grid** (Calendar's day, three days and week, and Today's one-day timeline, one partial).
The page title names the days shown ("Friday 2 October 2026", "2–4 October 2026", "28 Sep – 4 Oct 2026"), and the header's Day, 3 days and Week is Brasa's segmented control (a pill track, the active option `--carbon` with `--on-carbon` text, deep violet at night, never the spark's pink); on a phone its options take 10px sides so it fits beside the steps.
After the title, its ISO weeks in 16px/500 pewter figures ("W40", "W40–41"); after the steps, a calendar icon in the arrows' box, the native date picker unseen over it.
On a phone the view switch takes a row of its own, its three options sharing it, and the steps and the icon follow on the next.
New event, a quiet "+" line as Add a workstream is, starts the tools row under the title, Sync work at its right.
The grid runs the whole day, 48px an hour, in a card that scrolls within the window; the day heads and all-day events stay on paper at its top as the hours pass under them.
Day heads are 12px pewter over a 14px/600 number, with today in `--spark-deep`, glowing at night.
Under the number, a day to come carries its load in 12px figures: "45m planned" in graphite over "3h free" in pewter, one to a line; when the planned is more than the free, both sit in the warn badge.
Today's timeline, which has no heads, carries the same on one line ("45m planned · 3h free") above its hours.
Today's timeline is a pane titled Timeline, the hours in what its title bar leaves; under the notes, on a narrower page, the hours scroll in 75% of the window.
Weekend columns carry `--ink-tint-faint`, whichever days are shown.
Items are square tags with a 2px gap below, so back-to-back items never merge:

- work meetings are a quiet ink tint in graphite;
- personal events are glass with a hairline;
- a cancelled meeting is a hairline outline, its title pewter and struck through;
- a drag preview, and the time being written in the composer, is `--spark-tint` with a dashed spark edge.

Items starting within half an hour of each other share the column in lanes; one starting later is laid over the items still running, 14px further in for each step (three at most), opaque and ringed in 1px of paper, so neither blurs into the other.
Titles wrap between words over the lines an item's height allows, stopping above any item laid over it; a word too long for its lane is cut, never broken.
A five-minute meeting is still drawn 20px tall, and laid out as drawn.
The grid's one light is the now-line in `--signal` (cyan in Neon Signage, glowing at night), whose time is written in `--signal-deep` in the gutter.
An hour label whose digits the time would overlap (centres within 12px) is hidden, so the gutter never shows a clipped "06:00" behind "06:21".

**Projects' colours.** A project is one of the eight hues (`--hue-1` to `--hue-8`), shown wherever its tasks are as its flag: a 14px flag filled in the colour, the name said on hover and to a screen reader, never written beside it (task rows, the task sheet, the notes).
On Calendar's sheet a task in a project is a band of its colour instead, edged in the colour itself (see Calendar's sheet).
A new project takes the hue fewest open projects have; a project's Details offer the eight flags in a row, the chosen one ringed in its colour.

**A project's page** (`project.html`, `/projects/<id>`, 1040px wide).
Not a ruled sheet (Oscar's call, 2026-10-04): an overview in sections, a glass card each, as a modern product's project page is.
Its header is shared with its Tasks and its Gantt: a pewter "‹ Projects", the project's flag (20px) and name at 24px, then a line of graphite words ("Active · 14 tasks open · 2 repositories · 1 document", the repositories left out while there are none), then its tabs, Overview, Tasks and Gantt.
A tab is 14px/500 graphite (ink on hover), 24px apart; the current one is ink 600 on the nav's 3px spark bar, laid flat under its words, glowing at night.

Under it, the project at a glance: four glass tiles in a row, 12px apart, each its name in 12px/500 graphite, its value at 20px/600 ink on a 28px line, and a 12px pewter note along the tile's foot, so the four notes share a line.
Health is the timeline's badge ("On track", "Due soon", "1 overdue", "Paused"…), its note the open count; Progress the share done, a 4px meter in ink over the hairline, and "20 of 29 tasks done"; Next due the nearest open deadline's day, its note the task's title, cut with an ellipsis; Timeline the tasks' first start to their last due ("5 Oct to 23 Oct", each day kept on one line), its note how long that is.
With nothing to show the value is in pewter ("None", "No dates yet") and the note says why.
The glance is drawn again, out of band, whenever the project is saved, since its status changes its health.

Then two columns, 24px apart: the main one, and Details, 300px, at the right, kept in view as the page scrolls.
Each section is a list card: its title in 16px/600 on a stronger hairline, a pewter count or note after it, its rows full-bleed with hairlines between and `--glass-row-hover` under the pointer.

- Description: the project's notes written straight on the card, 14px ink on 22px lines, at least three lines tall and growing with the text; the card's edge goes ink while it is written in.
- Context, with "What an agent working on it reads, AGENTS.md first" after its title: a tree (`context-tree.js`), a row a document or a folder, AGENTS.md first.
  A document's row: its steel page icon on a 32px glass tile, then its name in 14px/500 ink (underlined on hover) over what it is about (its first words, heading marks gone) in 12px graphite, or in pewter what to write while it is empty, and at the right its length and when it was written ("12 lines · 11:48") in 12px pewter figures; the whole row opens it.
  A folder's row: a 12px steel chevron (turned down while open), the folder's icon on the tile (open while open), its name in 14px/500 ink, and at the right how many documents it holds however deep ("3 documents", "No documents" with only folders in it, "Empty"); the whole row folds it.
  Every row keeps the chevron's 12px column, so names line up level by level, each level 24px in, its rows under a hairline guide that drops from its folder's chevron; an empty folder's first row is a pewter "Nothing in it yet: add a document, or drag one here".
  On hover or focus a row's tools take its meta's place at the right, 28px steel icons going ink on `--glass-hover`: on a folder New document, New folder, Rename and the bin; on a document Rename and the bin (none on AGENTS.md); the bin goes `--err-fg` on `--err-bg` and opens the confirm dialog, a folder's naming what it takes with it ("and the 3 documents in it will be deleted").
  A new document or folder is named in a row of its own at the top of where it goes, and a rename over its row, on `--glass-row-hover`: the icon in ink, the name in 14px/500 ink on an ink line (spark while in focus), and at the right "Enter to add, Esc to cancel" in pewter with its keys boxed.
  A row in focus is ringed in 2px spark inside; a row dragged goes 40% faint, and the folder it would land in (or the whole tree, for the top) is lit as the task lists' drop targets are, `--spark-tint` inside a 1.5px spark edge, its contents on `--ink-tint-faint`; a folded folder held under it opens after 600ms.
  A row just made, renamed or moved glows `--spark-tint` once, fading out over 1.2s, and takes the focus.
- Repositories, with its count: a row each, its steel branch icon on the tile, its name (the last part of where it is) in 14px/500 ink over where it is in 12px graphite, written in place (a steel line under it on hover, ink while written), and at the row's end a bin as a weigh-in's, shown on hover.
- Details: Name, Status (a select) and Colour (the editor's eight flags as 28px swatches, the chosen one ringed in its colour), each a field as a form's: its name over its line.

Context and Repositories each end in a line to add one: a steel plus under the icons' column, then the name written on it, its placeholder in graphite (a document's name or path, or a repository's folder or URL); Enter adds it, and a new document opens on its own page.
Context's line has New folder at its right, behind a hairline: a steel folder-plus and the words in 14px graphite, both ink on hover, opening a folder's row at the tree's top.
Each card saves as it changes and posts only its own fields: Description the notes, Details the name, status and colour.
Under 760px of content the columns become one, Details last with its fields side by side; under 600px the glance goes two by two and a document's length and time go.

**A document's page** (`project_doc.html`, `/projects/<id>/docs/<doc>`, at a task page's 800px).
The task page's header: a pewter "‹ " and the project's name, and at the right a 12px pewter "Saved" once a save lands ("Not saved" and a toast if one fails), nothing while the writing is unsaved.
Then the name as the heading, 24px/600 display on 32px; any but AGENTS.md's is written in place, on no line, with the task page's bin at the right, which opens the confirm dialog ("Delete document?").
Under it, the project's flag and "Note-app's context · in decisions/adr · edited 11:48" in graphite; while the project has folders, any but AGENTS.md's folder is a select written in the line, its path in ink ("No folder" in graphite) before the notes' small steel chevron, on the fog under the pointer, and choosing one moves it.
Then the Markdown on a ruled sheet written as Today's notes are (CodeMirror, `doc-editor.js`): a row a line, numbered on the fog, a long line wrapping within its row, a heading's line ("# ", "## ") in 600; the empty rows under it, numbered on, run to the window's foot, and a click there writes at the end.
The page scrolls as the text grows, never the sheet; an empty document opens with the caret in it and its placeholder saying what to write.

**Habits** (`habits.html`, `/habits`, in the sidebar under Calendar, its icon a ring with a tick).
A page header ("Habits", and under it in graphite what they are and where they are ticked), then one ruled sheet: a group headed Habits and their count, its column names at the foot of the head in 12px/500 pewter (the four weeks' initials in 9px, Done, Streak).
A habit a row: its name in ink at 500 (green and underlined on hover, to its page), its days in 12px pewter, and on a line of its own the first line of what it is in graphite, cut with an ellipsis; then its last four weeks as 8px squares 2px apart, each Monday 4px further (drawn as the pane's days), how often it was done ("5/12" of its own days, or "5" when it has none; 44px, tabular), and its streak ("7d", 48px).
Under the group, a row to start one: its name on a field line (360px at most) and a quiet Start it; then the empty numbered rows to the sheet's foot.
Narrower, Done goes; on a phone, the four weeks too.

**A habit's page** (`habit.html`, `/habits/<name>`, as a document's page).
The header: a pewter "‹ Habits", at the right "Saved" and the Markdown's modes; then its name as the heading, written in place, with the bin at the right ("Delete habit?", which names what goes).
Under it in graphite, on one line: its days' repeat icon with their words ("Any day" when it has none), "· since Wed 30 Sep" and "· habits/morning-run.md".
Then its half year on the sheets' paper in a hairline card: at the left its figures, each a 12px pewter name over 14px ink at 500 (Streak, Last 30 days, Comments); at the right its weeks, a column of 11px squares 3px apart each, Monday at the top, the month's name in 9px pewter over the week it starts in and M, W, F down the left; drawn as the pane's days, a day with a comment carrying a dot (green, the paper's on a day done).
Then its words as a document's: what it is, then "## Log" and its entries, the newest first.

**A project's Tasks** (`project_tasks.html`, `/projects/<id>/tasks`, its second tab).
Where a project's tasks are planned: under the shared header and the key line, a list card a workstream, in the project's order.
A card's head is its workstream's row, over a stronger hairline: a steel circle that marks it done (ink on hover and once done), its name in 16px/600 ink, and its done count in 12px pewter; then its open tasks, then its composer, which files into it ("Add a task to Calls…").
Then "No workstream" (or "Tasks", when the project has none), its tasks in none and the project's composer.
A workstream marked done, or with every task done and none open, folds to a 12px line under the cards: "Finished" in pewter, then each its circle and its name in graphite, the circle marking it open again.
Then the project's Done fold, the last 14 days; and last, outside what is redrawn, so a name being written survives, the line to add a workstream (a plus, then "New workstream: a lane of the project's work"), as the context's line to add a document is.

**Gantt** (a project's third tab, `/projects/<id>/gantt`, as wide as Calendar).
A page header (a pewter "‹ Projects", the project's flag and name at 24px, the task counts and the plan's span, the project's tabs, the key line) with, at its right, the Weeks / Days segmented control and a quiet This week (or Today) button, then one sheet, ruled as Me's is (36px rows, 28px compact, the row numbers on the fog), that runs to the window's foot and scrolls both ways inside itself.
Its header row (48px) and its frozen pane stay put while it scrolls, as a spreadsheet's do: the numbers, a 32px box column, Task (280px, widened by dragging its header's edge, remembered as `pc-gantt-title`), Priority (96px: the priority's icon and its word in graphite), Start, the length (Wks or Days) and Due, on opaque paper edged by a mist line, while the time is the sheet's see-through paper.
Its time is a 52px column a week, or drilled down, a 36px column a day (Start then 112px, for its date).
Column names are 12px/500 graphite; a week's head is its ISO week in 12px/600 ink over its Monday's day in pewter (graphite, with the month, where the month turns); a day's is its initial in pewter and its date in ink (pewter at weekends), under its week's name and Monday ("W41 · 5 Oct") running across the week from its Monday; now's head is `--spark-deep`, glowing at night.
Cells carry hairline rules both ways, as a spreadsheet's; the time's columns are ruled by the table's background, so the empty numbered rows under the last are too, now's column (this week, or today) is tinted `--ink-tint-faint`, and in days so are weekends, each week's Monday ruled in mist.
A workstream's row is 600 with the task box (`--ok-fg` once done, as a task's), a 12px steel chevron before its name that folds it (turned right while folded, its tasks and add row gone, a pewter caption counting them after its name, its row numbers skipping them), and its Start, length and Due its tasks' in pewter (read-only); its tasks are one 24px step in; "Add a workstream…" heads the tasks in none; each group ends in a pewter "Add a task…" row after a steel plus.
Groups are bracketed by 2px graphite rules, in ink round the cursor's group, as on every sheet.
A task's bar is 20px of `--solid` (white tubes at night) from its start's day to its due's, in either scale (so a Monday-to-Friday week leaves its weekend), inset 2px and never under 4px, with 8px grips at its ends; done, it is the system's ok green (`--ok-fg` 30% into `--ok-bg`, on a 1.5px `--ok-fg` edge), its box `--ok-fg`, and its title pewter and struck through.
A task due with no start is a 2px, 20px ink tick on its due; a workstream's lane is a 6px graphite summary with 11px end ticks spanning its tasks (`--ok-fg` once done).
Due soon (three days) is a warn badge in Due.
The now-line is the signal, 2px, down through the weeks at today, glowing at night.
The cursor is a 2px `--spark-deep` ring on its cell (glowing at night), over any bar, with the row's number in ink 600 and its week's head on the fog; while the sheet does not have focus it is a 1px steel ring.
A range is `--spark-tint`; a bar being drawn is that tint edged top and bottom in the spark, as a calendar drag's preview.
A cell being written takes its words on its own line (500 ink, on the paper), the ring kept; a title or a name wraps, its row growing with the words (its number, box and dates centred in it), scrolled into sight as it grows.
A task's Task cell ends in a 14px steel trash bin, hidden until its row is hovered (always shown on touch) and err-tinted on hover, as Calendar's sheet's; it opens the same "Delete task?" dialog.
A task's row number is its grip (a steel six-dot mark beside it on hover): dragged, the row fades to 40%, a 2px spark line (glowing at night) marks where it would land, and the group it would land in takes `--spark-deep` rules.
On phones the Task column narrows to 150px and Priority, Start, Wks and Due fold away; the bars are still drawn and dragged.

**Calendar's sheet** (`partials/day_sheet.html`, Calendar's fourth view).
Under the calendar's header, a key line in place of New event, then one table that scrolls both ways inside itself to the window's foot (as the grid does), on the sheets' see-through paper under a mist line.
Its header row (48px, 12px/500 graphite names at the foot) and its Day column (128px: a fold chevron, the weekday in pewter, the date in ink 500, today's both `--spark-deep` 600) stay put on opaque paper, the Day column edged by a mist line.
The columns: a stay item's 176px (accommodation's, a checkbox, 120px), Plan the rest (320px at least), a habit's 84px, its name broken at its hyphens, a link to its page (ink and underlined on hover).
Rows are 36px (28px compact) and grow with their plan; cells carry hairline rules both ways, each week's Monday is ruled in mist, and weekends are tinted `--ink-tint-faint`.
A stay's cell is its value in ink; accommodation's is a centred 14px box, steel on a day with no stay, edged amber while its stay has it unsorted (as under Today's date), and ink with a paper tick once sorted.
A day that folds has a 12px steel chevron before its date (ink on hover, turned right while folded; the Day header's folds them all); folded, its plan is its first line, cut short with an ellipsis, then "+N" in 12px/500 pewter.
Plan lists the day's tasks, each a 14px box in steel (edged in `--hue-6` with a 6px `--hue-6` square inside while in progress; `--ok-fg` once done, its title pewter and struck through), a 10px steel chevron hugging it (ink on fog when hovered or open) whose menu is the sheet menu's, its priority's icon (a 14px slot kept empty without one, so the titles line up; the word on hover), and its title in ink, a link to its page underlined on hover, on its deadline's day, once that is past with the task still open, "overdue" after it in the warn badge (12px/500; a deadline to come, however soon, is not flagged); a task in a project sits on a band of its colour, 16% (7% once done), edged 2px in the colour (45% once done), 4px out into the cell's padding with a 1px gap between lines, the project named on hover; and then the day's own events, the time in 12px pewter figures before the title in graphite.
A task's line ends in a 14px steel trash bin at the cell's right, hidden until the line is hovered (always shown on touch) and err-tinted on hover, as the task lists' rows'; it opens the same "Delete task?" dialog.
A habit done fills its cell with `--hue-4` at 30%, the habits' green, with a 16px tick in it; skipped is a 10px steel box, missed a 10px steel dash, and the cell's tooltip says which, with the day's note.
A habit's cells being painted fill (or empty) as the drag passes, before the sheet is drawn again.
The cursor, the range and a cell being written are the Gantt's: a 2px `--spark-deep` ring (a 1px steel one while the sheet does not have focus), `--spark-tint`, the words 500 ink on the cell's line.

**The Changelog** (`changelog.html`, `/changelog`, from Settings, at a list page's 800px).
The page header says which version this is; under it a list card per version, newest first, 24px apart: its title row the version (with an ok "This version" badge on the running one, and "Unreleased" for changes not yet merged) and, at its right, its day in 12px pewter ("4 Oct 2026").
Each change is a row of a 64px column with its kind in 12px/500 graphite (Major, Feature, Fix), then its words in 14px ink, and what more it says under them in 14px graphite on 1.5 lines; a Major's kind and words are ink 600.

**Models** (`models.html`, `/models`, from Settings), a ruled sheet as Repositories' is, its fields' names 128px wide.
Each provider is a group: its title row its name in 14px/600 ink, its state's badge (ok "Signed in", warn "Not signed in", neutral "Not installed" or "Not checked yet", err "Needs attention") and, at its right, its CLI and version in 12px/500 pewter.
Then its account, where its CLI is, written on the line (its placeholder the command found on PATH, or "Where codex is"), and its models, a row each: the name in ink 500, a neutral "Default" badge on the provider's own pick, what it is for in graphite, and its id at the right in pewter code; or, in graphite, what to install or run to sign it in, its commands in ink code.
"Used for" follows, a row a use: its model and its effort as two selects on the line; then "Checked", when, and a quiet Check again.
In Settings, between Modules and Version, a row as Version's is: each provider's name in 500 and its badge, and "Set up ›" at its right.

**A task's page** (`task.html`, the task sheet in its page mode; Oscar's pick of the prototypes on 2026-10-11, kept on the branch `prototype/task-page-map`).
It takes the window's whole width: the map of its project down the left, a 272px column with a hairline at its right that scrolls on its own, and the task as a document over the rest, kept to 1040px and centred there.
A content column narrower than 820px (the sidebar open on a smaller window, a phone) keeps the document alone.
The map (`partials/task_map.html`): the project at its head (its flag in its colour, its name in 16px/600 ink, a way to its page), then "Context" and "Workstreams" as 12px/600 pewter headings.
Context is the project's documents as its page's tree has them, AGENTS.md first, folders folded behind a steel chevron; Workstreams each a row (chevron, a three-line steel icon, the name in 14px graphite, its open tasks' count in pewter at the right), folded but for the task's own, each unfolding to its open tasks in the Tasks tab's order and, folded under them, "N done", the last two weeks' finished ones.
A task's row is a 12px box drawn as its sheet's (in progress edged in blue and filled, in review in amber, blocked edged in red, done in ink with its tick) and its title on one line, Claude's with a steel robot after it; finished ones pewter, cancelled struck through.
The task itself is in 600 ink on the hover fill with the map's one spark, a 3px bar at its left edge, as the sidebar's current page has.
Rows are 28px, a level 16px in; folds are remembered (`pc-map-folds`), the task's own workstream always opening.
The task itself has what it holds under it, a level in: Description (a document icon, the document open when it is), then its files as a tree (folders open, behind their chevrons; files by name), and last a line to add one, a steel plus and "New file" in pewter, written on in place.
The document open, the description or a file, has the map's spark, the task's own row its 600 ink.
A task in no project has "No project" at the head and itself alone.
In the document: a header of a pewter "‹ Calendar" (where it was opened from) and, at its right, a 12px pewter "Saved" once a save lands ("Not saved" and a toast if one fails), nothing while the writing is unsaved, so the page stays still as it is written.
Then the sheet with no row around it: the 18px box beside the title, the title as the page's heading (24px/600 display, 32px lines, wrapping), and under it, aligned with the title's words, every field on one line as the sheet's end line draws them (the four field icons, project, owner, status once it applies, History, and the bin at the line's right), above a hairline.
History opens the sidebar's History pane.
The description follows 16px below at reading size, 16px on 1.6 lines in graphite, at least half the window tall and as long as it runs: the page scrolls, never the editor.
A new task opens with the caret in its empty description, whose placeholder asks for the context, the plan and what done looks like.
Its agent work, its outline and its history are panes of the sidebar at the right (see The agent window): Agent work (a robot), Outline (three lines) and History (a clock), above the agent window's sparkle.
Each pane's head is the agent window's: its name in 16px/600 ink, a 12px pewter line under it ("Claude's task, not launched yet", "Its description's headings", "How it changed, newest first") and Collapse.
Agent work, for Oscar's own task, says it is his and has Hand to an agent, which makes it Claude's (the sheet's owner, saved as its menu saves it); for Claude's, its work in the order the work goes, each field its name in 12px graphite over its value on a flank border: Brief (Repositories as toggles, Acceptance criteria written on the line), the primary Launch (dimmed while it cannot), its runs once there are any, Pull requests (a chip and `owner/name#number` each, its title under it, and a line to add one), Outcome once it ran, and Updates.
A file of the task's opens in the document's place, as a project's document is on its page: "‹" and the task's title back to it, "Saved" and the Markdown's modes at the header's right, its name as the heading written in place with its bin at the right, "A file of this task's" and where it is on disk in a pewter line, then its Markdown at reading size; renamed, its address and its row on the map follow.
Outline lists the open document's headings, each a 28px row, a level 14px in, the top level in 500 ink; a heading's row puts the caret on its line, at the window's top.

**Nudges.** A glass card of rows with graphite icons, a secondary "Open" action and a steel dismiss control.

## Interaction grammar

Motion is colour, border and background transitions at `--dur` 150ms on `--ease`, and nothing else in the signed-in UI.
The earlier checkbox draw-in, the breathing running dot and the row fade-in were removed.
Beyond that, only these move: the toast, the confirm dialog (an 8px rise with fade), the theme icon's morph, the sidebar's width when it collapses, its pages and projects making room for one dragged, and the system's two one-shot animations, the wordmark's `--spark-entrance` and a ticked box's `--check-pulse`.
`prefers-reduced-motion` collapses every transition.

**Calendar drag** (`app/static/calendar.js`, vanilla, listeners on `document` so they survive htmx swaps).
Oscar's own events move and resize, snapping to 15-minute increments, an item keeping the place it was held by, with a live preview; the resize grip is steel.
A click on an event, or an all-day event, opens its card (380px, beside the item): a work meeting's title in 16px/600, its day and times, its place, its link as the primary "Join on zoom.us" and a pewter note that it is read-only; a cancelled one has the neutral Cancelled chip and no Join.
One of Oscar's own is written on its card instead: its title in 16px/600 on its line, its repeat and place in graphite, Date, Starts and Ends on lines, then Save and Delete (for a series, Delete this one and This and later), each delete asking first.
Dragging down an empty column draws a new event's time; a click takes the half hour it lands in, for an hour; on touch only a tap writes one, so the grid still scrolls.
Either opens the composer (380px) beside the time: the title on its line in 16px/600, Date, Starts and Ends, Repeat on a line of its own, the length (or "No time: all day") in 12px pewter beside Add event.
New event and E open the composer under the button, on today if it is shown.
Only one card floats at a time; a press outside closes it and does nothing else, and Esc closes it.
Every mutation re-asks the server by firing `calendar:refresh`; the grid re-renders.
A height-capped grid opens on the usual day, 06:00 at its top, or with now in view an hour and a half under the top as far as 22:00 allows, and keeps its scroll position across refreshes.

**Writing tasks** (`app/static/task-sheet.js`, `app/static/tasks.js` and `app/static/notes-editor.js`, vanilla, listeners on `document`; the description on CodeMirror 6 and `markdown-live.js`).
`task-sheet.js` runs the task sheet: the title line, its field icons and their menus, typed words becoming fields, adding, and saving an edit when focus leaves it.
Every field is a hidden input the form posts, so the icons and menus only read and write those inputs; the menus live in the body, since list cards clip what overflows them.
`tasks.js` runs the row disclosures, the folds (Done's, and the timeline's projects), the cursor on the task lists, and filing by drag; `shell.js` the keys that work on every page and need a script, the sidebar's pages 1 to 9 (Alt+1 to Alt+9, from a field too) and ? for the keys dialog.
Every key is an action's in `app/services/keys.py`, and `keys.js` holds them as the page was drawn with them: a page's own script asks `Keys.is(e, "task.done")` of a key it has the context for, and `keys.js` does the rest itself, on the window after every page's own listener, by clicking the page's button for it, focusing its field, going to its page, or calling a handler a script handed over (`Keys.handle`), such as Left and Right (outside a field) on a page of days.
The list keys: Up/Down or J/K move (Done's header is a stop, opened by Enter or Space), Shift jumps a list, Home and End go to the ends; Enter or E edits, N writes a new task (into the cursor's list where it has a composer, else the page's first), X done, T today, M tomorrow (posted directly on a done row, which has no do-date buttons), D and P open the task sheet on its day or project menu, Space opens the description, Delete deletes after asking, Esc leaves.
The cursor lands where the work leaves it: on the row that followed one dated, filed, finished or deleted away; on the same task after an edit, wherever it regrouped to; on a task just added when Esc leaves the composer; and on the same task across V's reload (`sessionStorage` key `pc-task-cursor`).
htmx wires up swapped-in content in the same step as the swap (`defaultSettleDelay: 0`, in base.html): with its default 20ms settle, a re-rendered list missed a refresh fired in that gap, and keys and submits met controls not yet wired up. Keys are never queued, since a replayed key cannot type; a sheet htmx has not taken over never submits natively and leaves the page; an open edit caught in a list's re-render keeps its sheet, words, fields and caret where the task's new row lands.
Keys never fire while typing in a field or over a dialog, and reaching for the mouse ends the pass.
Lists that re-render from the server take any half-written task with them: `task-sheet.js` carries its title, description, fields and focus across the swap to the fresh sheet with the same `data-composer-key`.
A task whose add is in flight is not a draft: only the focus moves over, so it is never offered to be added twice, and if its list re-rendered from a moment before the add landed, the lists render again so the new task shows.
`notes-editor.js` is the description editor: the Markdown engine (below) as a checklist, mounted in each `[data-notes-editor]` as htmx loads it and destroyed as htmx removes it.
It writes the same plain text the server stores into a hidden `notes` textarea, with an input event, so forms and the server never see the editor; a form reset, or a draft carried to a fresh sheet, sets the editor from the field with a fresh history.
Ctrl+Enter is taken out of CodeMirror's keys: it belongs to the sheet (add, or save).
The confirm dialog answers the row it was asked about even when a late list refresh swapped that row while it was open: focus goes back to the row's live twin, and a confirmed delete is sent from it rather than silently dropped with the detached one.

**The Markdown engine** (`app/static/markdown-live.js`, `window.MarkdownLive.extensions({checklist, mode})`, on CodeMirror 6 and the Lezer Markdown parser).
Markdown is written and shown as it reads while it is written, as Obsidian's Live Preview does (Obsidian is CodeMirror 6 too): no preview pane.
The text is the record: every effect is a decoration over the characters, never a change to them, so what is saved, copied and undone is the Markdown as written, byte for byte, and Claude reads and writes the same text.
It has Obsidian's three modes: Live Preview, Source (the Markdown as written, every mark showing in steel) and Reading (rendered, not editable, its boxes still ticking and its links still opening), switched with `MarkdownLive.setMode`, `toggleReading` and `toggleSource`; a page that offers them binds Ctrl+E to `toggleReading` itself, on a keydown the editor has not handled, since Reading cannot hear it.
A task's description stays in Live Preview, with nothing to switch.
It parses CommonMark with GitHub's tables, strikethrough, task boxes and bare links, incrementally, and draws only the window's lines.
Indented lines nest instead of turning into code, "---" under a line is a rule rather than a heading, and HTML blocks stay text, since these are notes, not a typesetting source.
A mark ("**", "*", "~~", "`", "[ ](url)", "\\") hides until the caret or a selection reaches the words it marks, then shows in steel; a heading's "# ", a quote's "> " and a rule's "---" show while the caret is on their line; a fenced block's fences fold to 6px edges until the caret is in the block, its language at its top right.
With the editor unfocused, nothing shows.
Headings are 600 ink (h1 16px, 20px on a task's page; h4 to h6 graphite), a quote a 2px steel rule at its left, a rule a mist hairline.
Code, inline as a tinted chip (`--ink-tint-tag`) and fenced as a tinted block, is the one text not in Inter: a system monospace at 0.9em (`--font-code`), since its columns must line up.
A fenced block is highlighted in its language (Python, JavaScript, TypeScript, JSON, HTML, CSS, shell, PowerShell, YAML, TOML, SQL, diff) in the sign colours; the code's colours apply only inside a code block, so raw HTML in the text stays plain.
A table is drawn as a table (its alignments, and its cells' emphasis, code and links, a hairline grid, its header on the faint tint); a click in a cell opens the table as its Markdown, in code's face, the caret at that cell's end.
An image (`![words](url)`) is drawn as itself, only from a web or data address; with the caret in it, its Markdown shows.
Only an http(s) address is a link (underlined ink, as every link); "[words]" alone stays as written.
A rendered link opens beside the app on a click, as Obsidian's does; one showing its Markdown is written in, and opens on Ctrl+click (Cmd+click).
An address pasted over words on one line makes them its link.
Lists are read line by line, as `app/checklist.py` reads sub-tasks: a line's lead (its indentation, "- " and box) is one piece the caret never stands in, drawn as a 14px steel box (ink with a paper tick when done) for "- [ ] ", or a bullet for "- ", the words hanging 22px a level beside it; a numbered list's numbers are graphite.
The boxes are exactly the lines the server counts as sub-tasks; ticking changes only the box's mark ("[x]" or "[ ]").
Enter goes on to the next item ("[ ] " if the item had a box), at an item's first word puts an empty one above it, and on an empty item steps out a level, then out of the list; it goes on with a numbered list and a quote too.
Shift+Enter writes a note under an item.
Enter on a note goes on to its item's next sibling.
Backspace at an item's first word takes its box away, and on an indented line a level.
Tab nests an item or note under the line above (at most a level deeper) and Shift+Tab takes it back; where nothing can nest Tab moves focus on.
Ctrl+L makes a line an item, then ticks and unticks it.
Ctrl+B, Ctrl+I, Ctrl+Shift+X and Ctrl+\` wrap the selection in "**", "*", "~~" and "\`", or unwrap it; Ctrl+K stays the command menu's and Ctrl+Enter the task sheet's.
Spelling is marked only on the caret's line.
A task row draws the same description through `app/markdown.py` `render_note` (headings, quotes, rules and inline Markdown; fenced blocks as code), so the row reads as the editor does with the caret elsewhere.
On a 5,000-line document a keystroke redraws in about 2ms.
Its browser tests run it on a task's page and, for what no page uses yet (the modes, tables, code), on a bare page of its own (`tests/fixtures/markdown_live.html`).

**Notepad** (`app/static/notepad.js`, on CodeMirror 6).
The editor is `app/static/vendor/codemirror.js` (window.CM, with the Lezer Markdown parser; every page loads it, for the task sheet's description), built from `scripts/vendor/codemirror` (`npm install`, `npm run build`) and committed, so the app itself has no build step; it takes the page's textarea's place, the textarea holding the notes as the server sends them.
The notes are the text as stored: a task row is its "- [ ] " or "- [x] " line, drawn as its box (one piece: the caret never stands in it), and a task's other rows start with a tab, drawn as its indent; the rows are line decorations, the box, indent and controls widgets, the controls a float at the title's end (so they wrap to their own line by themselves).
"- [ ] " at a row's start makes the row a task, and Enter in a task starts its next row with a tab, under its title ("- " rows its sub-tasks); Enter on an empty tabbed row steps back out to a plain row, and Enter at a title's first word puts a plain row above it.
"/reflection" at a row's start makes the row a reflection, drawn as its label (one piece, like a task's box); Enter in it starts its next row with a tab, as in a task, and Ctrl+Enter goes on to a plain row after it.
"- [ ] " on a task's row makes it a sub-task, its box one piece like a task's (the caret never in it); Enter on one starts the next, on an empty one takes its box away, and Backspace at its first word too. Its box edits its "[ ]", and an added task has its description written at once (`- [x] ` done, as the task sheet's checklist reads it).
"/stay" at a row's start makes the row a stay, labelled like a reflection; Enter at its end, with nothing under it yet, writes its items (the last stay's names, from the server; place and accommodation the first time), the caret at the first value, as choosing /stay from what is offered does. Enter on an item starts the next ("\t- [ ] "), on an empty item takes its box away, and its box edits its "[ ]"; after an item's box its names are offered. The line under the date follows the notes as they are written.
What is offered comes from CodeMirror's autocompletion: the commands after "/" at a row's start, and a stay's item names. Esc belongs to the notes except while an offer is on screen, when it closes it.
A folded task's hidden rows follow its title on one line: a caret landing after them goes to the title's end, and an edit that would reach them (a row added under the title, Delete at its end, a selection across it) unfolds the task instead, the next edit doing what was meant; an undo goes through and unfolds it, and Ctrl+Enter leaves it folded. Folded task rows save with the notes (a text block's `folded`, by row).
Home on a task's, reflection's or stay's row goes to its first word, a selection drawn back to a row's start stops there, Left from there goes on to the row above, and Backspace there takes its box, label or tab away, so the row is plain again.
Ctrl+Enter or Esc in a task saves it: added for the day ("Task added: <title>"), or its title and description written to the task it made ("Task saved: <title>"); Ctrl+Enter then goes on to a fresh plain row.
Ticking a task's box ticks its task; the box shows the task as it stands, wherever it was ticked.
A task's controls open the task sheet's menus (task-sheet.js, `data-sheet="props"`): a field set before the task is added goes with it when it is (a new task's do date is the page's day), and once added each change is written to the task at once, with its words.
Its bin takes its rows out of the notes, an undo step of its own (undo brings the words back, as a task not yet added); a task already added is deleted with them, once the app's "Delete task?" dialog is confirmed (`window.confirmAction`, shell.js, the dialog hx-confirm opens).
The notes save as a whole 600ms after a change, when the tab is hidden, and when the page is left (with every task written or changed since its last save): the text between reflections as text blocks, a task row as "- [ ] " or "- [x] " and the task it made by row (a text block's `links`), each reflection as a reflection block of its words (its first row after "/reflection", its other rows without their tab), and each stay as a stay block of its rows (as a reflection's), which read back as those rows.
A task row keeps the task it made through edits around it (its start mapped through each change) and loses it with its box; an undo that brings a task's rows back brings its task back with them.
A save names the version it was made from; refused (another window saved since), the page stops saving and asks; returning to the tab shows a newer version when nothing here is unsaved.
Esc outside a task steps out of the text; Left and Right, outside it, go a day back or on.

**The habits' pane** (`app/static/habits.js`, vanilla, from the habits the page was drawn with).
A box posts the day ticked or not (`POST /ui/habits/<id>/done`), drawn at once and put right by the answer, the habit as the pane draws it; a toast says so if it fails.
A comment saves 600ms after the writing pauses, as it is left, and as the page is (`POST /ui/habits/<id>/note`, the file read in first, so a comment written there meanwhile is not lost); Enter saves and closes it, Shift+Enter writes a new line, Esc closes it.
The day picked is the pane's alone: a comment open as it changes is saved first, then shows the new day's.
Left and Right on a box pick the day before or after, of the seven.
A habit's days' icon is the task sheet's (`data-sheet="props"`, one field, `days`): its menu offers Any day, Every day and Weekdays, then each weekday to tick on or off, the menu staying open; a change is written to the habit (`POST /ui/habits/<id>/days`).
Rows are made once and changed in place, and moved only when the list's order changes, so the keyboard and a comment's caret stay where they are.
**A habit's page** (`habit.html`, on `doc-editor.js` as a document's page, and `habits-page.js`): its words save as a document's do, over the version they were written from (`POST /ui/habits/<id>/file`, 409 when its file moved on since), and its name the same way; a save draws its half year again (`doc:saved`), and so does a change of its days.
**Calendar's sheet** (`app/static/day-sheet.js`, vanilla, on the sheet itself so its keys come before the page's).
A roving cell cursor as the Gantt's, kept through every redraw by day and column, starting unfocused on today's row so the page's keys work until a click.
Every edit is one JSON POST of ops (`/ui/day-sheet`), applied as the days' notes and tasks would have them and answered with the sheet drawn again; requests go one at a time, and coming back to the tab draws it again from the days as they stand.
A habit's drag is held under the pointer and posted once, on release, for the days it changed.

**Gantt** (`app/static/gantt.js`, vanilla, on the sheet itself so its keys come before the page's).
A roving cell cursor (the cursor's cell alone is in the tab order), kept through every redraw by row key and column, and scrolled clear of the frozen pane and header.
Every edit is one JSON POST of ops (`/ui/projects/<id>/gantt`, `app.services.gantt.apply`), answered with the sheet drawn again; requests go one at a time, and a sheet that now starts earlier keeps the same weeks in view.
Right (or Tab) from Due enters the time where the row's work is, not at the sheet's first column: a task's start (or its due), a workstream's first day, and for a task with no days, or a group's add row, the next workday after the dated task above it in its group, never before today (today with none); a day out of sight scrolls in a lead from the pane.
Ctrl+arrows go as a spreadsheet's do: from a filled cell along its run to the run's last, from an empty one to the next filled, else to the sheet's edge, though along a row with no days drawn on the way today stops it (before the edge, or before the pane going left); a column of time is filled under a bar, tick or lane, a pane cell by its box or words.
Typing writes over a cell and the arrows then leave it (Excel's Enter mode); Enter, F2 or a double-click write in it with the arrows moving in the words; Enter keeps it and goes down, Tab across, Esc drops it, and a click elsewhere keeps it.
A value the server refuses is said in the toast and the cell opens again on the words.
Every printable key is the sheet's while it has focus (the page's number and letter keys do not fire), except ? for the keys.
Delete on Task, or a task's bin, deletes the tasks held after asking; elsewhere Delete clears the bars or dues held.
Undo keeps the rows' fields as they were before each edit (taken when its turn in the queue comes) and redoes to how they were after; a new task undoes by deleting it, and a deleted task cannot come back, so deleting clears the history.
The pointer: a click moves the cursor (Shift holds a range), a drag over a task's time draws its bar there, a bar's middle drags it and its grips stretch it, a tick drags its due, all by whole columns (weeks, or days), previewed as they move; a row dragged by its number drops before the row it is over (above its middle) or after it, at a workstream's top over its row, and at a group's end over its add row, and undoes back where it was; a workstream's row dragged by its number takes its whole lane, faded, and drops before the first lane whose middle is under the pointer, else after the last, and undoes back before the lane it was before.
Weeks / Days (or V outside the sheet's cells) fetches the sheet in the other scale and keeps the same days in view and the cursor on its day's column; it is remembered (a `gantt_scale` cookie), and edits answer in the scale they were made in.

**The chats** (`app/static/chat.js`, vanilla, on every page; Nutrition's, Spending's and the agent window's).
Each composer is a `form[data-chat]` naming its log (`data-log`) and its agent (`data-name`), its listeners on the document, so the agent window's, drawn again on a new chat, works as it lands.
Enter sends and Shift+Enter starts a new line; Left and Right, outside the message, go a day (a month, on Spending) back or on.
In the agent window, A (outside a field) opens it with the caret in its message, or collapses it; Esc steps out of the message, so A collapses it next; collapsing it from inside hands the focus to the sidebar's Agent, and New chat or another agent puts the caret back in the message.
Its answer goes on as Oscar moves from page to page: the next page shows it so far and asks after it every two seconds, as a chat page opened mid-answer does.
Sending draws Oscar's message and Claude's row at once, then reads the answer as it streams (newline-delimited JSON: the words, what Claude is doing, then done), following it down the chat while the chat is scrolled to its end.
Done, the chat and what Claude changed are drawn again from the server (the composer's `data-changed` event: `nutrition:changed`, `money:changed`), the answer as Markdown and the log or the month as Claude left it.
A page opened while an answer is on its way shows it so far and asks after it every two seconds; once it lands, the log or the month is drawn again too (`nutrition:answered`, `money:answered`).
A refused message (empty, or one while Claude is still answering) is said in the toast, and its words go back in the composer.

**Assets.** Static URLs go through `asset()`, which appends the file's mtime (`?v=`), so a browser never pairs new templates with a stale stylesheet.
The favicon is the Today icon in ink on a white tile, its dot the spark (Neon Signage's day pink, `#e5006e`).
It is the one system colour outside `design/`: change it by hand when switching systems.
