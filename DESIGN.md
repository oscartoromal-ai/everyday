---
name: Personal Calendar
description: A personal planner in Neon Signage, moving page by page into a drafted settei sheet, starting with the day page.
colors:
  ink: "#1a1530"
  graphite: "#5d5873"
  pewter: "#68627a"
  steel: "#8f889e"
  paper: "#ffffff"
  hue-6-drafting-blue: "#3a5ccc"
  hue-8-red-pencil: "#dc5444"
  draft-rule: "#6580d7"
  draft-pencil: "#dc5444"
  draft-pencil-ink: "#a6423e"
  draft-pencil-fill: "#b54740"
  draft-paper: "#f7f8fd"
  draft-grid: "#3a5ccc17"
  sb-ink: "#30479d"
  sb-rule: "#6580d761"
  draft-cyan-night: "#5f9df0"
  draft-rule-night: "#b1cbf8"
  draft-pencil-night: "#f78a66"
  draft-paper-night: "#2f436a"
  draft-grid-night: "#5f9df029"
  sb-ink-night: "#b8c3ff"
typography:
  sheet-title:
    fontFamily: "Barlow Condensed, Inter Variable, sans-serif"
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.06em"
  title:
    fontFamily: "Inter Variable, Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
  body:
    fontFamily: "Inter Variable, Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "-0.01em"
  body-sm:
    fontFamily: "Inter Variable, Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    letterSpacing: "-0.01em"
  caption:
    fontFamily: "Inter Variable, Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
  label:
    fontFamily: "Barlow Condensed, Inter Variable, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.18em"
  sheet-caps:
    fontFamily: "Barlow Condensed, Inter Variable, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    letterSpacing: "0.14em"
rounded:
  square: "0px"
  tag: "6px"
  ctl: "12px"
  pill: "9999px"
spacing:
  s-1: "4px"
  s-2: "8px"
  s-3: "12px"
  s-4: "16px"
  s-6: "24px"
  s-8: "32px"
  s-12: "48px"
components:
  plate:
    backgroundColor: "{colors.draft-paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.square}"
    padding: "9px 12px"
    height: "40px"
  draft-caption:
    textColor: "{colors.graphite}"
    typography: "{typography.label}"
  button-drafted-primary:
    backgroundColor: "{colors.draft-pencil-fill}"
    textColor: "{colors.paper}"
    rounded: "{rounded.square}"
    padding: "0 14px"
    height: "34px"
  button-drafted-primary-hover:
    backgroundColor: "{colors.draft-pencil-ink}"
  button-drafted-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    padding: "0 14px"
    height: "34px"
  button-drafted-secondary-hover:
    backgroundColor: "{colors.draft-paper}"
  day-sheet:
    backgroundColor: "{colors.draft-paper}"
    rounded: "{rounded.square}"
    padding: "24px 32px 48px"
  strip-block:
    backgroundColor: "{colors.sb-ink}"
    textColor: "{colors.draft-paper}"
    rounded: "{rounded.square}"
    height: "24px"
  cut-number:
    textColor: "{colors.sb-ink}"
    typography: "{typography.sheet-caps}"
    width: "56px"
  record-value:
    textColor: "{colors.draft-pencil-ink}"
    typography: "{typography.sheet-caps}"
---

# DESIGN.md

This describes the visual system actually built for Personal Calendar, grounded in `app/static/app.css` and `app/templates/`.
It is descriptive, not aspirational: every claim below traces to a rule or a template in the repo.
The frontmatter above resolves the settei world's tokens to their Day values (and a few Night ones) for tools; the CSS is the source, and most of those tokens are `color-mix()` of contract tokens, listed in `.impeccable/design.json`.

## The system: Neon Signage, from design-language

Since 2026-09-26 the planner wears "Neon Signage", at Oscar's request, picked from three Tokyo Night prototypes (kept on the branch `prototype/tokyo-night`).
It replaced Brasa v2, which the planner wore from 2026-09-25; before that it had its own "calm paper planner" look.
Since 2026-09-27 a second world, the settei sheet (below), owns every input and the whole day page; the rest of the app will move into it page by page.

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
The settei world's own tokens are defined in `app.css`, but every one of them is mixed from contract tokens, so a switch recolours them too.
`base.html` links `design.css` before `app.css`, preloads the fonts the lock file lists, and names the installed system in its top comment; `design_system()` in `app/ui/views.py` reads the lock file on each render.

The system's rules, as they apply here:

