# Personal Calendar: build-ready spec

A locally-run, Python-backed web app that unifies calendar, to-dos, and projects (with goals, habits, and reviews phased in) as Oscar's control panel for his life and his AI.
This spec is the destination of the wayfinder map in [tracker/map.md](tracker/map.md).
Every section gists a decision made on that map and links the ticket that holds its full reasoning; the tickets are the authority when detail here feels thin.

## 1. Product shape

- Single user (Oscar), single machine (Windows 11), browser UI, no cloud backend.
- The app is the canonical store for personal plan state: projects, tasks, events, blocks.
- Claude is a first-class client: it reads and writes the plan through MCP from day one.
- The work calendar is visible read-only inside the app; the app never writes to it.

## 2. Phasing

Per [v1 phasing](tracker/tickets/002-v1-phasing.md):

- **v1**: the hybrid planner: calendar (events plus chosen task blocks), todos, projects with workstreams, manual entry, recurrence for both events and tasks, the work-calendar ICS feed, the MCP planner interface, nudges (three of four triggers), Tailscale phone access.
- **v2**: automatic capture of Claude Code session work (MCP plan tools as the semantic channel, lifecycle hooks as the deterministic trace); enables the fourth nudge trigger.
- **v3**: goals, which projects roll up into.
- **v4**: habits and routines. Habits came early (Oscar's call on 2026-09-27): written in the notepad as "/habit name" (see Today), kept as their own entity rather than recurring tasks, so they never crowd the task lists; a table of when each was done and missed is next.
- **v5**: reviews and reflection flows.
- **Health** (Oscar's call on 2026-09-28): a module beside the planner, its own group in the nav, starting with Nutrition (see [Nutrition chat](#nutrition-chat), Oscar's call on 2026-09-30) and Me, the context health advice needs: height, birth date, sex, activity level, goal and target weight, dietary pattern, allergies and intolerances, foods avoided and health notes, saved as they change, and weight as a log of weigh-ins, one a day; from them, age, BMI and an estimated daily energy to keep his weight (Mifflin-St Jeor times the activity's factor). Claude reads it through `get_health_profile`.
  Then Garmin (Oscar's call on 2026-09-30, see [Garmin](#garmin)): what his watch measures, day by day, synced from Garmin Connect.
- **Finances** (Oscar's call on 2026-09-30, see [Finances](#finances)): a module of its own in the nav, beside Health: Spending (a month against its budgets, beside a chat with Claude), Accounts (net worth, balances, his banks' exports), Bills and Goals.

Review flows are deliberately unspecified here; they sharpen as their phase nears (see the map's Not yet specified section).

## 3. Planning interaction model

Per [Planning model](tracker/tickets/001-planning-model.md), decided against interactive prototypes ([asset](tracker/prototypes/planning-model.html)):

- **Hybrid**: to-dos live in lists by default; a task gets a calendar block only when Oscar chooses to give it a slot.
  The calendar shows real events plus deliberately scheduled task blocks, never a forced block per task.
- **Delegated to Claude** is a list section with status chips (queued, running, needs review), not a calendar lane.
- **Missed blocks**: when a scheduled block passes uncompleted, the task falls back to the list wearing a visible "missed" marker until replanned or completed.
  Replanned means a block still to come, or a do-date after the day it missed that has not itself passed; the row offers one step back onto the plan, the next free slot today or else tomorrow.
  The empty slot stays on today's calendar as a faded ghost outline, gone tomorrow.
  The calendar's future is a plan; its past stays honest.
- **Tasks** is where the app opens, because planning comes before doing: every open task of Oscar's, grouped by do-date (Overdue, No date, Today, Tomorrow, Later this week, Next week, Later), each with one-click Today and Tomorrow buttons and a date picker.
  No date is the backlog, always shown and sorted deadlines first; a repeating series shows only its next occurrence (on Projects too); Claude's tasks stay in Delegated to Claude.
  A By date / By project switch (remembered) regroups the same tasks as Projects' cards (workstreams, then other tasks, each card with its quick add and Add a workstream), followed by a No project card.
- **Done folds away**: finished tasks leave their lists for a collapsed Done fold, under Today's list and at the foot of Tasks (the last 14 days), where unticking one sends it back.
- **Sub-tasks and the calendar**: sub-tasks have no blocks of their own; a task's block is the time its checklist is worked, and the block's menu on the calendar lists the sub-tasks so they tick off there. Workstreams likewise hold tasks, never sub-tasks.
- **Triage by keyboard**: on Tasks, arrow keys move a row cursor and single keys act on it (T today, M tomorrow, D pick a day, X done, E edit), the cursor moving on to the next row as each one is dated or finished.
- **A task's project is its colour** (Oscar's call on 2026-09-28, chosen from a prototype of four): each project has a colour, set in its editor on Projects, and a task in it shows the project as its flag filled in that colour, the name only on hover, wherever tasks are listed.
  In Today's notes the task's rules take the colour too, and on Tasks its row's rule.
- **Seeing more** (Oscar's call on 2026-09-28; the browser's zoom stays the browser's): compact rows (C, or the rail's toggle) fit more of Tasks and Today's notes on screen at the same text size; Today, Calendar and Weeks widen with the window; and on Today, Ctrl+\ (or the day header's icon) folds the timeline away for the notes. All three are remembered.
- **Filing by drag**: in By project (and on Projects) a task is dragged onto a workstream, another project, or No project to file it there.
- **Today is a notepad beside the day's timeline** (Oscar's call on 2026-09-27, "for now"): the whole left column is one plain notepad for the day, the right the day's timeline.
  The notes are plain text, saved as they are written.
  A row too long for the box wraps inside its row; nothing scrolls sideways.
  Spelling is marked only in the row being written (Oscar's call on 2026-09-28): a row left, and every row once out of the notes, shows no marks; the task sheet's title and description lines likewise.
  A task is written in them: "- [ ] " at a row's start makes the row a task, drawn indented as a checkbox and "Task" (not text); the rows added under it with Enter are indented the same way and are its description, and "- [ ] " on one of them makes it a sub-task, with its own box; plain rows stay at the left.
  A ticked sub-task is crossed out, and a ticked task, title and rows; a sub-task's tick is written to its task's description at once.
  Writing a task never needs the mouse (Oscar's call on 2026-09-28): Tab and Shift+Tab stay in the notes, Tab going from a task's title to the row under it (a new one when it has none), taking a plain row right under a task into it, and making a task's row a sub-task, Shift+Tab stepping back out; and as in the task sheet, "friday", "at 3pm", "due friday" or "every week" and a space in a task's title set that field, a title's last words taken as it is closed; since a word can be meant as a word, each is an undo step of its own that Ctrl+Z (or Backspace straight after) takes back with its field, the words then staying words, and a title closed with words taken says so in its toast ("Task added: Book flights, due Fri 2 Oct"), with Undo.
  Lines pasted inside a task (its title or a row) stay inside it: each after the first becomes one of its rows, a "- [ ] " line a sub-task, so a paste never ends a task early or starts another (reflections, habits and stays likewise).
  A row deleted from inside a task (by Backspace, Delete or a cut, its words, box and tab all gone) goes whole, the caret at the end of the row above, so the rows under it stay the task's.
  Every task stays bracketed by a rule above and below its rows (one rule between two right under each other), and one with rows under its title folds to its title and back, and stays so; Ctrl+Enter or Esc in a task saves it (added for that day, or the task it made updated), Ctrl+Enter then going on to a plain row.
  At the right of a task's title come its controls, the task sheet's icons: do date, time, due, repeat and project, set before the task is added or changed on it after; on the title's last line when they fit there, else on a line of their own under it, within the same row.
  Delete, the last of them, takes the task's rows out of the notes, and deletes a task already added, once confirmed.
  Ticking the box ticks the task, and the box shows the task as it stands, wherever it was ticked; the notes keep the row as "- [ ] " or "- [x] " text, and the page remembers which task each row made.
  A reflection is written in them too: "/reflection" at a row's start makes the row a reflection, free text, its rows under it indented as a task's and the whole bracketed in light blue; Ctrl+Enter goes on to a plain row after it.
  The day's page stores it as a reflection block between the text around it, which Claude reads as such (`get_notebook`).
  A habit is checked in them: "/habit morning-skin-care" at a row's start checks the habit for that day, drawn as a ticked box and "Habit", then its name, what follows (and the rows under it) its note, bracketed in green; unticked, the habit was skipped that day.
  After "/" at a row's start the commands are offered, and after "/habit " the names already used, so one habit keeps one name.
  Each habit has its days (any day, every day, weekdays, or chosen weekdays), set from the repeat icon at its row's right; under the notes, the habits due that day not yet written are listed, each name writing its row and each icon setting its days.
  A due day with nothing written is a miss (a habit for any day is never missed); Claude reads the day-by-day record through `get_habits`.
  What was left open comes along (Oscar's call on 2026-09-28): under today's notes, the tasks still open from the last page before it that holds tasks, those to be worked by today (no do-date, or one not after it) and not yet written here.
  A title writes the task's rows at the end of the notes, its title row that same task (not a copy) and its description its rows, and moves its do-date to today; Bring all writes every one.
  The earlier page keeps its rows as written, each showing its task as it stands, so a task finished today reads ticked there too.
  Where Oscar stays is written in them too (Oscar's call on 2026-09-27: he moves around, and does not always have a bed sorted): "/stay" on a day's page, then its items, each "- [ ] name: value" with a box ticked once sorted, bracketed in amber.
  Its items are his to name (place and accommodation to begin with; a new stay starts with the items the last one had), and under the date the day's stay reads item by item, the unsorted ones in amber.
  A stay is written day by day, not as a range; a view of all days' stays together is next.
  Every day has its notepad: Left and Right (outside the text) go a day back or on, and past days stay editable.
  N writes a new task from Today in the capture window, as on Calendar and Weeks; the day's tasks are worked from Tasks, and the nudge center now opens Tasks.
  It replaces [the notebook](#the-notebook-decided-2026-09-26), where lines became tasks and reflections, and the storyboard sheet that followed it; both are in git history.
- **Weeks** is the planning-ahead surface: six weeks at a glance, as a month-style grid or as one ruled row per day, Oscar's choice and remembered.
  Each day shows its planned tasks, deadlines, and personal events; the work calendar is condensed to a load figure (meetings and busy hours) rather than listed.
  Dragging a task between days replans it (sets planned_for); an Unplanned tray holds tasks with no do-date, and dragging back to it unplans.
  It supersedes the earlier seven-day next-days list.
- **Calendar** (Oscar's call on 2026-10-02, against Google Calendar, Notion Calendar and Fantastical) is the time grid of events and task blocks, as a day, three days or a week (D, X, W), the choice remembered on each device and a phone starting on three days.
  The grid runs the whole day, scrolled within the window to the usual day (06:00 to 22:00) with now in view; Left and Right step by the days shown, and a switch keeps today in view.
  Items starting within half an hour of each other sit side by side; one starting later is laid over those still running, stepped in, so each keeps its width and its title.
  A meeting called off (Outlook's "Canceled: " subject) stays in its place, struck through, and takes no time: free slots and Weeks' load pass over it.
  A click on an event opens its card: when and where, a meeting link as its Join button.
  Oscar's own events are changed and deleted there (one of a series alone, or it and the later ones), and dragged and resized on the grid as blocks are; work meetings stay read-only.
  Drawing on the empty grid, or clicking an hour, writes an event there in the composer, whose title takes the task sheet's words ("saturday", "at 7pm", "every week"); New event (E) opens it on its own, all day until given a time.
  Over a time drawn, the tasks to schedule in the days shown are offered too, narrowed by the words written, and the one picked takes the time as its block.
- **A project as a Gantt chart** (Oscar's call on 2026-09-30: "I work in weeks", "a kind of Excel interface"): each project opens (`/projects/<id>`, from its card's bars icon) as a spreadsheet of its plan by week.
  A row per workstream, its tasks under it and a row to write one more; then the other tasks, and a row to write a workstream; a column per week (the ISO week, over its Monday), frozen beside Task, Start, Wks and Due.
  It drills down to days (Oscar's call on 2026-10-01): a Weeks / Days switch (or V) for the whole sheet, remembered, the same days kept in view; in Days a column per day, weekends tinted, the length in days, and every move by days.
  A task's bar is its span: from its start day to its due, so the end of a bar is its deadline, and the Tasks page, nudges and Weeks see the plan through the due they already read (Oscar's call: a task has to be done by a day).
  The do-date stays apart: when Oscar works on it, not when the plan says it runs.
  A task due with no start is a tick on its due; a workstream is a lane: a summary from its tasks' first start to their last due, its Start, length and Due theirs.
  A workstream folds to its row (its chevron, or Alt+Left and Right on it; Alt with the chevron folds or opens them all), its row then counting its tasks, and stays folded in that browser (Oscar's call on 2026-10-01).
  It is worked as a spreadsheet: a cell cursor, typing writes over a cell (a title; a week as "42", "W42", "12 Oct" or "next week"; a number of weeks; a due, a week there meaning its Friday), Enter goes down and Tab across, Shift holds a range, Space draws the bars over the weeks held, a drag over a task's weeks draws its bar, a bar's middle drags it and its ends stretch it, Alt+Left/Right move bars a week, Alt+Up/Down move a row (into the workstream above or below), Delete clears, Ctrl+Z undoes, and pasted lines become tasks.
  In Weeks, bars are drawn to the day but move and stretch by whole weeks: a bar keeps its days as it moves, a due keeps its weekday as its bar stretches, and a bar drawn new runs Monday to Friday; typed lengths are weeks unless named ("10d"), and in Days, days unless named ("3w").
  Rows keep their order as they are edited (a spreadsheet's rows do not re-sort), their own order once moved: with Alt+Up/Down, or dragged by their number to another place or workstream (Oscar's call on 2026-10-01).
  Done tasks stay on the plan, struck through; cancelled ones and a series' finished occurrences leave it.

### The notebook (decided 2026-09-26, set aside 2026-09-27)

Set aside for the notepad above; the storage, history and MCP reading it brought stay.

Oscar's own words, from the session that decided it: Today will be kind of a notebook, written naturally; treat Today not as the database but as a notebook that sends commands to the database.
The problem it solves: a task added on Today but dated another day used to vanish from the page it was written on.
Decided with Oscar:

- One page per day; past pages stay editable.
- "- " starts a task; inside its box, "- " lines are its sub-tasks, and Ctrl+Enter ends the box.
- A task's fields are set as in the task sheet, with its icons and typed words.
- A date and a time put the task on the calendar, as a block.
- A task on the page shows its current state, and every task keeps a version history of how it changed.
- "/reflection" writes a reflection, free text only; "/" is the prefix for commands, "- " for tasks.
- Underneath: the tasks planned for the day that were written elsewhere, with their context; on today's page also overdue and Claude's work.
- Claude can read the notebook through MCP.

## 4. Domain model

Per [Domain model](tracker/tickets/008-domain-model.md). All v1 entities below; goals (v3), habits (v4), and reviews (v5) bolt on without core migration.

### Entities

**Project**: name, status (active / paused / done), notes, colour (one of the design's eight hues; a new project takes the one fewest open projects have).
Flat, no nesting.
v3 adds a Goal entity plus a nullable goal reference on Project.

**Workstream** (Oscar's call on 2026-10-01, replacing milestones: "I manage it that way"): belongs to one project; name, status (open / done).
A stream of the project's work run beside its others, a lane of its tasks with no date of its own: its span is its tasks', and its progress is computable from them.
Deleting one leaves its tasks in the project, in none.

**Task**: title, notes, status, owner (oscar / claude), optional project, optional workstream (only of its own project), optional planned_for (do-date), optional due (deadline), optional starts_on (its start week on its project's Gantt), optional position (its place among its group's rows there), optional written_on (the notebook page it was written on), optional estimate (how long its work is thought to take, a minute to a day).
An estimate is set in the task sheet (its stopwatch icon, or "45m", "1h30" or "2 hours" as the title is written), in Today's notes the same way, and by Claude; it is the length of the time the task is given on the calendar (dropped on the grid, or booked with B), an hour without one, and its weight in a day's plan.
Notes are the task's free-form description, and sub-tasks live inside it: a line starting with "- " (or "* ") is a sub-task, "- [x] " once done, and every other line is context kept where it was written.
Sub-tasks are text, not rows: they carry no status, owner, or dates of their own, and ticking one rewrites only its own line.
A repeating task's occurrences start with every sub-task open.
planned_for is the day Oscar intends to work it and drives the daily list; due is the obligation and drives urgency.
Backlog tasks have neither.
The Weeks view is driven by planned_for and due.
starts_on always comes with a due, never after it: its span is its start day to its due, a start given alone ends that week's Friday (or on itself at a weekend), a due cleared takes the start with it, and a due moved before the start pulls the start back to its week's Monday.

**Block**: belongs to one task; start, end, state (planned / completed / missed).
A task accumulates blocks over time (missed Tuesday, re-slotted Thursday).
The missed marker and the ghost outline both derive from block state; missed is a block-level fact, never a task status.

A task's time is a block on its do-date: giving a task a time (in the sheet, or "at 3pm" as it is written) creates, moves or removes that block, an hour long unless an end is given.

**TaskRevision**: one step in a task's history: when, who (oscar, claude or system), the kind of change (created, updated, deleted), and the task's fields as they stood after it.
Recorded by the ORM on every flush that touches a task, whatever path made the change, and kept after the task is deleted; the history started on 2026-09-26 with a baseline of every task as it stood.
It is shown under the task's sheet and read by Claude through `get_task_history`.

**NotebookPage**: one per day; its blocks in the order they were written and a version (text, tasks by reference, reflections, habits, and stays, whose items are read from their "- [ ] name: value" lines). Today's notepad writes it as one text block; a page written in the notebook's time (with task references and reflections) reads back as text.
A save names the version it was made from, and a save from an older copy is refused, so two windows never silently overwrite each other; the page asks which to keep.

**Event**: title, start, end, all-day flag, source (local / work), read-only flag, external id.
One entity for own and external events: work-calendar events are rows with source=work, read-only, upserted by external id.
One calendar query, one rendering path; removing the integration deletes rows by source.

**RecurrenceTemplate**: a rule (frequency, interval, weekday selectors) attached to a task template or a local event template.
A daily generator job materializes real instance rows over a rolling horizon of about 8 weeks.
Each occurrence is its own task/event row, individually checkable and editable, carrying its template reference and occurrence date.
Habits do not use it (see Habit).

**Habit**: a name (lower case, hyphens: `morning-skin-care`) and its days, the weekdays it is due (Monday 0 to Sunday 6; "" for any day).
**HabitCheck**: a habit on a day, done or skipped, with its note; one per habit per day.
A day's checks are its notebook page's: each save of the page writes them from its habit blocks and removes those no longer on it, and a habit left with no checks and no days of its own (a name typed on the way to another) goes too.
A day is missed when it is one of the habit's days, since the habit began, the day is past, and nothing was written.

**SessionActivity** (v2): session id, project, started/ended timestamps.
The deterministic "session happened in project X" trace from the hooks layer.

### Task lifecycle

One shared lifecycle for every task regardless of owner: todo, in_progress, blocked, needs_review, done, cancelled.
The Delegated-to-Claude chips map onto it: queued = todo, running = in_progress, needs review = needs_review.
needs_review is a first-class state, also usable for Oscar's own review-me tasks.
The owner field is the only AI/human distinction; richer provenance (session ids, intake path) stays off the task record.

## 5. Work calendar integration

Per [Decision: work calendar integration mechanism](tracker/tickets/012-work-calendar-decision.md), with the branch settled by [Probe the work tenant's calendar routes](tracker/tickets/014-probe-work-tenant.md):

- **Route: published ICS feed, confirmed live.**
  The tenant offers "Publish a calendar" in Outlook settings; Oscar published at the "Can view titles and locations" level.
  The feed is an anonymous plain GET; verified end-to-end (555 events, titles and locations present, no bodies or attendees).
- The feed URL lives in `local/work-calendar-ics-url.txt`, git-ignored; the app reads it from config, never from the tracker or repo history.
- **Detail stored**: subject, start/end, location only.
  No bodies, attendee lists, or attachments in the personal database, regardless of what the route offers.
- **Polling**: a few times a day, morning-weighted (for example early morning, midday, late afternoon).
  Freshness need is a morning snapshot; intraday changes are seen in Outlook anyway, so publish lag is acceptable and was not measured.
- **Source interface**: the work-calendar source sits behind a small interface so Graph delegated auth (auth code + PKCE via msal, per the [research](tracker/research/outlook-calendar.md)) can swap in later without touching the rest of the app.
  No Graph work and no IT ask in v1.
- Parsing: `icalendar` plus `recurring-ical-events` to expand recurring meetings into concrete occurrences before upserting by external id.

## 6. AI integration

Per [Decision: AI integration architecture](tracker/tickets/007-ai-integration-decision.md), grounded in the [MCP research](tracker/research/mcp-integration.md) and [session-capture research](tracker/research/session-capture.md).

### Planner interface (v1)

- A FastMCP 3.x server mounted inside the FastAPI app, sharing the one database with the REST API and web UI.
- Transport: local streamable HTTP on localhost; no auth locally (see section 8).
- v1 client surface is Claude Code only, via a user-level MCP config.
  Claude Desktop and claude.ai can be added later without server changes (claude.ai needs HTTPS+OAuth, deferred).

### Auto capture (architecture fixed now, ships in v2)

Not a raw session-event feed: what flows in is project-level plan state, so the app can surface what needs working in the next days and each project's backlog.
Two layers, both machine-wide across all projects:

1. **Semantic layer (primary)**: project-plan MCP tools on the app's server, shaped like `upsert_project`, `upsert_tasks`, `update_task_status`.
   A user-level MCP config plus a standing CLAUDE.md instruction has sessions push their project's current state (done / next / blocked) after meaningful work or a planning pass.
2. **Deterministic layer (backup)**: SessionStart/SessionEnd hooks POST a minimal "session happened in project X at time Y" record, keyed by cwd.
   A session that never calls the tools still leaves a trace, feeding the activity-without-plan-update nudge.

Failure handling: hooks spool events to disk when the POST fails; the app ingests the spool backlog at startup (spool and replay).
Hook commands need a short HTTP timeout so a down app never delays sessions.

### Notebook and history

- `get_notebook(start, days)` reads Oscar's notes for each day (his notepad: prose, the tasks he wrote there, reflections, the habits he checked, and where he stays, each stay's items as name, value and sorted or not).
- `get_habits(start, days)` reads each habit day by day: done, skipped, missed, or nothing (not due, or today still open), with his note.
  `get_agenda` carries each day's page in brief too, so planning with Claude starts from what Oscar wrote.
  The notebook is read-only to Claude: it is Oscar's own writing.
- `get_task_history(task_id)` reads how a task changed and who changed it; Claude's own changes are named as Claude's.

### Nutrition chat

Oscar's call on 2026-09-30: Nutrition is tracked by day, and a chat with Claude on the page keeps the record.

- **Markdown is the record.** Nutrition lives in a folder of Markdown files (`[nutrition].dir`, `nutrition/` in the repo): `plan.md` (the plan, its daily targets in its YAML front matter, each an aim, a min or a max), `meals/` (recipes) and `log/YYYY-MM-DD.md`, one per day.
  A day's front matter holds its meals, each eaten or planned, and each item's amount (marked when assumed) and six nutrients (kcal, protein, fat, saturated fat, carbs, fibre); under it, short Notes and Next sections.
  The app never stores a total: it sums the items, so totals cannot drift from them.
  The files are outside the database and its backups; git holds their history.
- **Claude through the Agent SDK, on this machine's Claude Code login.** Each message is one stateless run of the Claude Agent SDK (`app/services/nutrition_agent.py`), driving the installed Claude Code CLI, so no API key is needed.
  Its world is the nutrition folder: its tools are the file tools and web search, a PreToolUse hook denies any path outside the folder, and no setting, CLAUDE.md, skill or MCP server of the machine's reaches it.
  The prompt carries the time, the day, Oscar's Health > Me profile and the day's chat so far; the files carry everything else.
- **The chat is the day's.** Messages are stored by day (`nutrition_messages`); each day starts a fresh chat.
  A run goes on in its own thread after its page closes, and its answer is saved; one run at a time per day.
- **The log stays readable.** After a run the day's file is read back; if it does not follow the format, Claude gets one unseen turn to fix it, and a file that still cannot be read is shown as such, with why.

### Garmin

Oscar's call on 2026-09-30: the app connects to his Garmin metrics.

- **Through python-garminconnect, signed in as Garmin's own app.** Garmin's official API is for businesses only; the library signs in as the Garmin Connect mobile app does (garth, which it used before, is deprecated since Garmin changed its sign-in).
  Connecting is in the app (Health > Garmin): email and password, then the code Garmin sends when the account asks for one.
  The password signs in once and is never stored; Garmin's token is kept in `[garmin].token_dir` (git-ignored `local/garmin/`) and refreshed by the library.
  When Garmin stops honouring it, the token is deleted and the page asks to sign in again; the days already synced stay.
- **Kept by day in the database.** `garmin_days` holds each day's steps, energy burned (total and active), intensity minutes, resting heart rate, stress, body battery, the sleep that ended that morning with its stages and score, that night's HRV and the morning's training readiness; `garmin_activities` the activities.
  A figure Garmin does not have is null, and a request that fails leaves what was kept before.
- **Synced by the scheduler** every `[garmin].sync_minutes` (30) and on demand: the first sync reaches `backfill_days` (30) back, each later one from the day before its last, so yesterday settles and a gap while the app was off is caught up.
- **Read by Claude.** `get_garmin(start, days)` over MCP; `get_health_profile` carries the energy his Garmin measured him burning a day (the average of his last 14 full days worn, from 7 of them), which Me shows beside the estimate; and Nutrition's chat gets the day's and the day before's figures in its prompt.

### Finances

Oscar's call on 2026-09-30: the app keeps his money, fed by his banks' CSV exports, with Claude in a chat on Spending.

- **The database is the record**, unlike Nutrition's files: exports become rows, amounts whole cents in Australian dollars (out negative), in `money_*` tables backed up with the rest.
- **His banks' exports, imported by hand on Accounts.** Revolut and ING Australia, told apart by their header line (`app/sources/bank_csv.py`).
  Revolut rows count once COMPLETED and in AUD, a fee taken off its row; the others are counted as left out, with why.
  Each row's fingerprint is its day, amount and description with how many identical rows came before it in the file, so importing an export twice, or two that overlap, adds each transaction once.
  Every day's closing balance in an export becomes its account's balance that day, so net worth has its history from the first import.
  The column layouts come from the banks' published formats; the first real export of each confirms them.
- **Sorted into categories**: spending, income, or transfer (money between his own accounts, in neither).
  A rule sorts every transaction whose description holds its words as it is imported (the longest match wins), and the unsorted ones when it is added; a Revolut top-up is a transfer.
  Categories begin from a starting set on first use; a spending category may have a budget a month.
- **A month** is what was spent by category against its budget, what came in, what is left, what moved between accounts (counted once when both sides are imported), and what is not sorted yet, unsorted money counting in the totals.
- **Net worth** is each account's latest balance summed, a card's or loan's as owed; balances without an export (super, shares) are written by hand.
- **Bills** come round by their cadence from any one due day (weekly, fortnightly, monthly on the day or the month's last, quarterly, yearly).
  A bill is seen paid by money out within five days of a due day whose description holds its words.
  A bill due within three days and not seen paid raises a nudge, and is in the morning digest.
- **Goals** are a target, by a day or not, kept in an account (its balance is the progress) or counted by hand, with what a month gets there.
- **Claude through the Agent SDK**, as Nutrition's chat is (`app/services/money_agent.py`), one stateless run per message, the month's chat so far in its prompt.
  Its world is the tools of `app/services/money_tools.py`, run in the app's process on its database: read a month, find transactions, sort them, add rules, categories and budgets, write balances, and keep bills and goals.
  It has no files and no shell, and no setting, CLAUDE.md, skill or MCP server of the machine's; it can search the web.
  The chat is the month's (`money_messages`); a run goes on after its page closes, one at a time per month.
- **Read by Claude elsewhere** through `get_finances(month)` over MCP.

### Plan truth

- The app database is canonical for cross-project plan state.
- Repo trackers (wayfinder maps and the like) remain per-project working artifacts, not synced or mirrored.

### Manual entry

The web UI writing to the same database; nothing extra to build.

## 7. Nudging and notifications

Per [Decision: AI nudging and notifications](tracker/tickets/013-ai-nudging.md):

- **Triggers (rule-based, no Claude in the loop)**:
  1. Missed blocks: a scheduled block passed uncompleted; nudge to replan.
  2. Activity without plan update (arrives with v2 data): sessions ran in a project but no MCP plan update followed.
  3. Upcoming due dates within about 3 days, task not done.
  4. Needs-review backlog: tasks sitting in needs_review beyond a threshold.
  5. A bill of Finances due within about 3 days and not yet seen paid; its nudge retires once a payment is seen.
- Nudges are templated by APScheduler jobs; Claude remains the planner Oscar talks to, not a background voice.
- A task's nudge shows only while its fact still holds: replanning a missed task, finishing a task, or clearing its review retires the nudge without a dismissal.
- **Channels**: an in-app nudge center (inbox/banner, each nudge dismissable or actionable) plus phone push via a relay.
  Windows toasts explicitly not used.
- **Cadence**: a morning digest bundles the day's shape, missed blocks, upcoming dues, and review backlog.
  Only genuinely time-sensitive items (due-today slipping, a block just missed) break through during the day.
  Quiet hours are configurable.

## 8. Architecture

Per [Architecture](tracker/tickets/009-architecture.md) and [Decision: security and remote access](tracker/tickets/015-security-remote-access.md).

### Framework and process

- One FastAPI process serving the web UI, the REST API, and the mounted FastMCP server against one database.

### Storage

- SQLite in WAL mode, a single database file.
- SQLAlchemy for models, Alembic for migrations.
- Zero-admin, file-copy restore; sufficient for single-user write load.

### Frontend

- Server-rendered: Jinja templates plus HTMX for pages, lists, and forms; no build step, state server-side.
- Real client JS is limited to a few focused vanilla islands, each built well once: the calendar (its grid and Today's timeline: drag-to-slot, drawing and writing events, their cards), drag-to-replan on the Weeks view, the task sheet (one editor for adding and editing, with its line-based description editor), Today's notebook (the same line editor in prose mode, with the sheet as its task box), and the chats with Claude on Nutrition and Spending (the answer streamed as it is written).

### Background jobs

APScheduler inside the FastAPI process; jobs share app code and database sessions:

- Daily recurrence materialization (8-week rolling horizon).
- Work-calendar ICS poll, a few times a day, morning-weighted.
- Hook-spool ingestion at startup (v2).
- Nudge trigger evaluation and morning digest.
- Daily backup snapshot.
- Garmin sync, every half hour while connected.

### Deployment and backups

- Auto-starting background service on Windows (NSSM or Task Scheduler at-logon, hidden window); the app is effectively always up, which the hook-spool design assumes.
- The in-app daily backup job uses SQLite's backup API to write dated snapshots into a cloud-synced folder; retain about 30.
- Restore is copying a snapshot back over the database file.

### Security and remote access

- **Tailscale overlay**: the app binds localhost plus the Tailscale interface; Oscar's phone joins the tailnet and gets the full web UI anywhere.
  WireGuard-authenticated, zero public exposure, no port forwarding.
- **No app-level login**: localhost and the tailnet are the trust boundary; MCP and REST stay authless locally.
- **Browser-side hardening**: middleware rejects requests whose Origin/Host headers are not the app's own (closing DNS rebinding and cross-site XHR against localhost); standard CSRF tokens on HTMX form posts.
- **Push relay**: managed ntfy.sh with an unguessable topic name plus access token.
  Task titles transiting ntfy's server is accepted for personal use; self-hosting ntfy on the tailnet is a drop-in swap later.
- **Data at rest**: the SQLite file, hook spool, and backup snapshots are protected by OS user permissions; no additional encryption.

## 9. Out of scope

- Google Calendar integration, in any direction ([decision](tracker/tickets/006-google-sync-decision.md)).
- Writing to or editing the work calendar; work-event bodies and attendees in the personal database.
- Native mobile apps; the phone gets the web UI over Tailscale.
- Claude authoring nudges or acting as a background voice.
- Building the app itself was out of scope for the map that produced this spec; it is exactly what starts from here.

## 10. Standing preferences for the build

- Weigh quality, simplicity, robustness, and long-term sustainability over development cost.
- Be picky about UI quality; pixel-perfection matters to Oscar.
- Fix lint, test failures, and flakiness on sight.