- **Ink draws the interface.** Text, icons, checkboxes and the plan's own blocks are ink; there is no decorative colour in the chrome.
- **Two lights with two jobs.** Pink, `--spark`, is you: the active nav item in the sidebar, the primary button outside the drafted forms, focus, today on the Calendar's grid and on the Weeks board.
  Cyan, `--signal`, is time: the Calendar's now-line and its label.
  Each still marks one thing per region.
  The day sheet uses neither: its marks are the settei world's red pencil.
- **Night emits, Day prints.** At night the spark elements glow (`--spark-glow`), the now-line glows (`--signal-glow`), and the plan's own blocks on the Calendar are white tubes with a soft bloom (`--solid-glow`).
  By day every glow is flat, and the same roles are printed colour on a pale sky.
  Nothing in the settei world glows, by day or night.
- **Glass.** The canvas (`--canvas`) is the system's: sign glow over black by night, a pale pink-and-sky wash by day; resting surfaces are translucent glass with no shadow; only floating UI is opaque and casts a shadow.
- **Quiet status, loud action.** Status colour (ok, warn, err, neutral pairs) appears only inside badges, never as coloured text runs or large fills.
- **The graphic never carries the meaning alone.** The now-line's time is written in the gutter (on the day strip, under its mark), and deadlines carry the word "due".

## The settei world: drafted, like a settei sheet

Oscar's pick on 2026-09-27, from three 90s-anime directions in `tracker/prototypes/input-boxes.html`, then carried to the whole day page as an anime storyboard.
It is the world the rest of the app will move into; today it owns every input across the app ("drafted inputs" in `app.css`) and the day page ("a day's page: the day sheet").
It draws like the model sheets 90s anime was animated from: graph paper, thin rules in drafting blue, registration crosses at the corners, condensed caps for everything the sheet itself writes, and red pencil for what is being marked.
It has no Japanese text anywhere, by Oscar's decision.

Its tokens, all on `:root` in `app.css`, with Night values under `:root[data-theme="dark"]`:

- `--draft-rule`: the 1px drafting-blue rule, `--hue-6` softened toward paper by day (78%) so a resting field blends in while its edge still holds 3:1; by night it is the cyanotype's pale cyan rule (45% `--draft-cyan` into ink).
- `--draft-pencil`: the red pencil, `--hue-8` by day; by night a vermilion mixed from `--hue-8` and `--hue-3` (55/45), not the system's pink.
- `--draft-pencil-ink`: red pencil as text, deepened toward ink by day (72%) for 4.5:1; by night the pencil itself.
- `--draft-pencil-fill`: red pencil as a fill under paper-coloured text, deepened by day (80%); by night the pencil itself.
- `--draft-paper`: the sheet's paper, a hint of `--hue-6` in paper by day (4%); by night Prussian-blue cyanotype (36% `--draft-cyan` into the night's paper).
- `--draft-grid`: the graph-paper line, `--hue-6` at 9% by day and `--draft-cyan` at 16% by night.
- `--draft-cyan`: Night only, the drafting blue turned toward cyan (`--hue-6` 78% with `--hue-1`), the base of the night's rules, paper and grid.
- `--draft-sheet`: the graph paper itself, 16px squares of `--draft-grid` over `--draft-paper`, as one background shorthand.
- `--draft-marked`: the field in use, as a box shadow: its rule, a 1px gap of paper, and a 1px red-pencil line around it.
- `--font-label`: Barlow Condensed 600, the sheet's lettering.
- On the day sheet only: `--sb-ink` (the sheet's printed blue for cut numbers, blocks and scene marks: `--hue-6` 70% into ink by day, 45% by night), `--sb-rule` (the columns' inner rules, `--draft-rule` at 38%), and the column widths `--cut-w` 56px, `--rec-w` 212px, `--time-w` 104px, composed into `--sb-cols`.

**The Square Rule.** Everything in the settei world is square: plates, drafted buttons, the sheet, its title block, strip marks, badges on the sheet and the focus ring (`border-radius: 0`).

**The Red Pencil Rule.** Red pencil marks only what is being written (the field in use, the row being written, the caret) and what the planner recorded (a set field's value, record numbers, do-dates, due dates and times, the now mark); Oscar's own words stay ink.

**The Lettering Rule.** Barlow Condensed caps are the sheet's own voice (captions, column heads, cut numbers, records, scene marks, the day's name, the buttons that finish writing); what Oscar writes is always Inter.

## Colour

All colour is contract tokens from `design.css`: light mode ("Day") on `:root`, dark mode ("Night") under `:root[data-theme="dark"]`.
An inline script at the top of `<head>` sets that attribute before first paint: the choice saved by the sidebar's theme toggle (`localStorage` key `pc-theme`), or else the system theme.
With no saved choice, `shell.js` keeps following the system live.

- **Neutrals:** `--paper`, `--fog`, `--hairline`, `--mist`, `--steel`, `--pewter`, `--graphite`, `--ink`, and `--carbon` for dark chrome with `--on-carbon` text.
  Headings and primary data are ink, secondary text graphite, and placeholders and muted labels pewter.
  `--steel` never draws text: it is for marks (empty checkboxes, muted icons, grips) at 3:1 or more.
- **Spark:** `--spark` with `--spark-deep` for hover and for spark-coloured text, `--spark-tint` for selection and drop-target state only, and `--on-spark` for text on it (near-black at night, since white on neon pink fails contrast).
- **Signal:** `--signal` draws the Calendar's now-line, `--signal-deep` writes its time.
- **Solid:** `--solid`, `--on-solid` and `--solid-handle` make task blocks on the Calendar solid ink in both modes: deep indigo by day, white tubes at night.
  Without the inversion, dark-mode blocks sat at almost the same grey as work meetings.
- **Status pairs:** `--ok-*`, `--warn-*`, `--err-*`, `--neutral-*`, rendered on glass through the `--badge-*-glass` fills; the day sheet uses the same fills, squared.
- **Canvas and glass:** `--canvas` (fixed to the viewport), `--chrome-flank` (the matte sidebar), `--glass-card`, `--glass-border`, `--glass-input`, `--glass-btn`, `--glass-hover`, `--glass-row-hover`, and ink-alpha hairlines `--hairline-on-glass(-strong)`; `--ink-tint-faint` tints weekends.
- **Hues:** the settei world is mixed from four of the contract's hues: `--hue-6` (drafting blue) and `--hue-8` (red pencil) in both modes, and by night `--hue-1` (turning the blue to cyan) and `--hue-3` (turning the pencil to vermilion); the other four are installed but not used yet.

## Type

Neon Signage uses one face, Inter variable, installed in `app/static/design/fonts/` (OFL, licence alongside) and declared in `design.css`; `base.html` preloads it at the same URL, so it is fetched once.
`calt` and `liga` are off, tracking is -0.01em, and weights are 400, 500 and 600 only.
Titles (page, card, week and dialog titles, and the wordmark) use `--font-display` and figures (times, counts, targets, busy hours) use `--font-num`; in Neon Signage both are Inter, so these hooks matter only when another system is installed.
Every Inter size is a scale token: `--t-caption` 12px, `--t-body-sm` 14px (the default UI size), `--t-body` 16px (inputs, card titles, the day sheet's writing), `--t-sub` 20px (project titles, a day sheet's "# " heading), `--t-h-sm` 24px (page titles).
Dates, times, counts and busy hours are `tabular-nums`.
The settei world's lettering is Barlow Condensed 600 (`--font-label`), always uppercase: the one face beside Inter, self-hosted as a Latin subset in `app/static/fonts/barlow-condensed-600.woff2` (OFL) by `scripts/fetch-label-fonts.py`, declared in `app.css`.
Its sizes are the sheet's own, outside the Inter scale: 34px at 0.06em for the day's name (28px on phones), 13px for cut numbers, 12px for drafted buttons, record numbers and the Today link (0.14 to 0.16em), 11px for input captions (0.18em), column heads, strip and scene marks (0.14em), and 10px for the title block's field names, hour labels and the now mark's time.

## Shape, space, elevation

- **Radii:** in Neon Signage's parts, only `--r-tag` 6px (badges, checkboxes, calendar items), `--r-ctl` 12px (buttons, inputs, cards, nav items) and `--r-pill` (status badges, the segmented control).
  In the settei world, none: every plate, drafted button, sheet and mark is square.
- **Spacing:** the `--s-*` scale (4, 8, 12, 16, 24, 32, 48).
  Everything that holds a plate leaves the 5px its corner crosses need (`.draft-slot` pads 16px).
- **Rules, not shadows, in the settei world:** its edges are 1px rules drawn as inset box shadows, so they never shift layout; the day sheet's frame is a double rule (the outer rule, 4px of paper, a fainter inner rule).
- **Elevation:** resting glass has no shadow; only the block menu, the add-a-task popover, the task sheet's menus, the "/" commands and the toast float, on opaque paper with `--shadow-dropdown`.
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
Content is 800px wide for list pages (Tasks, Projects) and 1200px for the day page, Calendar and Weeks.
The shell stays Neon Signage on every page, the day page included; only the content column changes world.

## Components

**List cards.** Tasks' groups, each project, each week in Rows and the trays are glass cards.
A title row sits on a stronger hairline, and rows below are full-bleed, dividing with hairlines and lighting on hover with `--glass-row-hover`.

**Task rows.** An 18px checkbox with a 6px radius fills with ink when checked; there is no draw-in animation.
Every empty box (rows, sub-tasks, the description editor, Weeks' mini boxes) is drawn in `--steel`, not `--mist`: mist falls under the 3:1 a control needs against the cards, in both modes.
The box the user has just ticked plays the system's `--check-pulse` once (in Neon Signage, a ring of spark light that fades in 640ms); `tasks.js` marks the fresh row `.just-done` for it.
The title is 14px/500 ink, and the meta line is 12px pewter.
A block's time is ink 500, and a do-date off the list's day is graphite.
"Due soon" and "missed" are warn and err badges.
A missed task offers one step back onto the plan beside its badge, a quiet 12px pewter button like the do-date buttons: "Replan at 16:30" books the missed block's length into the next free quarter-hour slot today (past timed events and other blocks, before 22:00), or "Move to tomorrow" gives it tomorrow as its do-date when today has no room.
The meta line sits 4px under the title, so the description disclosure can take a full 24px target (WCAG 2.5.8) without touching the title's.
Claude's statuses are badges too: Queued neutral, Running ok (with a static dot), Needs review warn, Blocked err.
A task with a description adds a pewter disclosure to the start of its meta line: a chevron and the sub-task count ("1/3"), or "Notes" when it has none.
Opened, the description sits under the meta line in 14px graphite: context lines as written, sub-tasks as 14px ink checkboxes that fill like the row's own, and a done sub-task pewter with a strikethrough.
An indented line under a sub-task is its note, hung 22px in so it aligns with the sub-task's words.
Which descriptions are open is remembered per tab (`sessionStorage` key `pc-open-notes`), so a day page's live refreshes never fold them shut.
A small trash bin ends each row, steel and hidden until the row is hovered or focused (always shown on touch), and err-tinted on hover.
It, and the task sheet's own bin, open the confirm dialog: opaque paper over the scrim with the modal shadow, titled "Delete task?".
The dialog restates the task's name in ink 600 and offers a Ghost Cancel (focused first) beside a destructive-secondary Delete, never a red primary.
It is the one handler behind every `hx-confirm` that carries `data-confirm-*` attributes (`shell.js`), so the browser's native confirm box never appears.
Each opening hears only its own answer: a dialog's close arrives a moment after it closes, and an Esc followed at once by another Delete must not hand the new question the old one's cancel.
On a day page a task is drawn as a day row instead, in the sheet's columns (see Day sheet), with the same controls.

**Task sheet.** Adding a task and editing one are the same sheet, written like a document rather than filled in like a form.
It is a drafted plate (see Inputs) under its caption, shaped inside like the row it becomes: the row's box (or, to add, a plus in the rule's blue, red once writing), then the title in 14px/500 ink, which wraps as a line of text.
The do-date, time, due and repeat fields trail the title's last word as small icons in `--steel`, 14px, with the value beside the icon in 12px once set ("tomorrow", "15:00–16:00", "Fri 2 Oct"), written in red pencil; repeat stays an icon, its rule in the tooltip.
The gaps before and between them are the line's own spaces, widened, so when they wrap they start flush with the title's text.
Each is a 24px target that opens a small menu on paper with the dropdown shadow: Today, Tomorrow, Next week, Pick a date (the native picker) and No date; for the time, Pick a time, then Change the start, Change the end and No time (native pickers, 15-minute steps; a new start keeps the length); or the repeat presets.
The current choice is 600 with a tick, and choosing hands the caret back to where it was.
Writing sets them too: "today", "tomorrow", a weekday's name or "next week" followed by a space becomes the do-date, "at 3", "3pm", "15:30" or "9-10:30am" the time (an hour when no end is given; a bare number stays a word), "due friday" the due date, and "every day", "every weekday", "every week" or "every month" the repeat.
A time is the task's block on its do-date: set, it books that time on the calendar; changed, it moves it, with the day if the day changes; cleared, it frees it.
The words leave the title as they convert, and Backspace straight after puts them back as words, which then stay words.
The description follows under the title, aligned with its text, below a dashed blue rule.
Editing adds an end line under the description: Project › Milestone (a flag, "Project" when there is none, one menu of open projects with their open milestones indented), a person icon that names Claude when the task is Claude's, its status once it is Claude's or beyond the box, History, and the bin.
History opens under the end line, above a hairline: each change newest first, a 12px pewter line of when and who ("Today 14:02 · Claude"), then a 12px graphite line per field that moved ("Do date: tomorrow → Fri 2 Oct", "Ticked “oil”", "Description edited").
Project and milestone live only there, since the list a task is written in already says which project it belongs to.

To add, each list card ends in the sheet's plus and a pewter placeholder, filed by the card it sits in (a project card's is in that project); on a day page, tasks are written in the storyboard instead.
Typing a title opens the icons and the description (focus alone does not, so a composer that folds away never shifts the page under a click), with a pewter "Ctrl+Enter to add" hint (hidden on touch), a drafted Cancel and the red-pencil "Add task".
Enter in the title moves to the description, and Ctrl+Enter adds the task and returns to an empty title for the next one.
A task dated away from the list it was written in does not join it; the page regroups instead.

To edit, the row's title swaps the sheet in place, captioned Edit task and marked in red pencil, with the caret at the end of the title.
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

**Day sheet.** Today, and every day's page (`/day/2026-09-25`), is one drafted sheet drawn like an anime storyboard, in the settei world.
Each block written is a numbered cut, and its row shows, beside the words, what the planner recorded and when.
The sheet is `--draft-sheet` graph paper inside a double rule, with a 17px registration cross at each of its four corners, 8px outside it; it has no glass and no glow.

*Title block.* The day's name in 34px Barlow Condensed caps ("Today" on today's page, else the weekday), then a pair of 32px square steps for the day before and after, blue-ruled and printed in `--sb-ink`, and on any other day a squared TODAY link between them.
To its right a ruled title block of four fields, each a 10px caps name over a 14px/600 figure: Date ("27 Sep 2026"), Week (the ISO week), Cuts (blocks written, empty lines not counted) and Open.
Under both, the key line names -, /, #, Ctrl+Enter, the arrows and "? all keys", its keys in square boxes on the sheet's rule.
Nudges, when there are any, sit under the title in a squared plate of paper.

*Day strip.* The day's time runs full width under the title as a drafted scale from 06 to 22: a 1px drafting-blue rule above and below, an `--sb-rule` line and 10px caps label at every hour, and a half-hour tick along the top.
Its head is a TIME label, then the day's all-day events as small blue-ruled tags (work ones hatched), then a pewter "Drag a task here to give it time" on the right (hidden on touch).
Timed items are 24px marks in lanes (overlaps stack, 4px apart): an event is a blue-ruled mark on paper, a work event hatched in `--sb-rule` with graphite words, a task block solid `--sb-ink` with paper-coloured words, a completed block ruled paper with pewter struck-through words, and a missed block a dashed red-pencil outline.
The now mark is a 1px red-pencil line, starting under the hour labels so it never strikes one through, with its time in 10px red-pencil caps under the scale.
Pointing at a task's block marks its row on the page, and pointing at a row marks its block: a red-pencil ring on the mark and a faint red wash on the row.
A task row dropped on the scale gets an hour's block where it lands, previewed as a dashed red-pencil mark with its start time.

*The storyboard.* Scene A, "As written", is the page itself: a column head CUT / CONTENT / RECORD / TIME in 11px caps between two drafting-blue rules, then a row per block in four ruled columns (56px, the rest, 212px, 104px), CONTENT widest, each row ruled underneath in `--sb-rule`.
Every block but an empty line is a cut, numbered in order ("01", "02") in 13px `--sb-ink` caps; the last line, where writing goes on, carries the next cut's number faintly (45%) and a pewter "Write on: - a task, / a reflection".
A blank page carries only the prompt "Write the day. Start a line with - for a task, / for a reflection, # for a heading."
The line kept around each box folds to nothing while empty and unfocused, so cuts stack without gaps.
Three blank frames, ruled in the same columns, follow the last cut to the sheet's foot; a click on one, or on the page's margin, writes at the end.
*Content.* What Oscar writes is 16px ink at 1.6 line height with a red-pencil caret, in live markdown: "# ", "## " and "### " headings (20px/600, 18px/600, and 14px Barlow Condensed caps), `**strong**`, `*em*`, `~~strike~~` (graphite) and `` `code` `` (in `--font-num` on a faint blue tint), each mark kept in the text in pewter.
*Record.* A task's record is written in red pencil beside Oscar's ink: "TASK 042" (or "CLAUDE 042" when it is Claude's), then its do-date when it is off the page's day, its due date ("due Fri 2 Oct"), and in graphite its project, "Done", or "from Tue 22 Sep" linking the page it was written on.
Due soon is a squared warn badge, missed a squared err badge in caps beside an underlined graphite Replan or Move to tomorrow, and Claude's status its badge, squared.
*Time.* A task's block is written in the TIME column: its start in 14px/600 red pencil over its end in 12px graphite, pewter once done.
A task's content is its row's box (square, ruled in drafting blue, filled `--sb-ink` when done), title, description disclosure and bin; the row re-reads itself whenever the plan changes, and is a drag source for the day strip.
The row being written is marked in red pencil: a 1px pencil line around the whole row on a faint pencil wash, its cut number red, "RECORDING" in its RECORD cell, and the task sheet inside it drawn without a plate of its own, with a pewter "Ctrl+Enter to close the task" (hidden on touch).
A task opened for editing becomes a plate across CONTENT, RECORD and TIME, captioned Edit task.
A reflection is a cut of its own, written in italics, "REFLECTION" in its record; while written it is ringed in red pencil with the same Ctrl+Enter hint.
A task deleted since it was written keeps its cut: its title pewter and struck through, a steel × that takes it off the page, and a pewter record, "TASK 042" and "Deleted".
The keyboard cursor on the sheet is a 3px red-pencil bar on the row's left edge over a faint pencil wash, and the row's cut number turns red with it.
When the page was saved in another window, a line at the storyboard's foot says so on a faint pencil wash, with Show that version and Keep mine as squared, blue-ruled caps buttons.
"/" at a line's start opens the commands under the caret, as a drafted slip: square, ruled in drafting blue, on the sheet's graph paper; Reflection and Task each carry a pewter aside, and the highlighted one is marked in red pencil (a 1px pencil rule, a faint pencil wash, its name in pencil).

*Scenes.* The day's other tasks follow as the next scenes, lettered B, C and D in the order they appear: "Also today" ("Also on this day" on other days: tasks planned for the day but written elsewhere, descriptions open, then the Done fold), and on today's page "Overdue" and "Delegated to Claude".
A scene's head is a square blue-ruled scene mark in 11px `--sb-ink` caps ("SCENE B") before its 16px/600 title and a pewter count, over a drafting-blue rule.
Its rows are day rows in the CONTENT, RECORD and TIME columns, indented by the cut column so they line up with the cuts above.

*Phones.* Under 900px the record and time columns narrow to 168px and 88px.
Under 720px the sheet has two columns: a 34px cut column ruled on its right, and CONTENT, with RECORD and TIME riding under the words on one wrapping line each; the column head keeps only CUT and CONTENT and the blank frames keep two cells.
The day's name drops to 28px, the title block spreads its four fields evenly, every other hour label hides, and the strip's marks lose their words for a legend under the scale (each item's time in red pencil beside its title).

**Tasks.** A page header ("Tasks", the open and undated counts, and a By date / By project segmented control on the right), the composer alone in its own card, then the tasks.
By date is one list card per do-date group; By project is Projects' cards (without their status control, which moves cards between Projects' shelves, and with a neutral badge on a parked project that still holds open work), then a No project card in the same form, its empty edit slot keeping the counts in line.
While planning, every row names its do-date, "today" included, whichever way it is grouped.
Each row ends in quiet do-date buttons, always shown since dating is the page's job: "Today" and "Tomorrow" in 12px pewter, and a calendar icon that opens the native date picker.
They darken to graphite on row hover and ink on their own hover; a button for the day the task already has leaves its slot empty, so the columns line up down the page.
On phones they take their own line under the title's text, without empty slots.
Dating a task regroups the page from the server.
The page works from the keyboard alone, as do the day page and Projects (each marks its lists' area `data-cursor`).
A 12px pewter line under each of their headers names the page's first keys and ends in "? all keys" (hidden on touch and phones); the focused row is the cursor, drawn as the nav's own marker, a 3px spark bar inset on its left edge with the spark glow, over the row hover fill (in red pencil on the day sheet).
The bar shows for keyboard focus only (`:focus-visible`), never after a click.
It is the one cursor the app draws: a Done fold's header, a Projects shelf's header (as an inset shadow, since its `::before` is the +/− sign) and the item under the keyboard in a task sheet's menu take the same bar (on `--fog` in the menu, which is opaque paper).
Projects' shelves remember being open like the Done folds, so a key acting inside one never folds it away.

**Done fold.** Finished tasks fold away under a list: a pewter "Done" summary with its count and a steel chevron that turns when open, then the rows, checked and struck through, ready to untick.
On a day page it closes the Also today scene, its summary in 11px caps, its rows day rows; on Tasks it is its own card at the foot, noting "last 14 days".
Which folds are open is remembered per tab (`sessionStorage` key `pc-open-folds`).

**Keys dialog.** `?` on any page opens every key, grouped Anywhere, Writing a task and Lists, on the confirm dialog's paper, 760px wide in two columns (one under 640px).
Each column is one grid, so all its descriptions start on one line; keys are 12px graphite in hairline boxes.
The dialog takes focus itself, so no control opens ringed; Esc closes it.

**Capture window.** N or Shift+N writes a new task from any page: on Tasks and Projects into the page's own list, on a day page as a new row at the storyboard's end, and on Calendar and Weeks, which have no list to write in, in a window holding the task sheet (600px, 15vh from the top, on the confirm dialog's paper).
It stays open for the next task, and a toast says where each one went ("Added “Call the plumber” for Fri 2 Oct", or "to No date"), since no list on the page shows it; Weeks' Unplanned tray catches up.
Esc closes it and keeps a half-written draft for the next time.

**Buttons.** `.btn.primary` is the spark primary, glowing at night, `.btn.quiet` the glass secondary, `.btn.danger-quiet` the destructive secondary with an err border.
Week navigation and nudge actions are secondary-style controls.
The buttons that finish writing are drafted instead (see Inputs).

**Inputs: drafted, like a settei sheet.**
Every place Oscar writes is a *plate*, in the settei world's tokens.
A plate is square, ruled with a 1px `--draft-rule`, filled with `--draft-sheet` graph paper, with an 11px registration cross 5px outside each corner (85% opacity at rest).
Above it, a caption: an 11px leader line in the rule's blue, then the field's name in 11px Barlow Condensed caps at 0.18em, graphite.
The field in use is re-marked in red pencil (`--draft-marked`): its rule gains a 1px paper gap and a 1px red line around it, its crosses turn red at full opacity, and its caption turns red with them.
Inside a plate, controls draw nothing of their own: 16px ink text, 40px tall, pewter placeholders, date and time in `--font-num`, a select's chevron drawn in the rule's blue.
Plates are the task sheet (composer and edit, captioned Add a task, then New task once writing; Edit task), the event, milestone and new-project forms, the project editor, Weeks' quick add, and, rule only, Projects' status select.
In a task sheet a set field's value is written in red pencil, and a dashed blue rule divides the title line from the description.
The buttons that finish writing (the sheet's, and those of the inline forms and the project editor) are drafted too: square, 34px (40px beside a form's fields), captions in 12px Barlow Condensed caps at 0.16em; the secondary is a blue-ruled outline that takes the paper on hover, the primary a red-pencil fill with paper-coloured text (`--draft-pencil-fill`, deepened by day for 4.5:1).
Their focus ring is square: a 2px paper gap and a 1px red-pencil line.
Focus elsewhere in the app is unchanged: every other focus ring is `--spark-deep`, not `--spark`, since accent text holds 4.5:1 on every surface where the bright spark can sink into a glow of its own colour.

**Time grid** (Calendar's week).
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

**Nudges.** A glass card of rows with graphite icons, a secondary "Replan" or "Open" action and a steel dismiss control; on the day sheet the card is a squared, blue-ruled plate of paper.

## Interaction grammar

Motion is colour, border and background transitions at `--dur` 150ms on `--ease`, and nothing else in the signed-in UI.
The earlier checkbox draw-in, the breathing running dot and the row fade-in were removed.
Beyond that, only these move: the toast, the confirm dialog (an 8px rise with fade), the theme icon's morph, the sidebar's width when it collapses, and the system's two one-shot animations, the wordmark's `--spark-entrance` and a ticked box's `--check-pulse`.
`prefers-reduced-motion` collapses every transition.

**Calendar drag** (`app/static/calendar.js`, vanilla, listeners on `document` so they survive htmx swaps).
A tray card can be dropped on a day column to create a block, with a live preview.
Planned blocks move and resize, snapping to 15-minute increments.
A click opens the opaque block menu; it loads the task's sub-tasks under its title (a caption with the done count, then the checklist, scrolling past 40% of the viewport), so they tick off while in the block, and it re-fits to the viewport once they arrive.
Context lines stay in the task's description; only the sub-tasks come along.
Every mutation re-asks the server by firing `calendar:refresh`; on a day page that re-renders the day strip, the scenes and the title block's counts too.
`calendar.js` also makes the open rows inside a day page's `[data-drag-to-grid]` areas (the storyboard and the scenes) draggable and fills the drag's data.

**Day strip drag** (`app/static/day-strip.js`, vanilla, listeners on `document`).
A task row dropped on the strip's scale gets an hour's block where it lands, snapped to the quarter hour and kept inside 06 to 22.
Pointing at a block marks its row, and pointing at a row marks its block.
Moving and resizing blocks stays the Calendar's.

**Weeks drag** (`app/static/weeks.js`, native HTML5 drag and drop).
Any `[data-plan-task]` can be dropped on a future day to set its do-date, or on the Unplanned tray to clear it.
Past days refuse drops.
After the PATCH, `weeks:refresh` re-renders the board.

**Writing tasks** (`app/static/task-sheet.js`, `app/static/tasks.js` and `app/static/notes-editor.js`, vanilla, listeners on `document`).
`task-sheet.js` runs the task sheet: the title line, its field icons and their menus, typed words becoming fields, adding, and saving an edit when focus leaves it.
Every field is a hidden input the form posts, so the icons and menus only read and write those inputs; the menus live in the body, since list cards clip what overflows them.
`tasks.js` runs the row disclosures, the Done folds, the cursor on Tasks, the day page and Projects, and filing by drag; `shell.js` the keys that work on every page, 1 to 5 for the nav's pages and ? for the keys dialog.
The list keys: Up/Down or J/K move (a Done fold's or shelf's header is a stop, opened by Enter or Space), Shift jumps a group (a project, on Projects), Home and End go to the ends; Enter or E edits, N writes a new task (into the cursor's project where it has one, else the page's own composer), X done, T today, M tomorrow (posted directly where rows have no do-date buttons), B books the next free hour today (the keyboard's drop on the day strip; a toast says what it booked, or that today is full), R replans a missed task, D and P open the task sheet on its day or project menu, Space opens the description, Delete deletes after asking, V switches Tasks' views, Esc leaves.
The cursor lands where the work leaves it: on the row that followed one dated, filed, finished or deleted away; on the same task after an edit, wherever it regrouped to; on a task just added when Esc leaves the composer; and on the same task across V's reload (`sessionStorage` key `pc-task-cursor`).
htmx wires up swapped-in content in the same step as the swap (`defaultSettleDelay: 0`, in base.html): with its default 20ms settle, a re-rendered list missed a refresh fired in that gap, and keys and submits met controls not yet wired up. Keys are never queued, since a replayed key cannot type; a sheet htmx has not taken over never submits natively and leaves the page; an open edit caught in a list's re-render keeps its sheet, words, fields and caret where the task's new row lands.
Keys never fire while typing in a field or over a dialog, and reaching for the mouse ends the pass.
Lists that re-render from the server take any half-written task with them: `task-sheet.js` carries its title, description, fields and focus across the swap to the fresh sheet with the same `data-composer-key`.
A task whose add is in flight is not a draft: only the focus moves over, so it is never offered to be added twice, and if its list re-rendered from a moment before the add landed, the lists render again so the new task shows.
`notes-editor.js` is the description editor: a contenteditable whose structure is always its own, since every edit that could split, merge or restyle a line is cancelled in `beforeinput` and redone on a line model.
It writes the same plain text the server stores into a hidden `notes` textarea, so forms and the server never see the editor.
In prose mode (the day sheet's text and reflections) there are no sub-tasks and no nesting, Tab moves on, and each line is markdown in live preview: a "#" to "###" heading line and `**`, `*` or `_`, `~~` and backtick runs are styled as they are typed, with their marks kept in the text.
The confirm dialog answers the row it was asked about even when a late list refresh swapped that row while it was open: focus goes back to the row's live twin, and a confirmed delete is sent from it rather than silently dropped with the detached one.

**Day sheet** (`app/static/notebook.js`, vanilla, listeners on `document`).
The page is a column of blocks with a prose block around every box; "- " at a line's start splits the prose there and opens a task row being written (the rest of the line its title), "/" opens the commands, and closing a row (Ctrl+Enter, Esc, or writing elsewhere) puts the caret on the line after it.
An empty row closes to nothing, and Backspace in a fresh row's empty title puts the line back.
Up and Down at a block's edge (the first or last line as drawn, wrapped lines included) step into the next block, a task row included, where the list keys work; on a storyboard row X, T, M, B, D and P keep the cursor on it, since the row stays where it was written.
N (outside the text) opens a row at the storyboard's end, and Left and Right go a day back or on.
The page saves itself as a whole 600ms after a change, when the tab is hidden, and when it is left (a row still being written then is written down too); tasks are saved by their sheet and referenced by id.
A save names the version it was made from; refused (another window saved since), the page stops saving and asks; returning to the tab shows a newer version when nothing here is unsaved.

**Assets.** Static URLs go through `asset()`, which appends the file's mtime (`?v=`), so a browser never pairs new templates with a stale stylesheet.
The favicon is the Today icon in ink on a white tile, its dot the spark (Neon Signage's day pink, `#e5006e`).
It is the one system colour outside `design/`: change it by hand when switching systems.
The label face, `app/static/fonts/barlow-condensed-600.woff2`, is the settei world's, outside `design/` too; it stays when the system switches.
