# Personal Calendar: build-ready spec

A locally-run, Python-backed web app that unifies calendar, to-dos, and projects (with goals, habits, and reviews phased in) as Oscar's control panel for his life and his AI.
This spec is the destination of the wayfinder map in [tracker/map.md](tracker/map.md).
Every section gists a decision made on that map and links the ticket that holds its full reasoning; the tickets are the authority when detail here feels thin.

## 1. Product shape

- Single user (Oscar), single machine (Windows 11), a desktop app (the web UI in a window of its own; the phone gets it in its browser), no cloud backend.
- The app is the canonical store for personal plan state: projects, tasks, events.
- Claude is a first-class client: it reads and writes the plan through MCP from day one.
- The work calendar is visible read-only inside the app; the app never writes to it.

## 2. Phasing

Per [v1 phasing](tracker/tickets/002-v1-phasing.md):

- **v1**: the hybrid planner: calendar (events), todos, projects with workstreams, manual entry, recurrence for both events and tasks, the work-calendar ICS feed, the MCP planner interface, nudges (three of four triggers), Tailscale phone access.
- **v2**: automatic capture of Claude Code session work (MCP plan tools as the semantic channel, lifecycle hooks as the deterministic trace); enables the fourth nudge trigger.
- **v3**: goals, which projects roll up into.
- **v4**: habits and routines. Habits came early (Oscar's call on 2026-09-27): written in the notepad as "/habit name" (see Today), kept as their own entity rather than recurring tasks, so they never crowd the task lists; Calendar's sheet shows when each was done and missed, a column a habit.
- **v5**: reviews and reflection flows.
- **Health** (Oscar's call on 2026-09-28): a module beside the planner, its own group in the nav, starting with Nutrition (see [Nutrition chat](#nutrition-chat), Oscar's call on 2026-09-30) and Me, the context health advice needs: height, birth date, sex, activity level, goal and target weight, dietary pattern, allergies and intolerances, foods avoided and health notes, saved as they change, and weight as a log of weigh-ins, one a day; from them, age, BMI and an estimated daily energy to keep his weight (Mifflin-St Jeor times the activity's factor). Claude reads it through `get_health_profile`.
  Then Garmin (Oscar's call on 2026-09-30, see [Garmin](#garmin)): what his watch measures, day by day, synced from Garmin Connect.
- **Finances** (Oscar's call on 2026-09-30, see [Finances](#finances)): a module of its own in the nav, beside Health: Spending (a month against its budgets, beside a chat with Claude), Accounts (net worth, balances, his banks' exports), Bills and Goals.
- **Code** (Oscar's call on 2026-10-04, see [Repositories](#repositories)): a group of its own in the nav, starting with Repositories, the GitHub repositories he can reach, synced from GitHub.

Review flows are deliberately unspecified here; they sharpen as their phase nears (see the map's Not yet specified section).

## 3. Planning interaction model

Per [Planning model](tracker/tickets/001-planning-model.md), decided against interactive prototypes ([asset](tracker/prototypes/planning-model.html)):

- **Tasks take no time on the calendar** (Oscar's call on 2026-10-02, after the blocks went unused): to-dos live in lists and on their days; the calendar shows events alone.
  Task blocks went with it: the To schedule tray, giving a drawn time to a task, Book, a task's time in the sheet, Today's focus card, and the missed marker with its replan, nudge and ghost outline (all in git history).
- **Delegated to Claude** is a list section with status chips (queued, running, needs review), not a calendar lane.
- **Projects is the one screen for tasks** (Oscar's call on 2026-10-02, replacing the Tasks page and its By date / By project views): every open task of Oscar's on one sheet, its first row the composer, then the tasks in no project, then each active project's card (workstreams, then Add a workstream with the tasks in none under it, each card with its quick add and its status), the paused and done projects on shelves, and the Done fold.
  Each row names its do-date and has one-click Today and Tomorrow buttons and a date picker; rows go soonest first (do-date, then deadline, then oldest), and a repeating series shows only its next occurrence.
  A new project is named at the header's right; a status moves its card between the active projects and the shelves.
- **Projects at a glance** (2026-10-03, after the portfolio views of Linear, Asana and Things): above the tasks, a row for each active project, then each paused one, as a portfolio list.
  Each row gives the project's health, its progress (tasks done of all, cancelled ones aside), its next deadline, and its span (its tasks' first start to their last due) on twelve weeks shared by every row, from last week's Monday, with now marked.
  Health is read from the deadlines, not set by hand, since one person has no one to report to: "N overdue", "Due soon" (within three days), "On track", "No deadline" or "Nothing open"; a paused project is "Paused".
  The name opens the project's page.
  The app opens on Today (`/` goes there); dates are planned on Today and each project's Gantt.
- **Done folds away**: finished tasks leave their lists for a collapsed Done fold, at the foot of Projects (the last 14 days), where unticking one sends it back.
- **Sub-tasks** live in their task's description and tick off on its row; workstreams hold tasks, never sub-tasks.
- **A task is an object with its own page** (Oscar's call on 2026-10-03: "I'm writing very long tasks"): `/tasks/<id>` opens a task on a screen of its own, for one too complex for its row.
  The page is the task sheet as a document: the title as its heading with its box, every field on one line under it (do date, due, repeat, estimate, priority, project, owner, status, History and the bin), then the description at length.
  It saves as it is written (a moment after the writing pauses, as a field is chosen, and as the page is left; Ctrl+S, Ctrl+Enter or Esc at once), and goes back to the page it was opened from, named ("‹ Calendar"), or Projects; deleted, it goes back there too.
  It opens from Calendar's sheet first (a Plan cell's task title, or Ctrl+Enter); the other places tasks are listed follow.
- **The command menu** (Oscar's call on 2026-10-02, after Akiflow and Notion Calendar): Ctrl+K (or Cmd+K) anywhere, or Search in the rail (the phone's tab bar), is one line to find and go.
  It finds tasks (open first, by their words or their description), projects, events (a series once, at its meeting nearest now) and the days' notes; a task found opens Projects with the cursor on it, a project its page, an event its day on Calendar with its card open, and notes their day.
  A day's words ("friday", "tomorrow", "12 oct", "2026-10-12") go to that day on Calendar or to its notes; every page is there by name, and the things to do from anywhere (a new task, a new event, the theme, compact rows, the keys).
- **Triage by keyboard**: on Projects, arrow keys move a row cursor and single keys act on it (T today, M tomorrow, D pick a day, X done, E edit), the cursor moving on to the next row as each one is dated or finished.
- **A task's project is its colour** (Oscar's call on 2026-09-28, chosen from a prototype of four): each project has a colour, set in its editor on Projects, and a task in it shows the project as its flag filled in that colour, the name only on hover, wherever tasks are listed.
  In Today's notes the task's rules take the colour too, and on Projects its row's rule.
- **Seeing more** (Oscar's call on 2026-09-28; the browser's zoom stays the browser's): compact rows (C, or the rail's toggle) fit more of Projects and Today's notes on screen at the same text size; Today and Calendar widen with the window; and on Today, Ctrl+\ (or the day header's icon) folds the timeline away for the notes. All three are remembered.
- **The sidebar is Oscar's to lay out** (Oscar's call on 2026-10-04: "I want to be able to move modules. And hide them."): its sections (Planner, Projects, Health, Finances, Code) and the pages in each are dragged into his order, and the projects under Projects into theirs, which is Projects' order too.
  A page never moves to another section.
  Each page has a hide eye beside it, and a section goes once all its pages are hidden; Settings, at the sidebar's foot, lists the hidden pages to bring back.
  The layout is kept in the database, so it holds on every device; a hidden page is still found by the command menu.
- **Back goes to where Oscar was** (Oscar's call on 2026-10-04: "Add a BACK-BUTTON that works with context"): the desktop app has no browser bar, so Back sits at the top of the sidebar, named after the page before ("Back to Garden Planner · Gantt"), with Alt+Left and the mouse's back button doing the same.
  The page comes back as it is now, never a stale copy (no page the app serves is cached), and as it was left: scrolled where it was, a Gantt's or Calendar's sheet with its cursor on the same cell and the same rows and weeks in view, Calendar's hours where they were, Projects' cursor on its row.
  A page's own "‹" link (a task's, a project's, a document's) goes back the same way when the page before is the one it names, and a task deleted on its page goes back to where it was opened, as it was left.
- **Alt and a number go to a page** (Oscar's call on 2026-10-04: "do with ALT-1, ALT-2 to move between modules, not just the number"): Alt+1 to Alt+9 are the sidebar's pages as they show, top to bottom, hidden ones skipped, so the numbers follow the layout as it changes.
  The current page wears its number in a small disc at its start, and holding Alt shows every page's; a digit alone no longer goes anywhere.
- **Every version says what it changed** (Oscar's call on 2026-10-04: "Create changelog & features/bugs applied per version"): Settings names the running version and the commit it was built from, and opens the Changelog, a page listing every version, newest first, with its changes, each a Major, a Feature or a Fix.
  Each pull request adds its changes as a file in `changes/`; versions are numbered from the order master took them in, never by hand (README, Recording a change).
- **A machine has the modules ticked when installing** (Oscar's call on 2026-10-04: "I want to use this for work without Finances"): the installer's Modules page lists Health, Finances and Code, each ticked to start with; Planner and Projects are always in.
  A module left unticked is not in that machine's app at all, unlike a hidden page: no pages, no keys, no Claude tools (and no words about them in the MCP server's instructions), no syncs, no nudges, and no Garmin figures on Today.
  The choice is the installer's `install.toml` in the app's home (`[install] without`), remembered by Setup for the next install; running Setup again changes it, and Settings names the modules not installed.
  Their data is not touched: a module installed again finds what it had.
- **Filing by drag**: on Projects a task is dragged onto a workstream, another project, or No project to file it there.
- **Today is a notepad beside the day's timeline** (Oscar's call on 2026-09-27, "for now"): the whole left column is one plain notepad for the day, the right the day's timeline.
  The notes are plain text, saved as they are written.
  A row too long for the box wraps inside its row; nothing scrolls sideways.
  Spelling is marked only in the row being written (Oscar's call on 2026-09-28): a row left, and every row once out of the notes, shows no marks; the task sheet's title and description lines likewise.
  A task is written in them: "- [ ] " at a row's start makes the row a task, drawn indented as a checkbox and "Task" (not text); the rows added under it with Enter are indented the same way and are its description, and "- [ ] " on one of them makes it a sub-task, with its own box; plain rows stay at the left.
  A ticked sub-task is crossed out, and a ticked task, title and rows; a sub-task's tick is written to its task's description at once.
  Writing a task never needs the mouse (Oscar's call on 2026-09-28): Tab and Shift+Tab stay in the notes, Tab going from a task's title to the row under it (a new one when it has none), taking a plain row right under a task into it, and making a task's row a sub-task, Shift+Tab stepping back out; and as in the task sheet, "friday", "due friday", "every week" or "30m" and a space in a task's title set that field, a title's last words taken as it is closed; since a word can be meant as a word, each is an undo step of its own that Ctrl+Z (or Backspace straight after) takes back with its field, the words then staying words, and a title closed with words taken says so in its toast ("Task added: Book flights, due Fri 2 Oct"), with Undo.
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
  The day's tasks come to its page (Oscar's call on 2026-10-02, after the page showed none of the three due that day): under the notes, "For today" lists Oscar's open tasks planned for the day or due on it, on today's also those whose do-date or due has passed, deadlines first, then by priority, each due one saying so ("due today").
  What was left open comes along too (Oscar's call on 2026-09-28): on today's, the tasks still open from the last page before it that holds tasks, those to be worked by today (no do-date, or one not after it), join the list once.
  A task already written on the page is not offered; a past day's page offers none, and a later day's those planned for it or due on it ("For tomorrow").
  A title writes the task's rows at the end of the notes, its title row that same task (not a copy) and its description its rows, and moves its do-date to the page's day; Bring all writes every one.
  The earlier page keeps its rows as written, each showing its task as it stands, so a task finished today reads ticked there too.
  Where Oscar stays is written in them too (Oscar's call on 2026-09-27: he moves around, and does not always have a bed sorted): "/stay" on a day's page, then its items, each "- [ ] name: value" with a box ticked once sorted, bracketed in amber.
  Its items are his to name (place and accommodation to begin with; a new stay starts with the items the last one had), and under the date the day's stay reads item by item, the unsorted ones in amber.
  A stay is written day by day, not as a range; Calendar's sheet shows the days' stays together, and fills one down the days.
  Every day has its notepad: Left and Right (outside the text) go a day back or on, and past days stay editable.
  A glance under the date (Oscar's call on 2026-10-02, after Oura's and Garmin's morning scores and Notion Calendar's next meeting) reads the day at once; whether its plan fits is the timeline's line above its hours.
  On today's it names the event on now (till when) and the next (in how long), each with its meeting link's Join; a cancelled meeting and an all-day event are passed over.
  Then how Oscar came into the day, from his watch: readiness (a low one, Garmin's POOR or LOW, asking to keep the day light), sleep and its score, and body battery; a past day's page shows its own.
  Today's is redrawn each minute and as the calendar changes.
  On a phone the page stacks: the header with its glance first, so the next thing on is the first thing seen, then the notes and their lists, then the timeline in a window of its own (75% of the screen), opened on now.
  N writes a new task from Today in the capture window, as on Calendar.
  Today's page opens with the nudge center, above the notes, each nudge saying its days from today ("due today" for one raised yesterday as "due tomorrow").
  It replaces [the notebook](#the-notebook-decided-2026-09-26), where lines became tasks and reflections, and the storyboard sheet that followed it; both are in git history.
- **Calendar** (Oscar's call on 2026-10-02, against Google Calendar, Notion Calendar and Fantastical) is the time grid of events, as a day, three days or a week (D, X, W), or the sheet of days (S), the choice remembered on each device and a phone starting on three days.
  The grid runs the whole day, scrolled within the window to the usual day (06:00 to 22:00) with now in view; Left and Right step by the days shown, and a switch keeps today in view.
  The title names the ISO weeks shown after the days ("W40", "W40–41"), as the Gantt counts weeks, and a calendar icon after the steps (or G) picks any date to go to.
  Each day to come says whether its plan fits it (Oscar's call on 2026-10-02, after Sunsama): under its head (and above Today's timeline), its planned tasks, by their estimates, against the time its meetings leave free in its usual hours (today's from now), a warn badge when they do not fit; the meetings' time is in the tooltip.
  Items starting within half an hour of each other sit side by side; one starting later is laid over those still running, stepped in, so each keeps its width and its title.
  A meeting called off (Outlook's "Canceled: " subject) stays in its place, struck through, and takes no time: free slots pass over it.
  A click on an event opens its card: when and where, a meeting link as its Join button.
  Oscar's own events are changed and deleted there (one of a series alone, or it and the later ones), and dragged and resized on the grid; work meetings stay read-only.
  Drawing on the empty grid, or clicking an hour, writes an event there in the composer, whose title takes words as the task sheet's does, and a time ("saturday", "at 7pm", "every week"); New event (E) opens it on its own, all day until given a time.
- **Calendar's sheet** (Oscar's call on 2026-10-02, after the Excel sheet he planned his days in: "a view that is kind of Excel like", habits drawn on it) is the days as the rows of a spreadsheet, a fourth view beside the grid's three.
  It shows four weeks from a Monday: opened on today, last week first, so the days just gone sit above those to plan; Left and Right (outside the sheet) step four weeks.
  A row a day: the day (a link to its notes), where Oscar stays (a column per item of the stays shown, place and accommodation to begin with), Plan, and a column per habit.
  A stay's cell is its item's value; writing in it writes the day's stay as "/stay" in its notes would (a day with none gets one at its page's top, with the items the last stay had).
  Accommodation is a checkbox (Oscar's call on 2026-10-03, as his Excel's AC column): its box alone, ticked once sorted (edged amber while a stay has it unsorted), ticked as a habit is, its words kept in the notes and its tooltip.
  Plan is the day's tasks, Oscar's planned for it (done ones struck through) and then those still open due on it ("due", urgent once due within three days or past), each in its project's colour and by priority, and then his own events, all day first (work meetings stay on the grid); writing in it adds a task planned for the day.
  A task's box is clicked through its work (Oscar's call on 2026-10-03): a click starts it (in progress, the box filled inside), the next makes it done, one more takes it back to to do; a chevron beside the box opens the statuses it can be given here, In progress and Done, the one it has chosen again taking it back to to do.
  A task's title opens its page, as Ctrl+Enter on a Plan cell opens its first task's; writing a task, Ctrl+Enter writes it and opens it, to be written out there (Oscar's call on 2026-10-03).
  A task is deleted from its bin at its line's end, or with Delete on its day's Plan (every task of the range's plans), asking first as Projects does.
  A habit's cell is filled green with a tick on a day it was done, an empty box when skipped and a dash when missed; a click or Space ticks it (written in the day's notes after its habits, as "/habit name" would be) or unticks it (its rows leave the notes), and a drag down its column (or accommodation's) paints every day it crosses as the first was turned.
  A day whose plan runs over a line folds to its first (Oscar's call on 2026-10-03), the line saying how many more ("+5"): its chevron before the date, or Alt+Left and Right on it (or a range of days); Alt with a chevron, or the Day header's, folds or opens them all, and folded days stay so in that browser.
  It is worked as the Gantt is: a cell cursor, a range with Shift or a drag, typing writes over a cell, Enter writes in it and keeps it going down, Esc lets it go; Ctrl+D fills the range from its first row (one cell, from the row above), and Delete clears the range's stays, unticks its habits and deletes its plans' tasks (after asking).
  A new event from the command menu opens the week instead, its composer being the grid's; the sheet stays the choice.
- **A project has its own page** (Oscar's call on 2026-10-04: "Projects need their own context"): `/projects/<id>`, opened from its name on Projects, from the sidebar and from the command menu, with its Gantt as the page's second tab.
  The page is one ruled sheet, as Me's is, saved as it changes: the project (name, status, colour, notes), its repositories, and its context.
  A repository is where the project's code is, a local folder or a URL, as written; it is named after the last part of it.
  The context is the documents an agent working on the project reads, in Markdown: its AGENTS.md first, which every project has and which keeps its name, then any others Oscar adds and names.
  Each document opens on a page of its own (`/projects/<id>/docs/<doc>`), written on a ruled, numbered sheet as Today's notes are and saved as it is written; any but AGENTS.md is renamed in its heading and deleted from its bin.
  The context is what the app will hand a Claude session it starts on the project (to come); for now Claude reads it over MCP (`get_project_context`), and the API serves it at `/api/projects/<id>/context`.
- **A project as a Gantt chart** (Oscar's call on 2026-09-30: "I work in weeks", "a kind of Excel interface"): each project opens (`/projects/<id>/gantt`, the Gantt tab of its page, or its card's bars icon) as a spreadsheet of its plan by week.
  A row per workstream, its tasks under it and a row to write one more; then a row to write a workstream, the tasks in none under it and a row to write one more; a column per week (the ISO week, over its Monday), frozen beside Task, Priority, Start, Wks and Due.
  It drills down to days (Oscar's call on 2026-10-01): a Weeks / Days switch (or V) for the whole sheet, remembered, the same days kept in view; in Days a column per day, weekends tinted, the length in days, and every move by days.
  The sheet takes the whole window, and its time always fills it to the right edge, however wide the window or far out its zoom: zoomed out, more weeks ahead come into view (Oscar's call on 2026-10-04: "Always fill in the entire screen so I can see more weeks in the future").
  A week's head names its year only where the year turns ("W1 '27", then "W2"), as its Monday's names the month.
  A task's bar is its span: from its start day to its due, so the end of a bar is its deadline, and Projects and the nudges see the plan through the due they already read (Oscar's call: a task has to be done by a day).
  The do-date stays apart: when Oscar works on it, not when the plan says it runs.
  A task due with no start is a tick on its due; a workstream is a lane: a summary from its tasks' first start to their last due, its Start, length and Due theirs.
  A workstream folds to its row (its chevron, or Alt+Left and Right on it; Alt with the chevron folds or opens them all), its row then counting its tasks, and stays folded in that browser (Oscar's call on 2026-10-01).
  It is worked as a spreadsheet: a cell cursor, typing writes over a cell (a title; a priority as "high", "h" or "2", or chosen from its menu with Enter; a week as "42", "W42", "12 Oct" or "next week"; a number of weeks; a due, a week there meaning its Friday), Enter goes down and Tab across, Shift holds a range, Space draws the bars over the weeks held, a drag over a task's weeks draws its bar, a bar's middle drags it and its ends stretch it, Alt+Left/Right move bars a week, Alt+Up/Down move a row (into the workstream above or below), Delete clears, Ctrl+Z undoes, and pasted lines become tasks.
  A task is deleted from its bin at its Task cell's end, or with Delete on Task (every task of the range), asking first as Calendar's sheet does (Oscar's call on 2026-10-04).
  A title or a name being written wraps, its row growing with the words so all of them stay in sight (Oscar's call on 2026-10-04).
  In Weeks, bars are drawn to the day but move and stretch by whole weeks: a bar keeps its days as it moves, a due keeps its weekday as its bar stretches, and a bar drawn new runs Monday to Friday; typed lengths are weeks unless named ("10d"), and in Days, days unless named ("3w").
  Rows keep their order as they are edited (a spreadsheet's rows do not re-sort), their own order once moved: with Alt+Up/Down, or dragged by their number to another place or workstream (Oscar's call on 2026-10-01).
  Workstreams keep an order of their own, a new one last: on a workstream's row, Alt+Up/Down moves its whole lane past the workstream above or below, and its number drags it to another place among them; the tasks in none stay under them all, and the Projects page lists them in the same order (Oscar's call on 2026-10-04).
  Done tasks stay on the plan, struck through; cancelled ones and a series' finished occurrences leave it.
  The tasks shown are chosen by status from a menu, remembered in that browser; Ctrl+Tab steps through all tasks, all but done, in progress and review, Ctrl+Shift+Tab back (Oscar's call on 2026-10-04).

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

**Project repository** (2026-10-04): belongs to one project; its location, a local path or a URL, as written.
Its name is read from the location, never stored.

**Project document** (2026-10-04): belongs to one project; name (unique within the project, in any case), body (Markdown), when its body last changed.
Every project has one named AGENTS.md, created with it, which cannot be renamed or deleted.

**Workstream** (Oscar's call on 2026-10-01, replacing milestones: "I manage it that way"): belongs to one project; name, status (open / done), position (its place among its project's workstreams).
A stream of the project's work run beside its others, a lane of its tasks with no date of its own: its span is its tasks', and its progress is computable from them.
Deleting one leaves its tasks in the project, in none.

**Task**: title, notes, status, owner (oscar / claude), optional project, optional workstream (only of its own project), optional planned_for (do-date), optional due (deadline), optional starts_on (its start week on its project's Gantt), optional position (its place among its group's rows there), optional written_on (the notebook page it was written on), optional estimate (how long its work is thought to take, a minute to a day), optional priority (urgent, high, medium or low).
An estimate is set in the task sheet (its stopwatch icon, or "45m", "1h30" or "2 hours" as the title is written), in Today's notes the same way, and by Claude; it is the task's weight in a day's plan.
A priority (Oscar's call on 2026-10-04: "visible in GANTT and everywhere we see tasks") is how much a task matters against the others, Linear's four levels, none by default.
It is set in the task sheet (its bars icon, or "p1" to "p4" as the title is written, as Todoist writes them), in Today's notes the same way, with "!" on a Projects row, in the Gantt's Priority column, and by Claude.
It shows wherever tasks are: rows, the task sheet and page, Today's notes and its For today, Calendar's Plan, the Gantt, and search.
It orders nothing on its own: dates still lead every list, and priority is their first tie-break (the most pressing first among tasks of the same dates); the Gantt keeps its rows where they were put.
A repeating task's occurrences start with no priority, as they start with no estimate.
Notes are the task's free-form description, and sub-tasks live inside it: a line starting with "- " (or "* ") is a sub-task, "- [x] " once done, and every other line is context kept where it was written.
Sub-tasks are text, not rows: they carry no status, owner, or dates of their own, and ticking one rewrites only its own line.
A repeating task's occurrences start with every sub-task open.
planned_for is the day Oscar intends to work it and drives the daily list; due is the obligation and drives urgency.
Backlog tasks have neither.
starts_on always comes with a due, never after it: its span is its start day to its due, a start given alone ends that week's Friday (or on itself at a weekend), a due cleared takes the start with it, and a due moved before the start pulls the start back to its week's Monday.

**TaskRevision**: one step in a task's history: when, who (oscar, claude or system), the kind of change (created, updated, deleted), and the task's fields as they stood after it.
Recorded by the ORM on every flush that touches a task, whatever path made the change, and kept after the task is deleted; the history started on 2026-09-26 with a baseline of every task as it stood.
It is shown under the task's sheet and read by Claude through `get_task_history`.
A description written over a while is one step: an edit to the description alone, by the same hand within ten minutes of that task's last step, itself such an edit, folds into it, so a page saving as it is written leaves one "Description edited".

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

### Project context

- `get_project_context(project_id or name)` reads a project's context: the project, its repositories, and its documents in full, AGENTS.md first.
  `list_projects` names each project's repositories too, so a session can tell which project its folder belongs to.
  The context is read-only to Claude for now: Oscar writes it on the project's page.

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

### Repositories

Oscar's call on 2026-10-04: a Repositories page, connected to GitHub to pull his repositories, with connecting made as easy as it can be.

- **Connecting is one click through the GitHub CLI** (`app/sources/github.py`), after how GitHub Desktop, VS Code and other tools sign in.
  The CLI on the machine is usually signed in already (`gh auth login`, GitHub's own device flow); the page says as whom, and Connect uses it.
  The app asks `gh auth token` for the token at each sync and never copies it, so signing gh out, or into another account, is followed.
  A registered OAuth app of the app's own was set aside: its device flow is the CLI's, with a registration to keep.
- **Or a pasted token**, for a machine without the CLI: a link opens GitHub's form for a fine-grained token already filled in (read-only, repositories' metadata only), and the token is checked with GitHub before it is kept, in `[github].token_file` (git-ignored `local/`).
- **One client for GitHub.** Every request goes through `GitHub` in `app/sources/github.py`: the API version header, paging by the Link header, and GitHub's refusals in words (signed out, rate-limited until when, unreachable); a later GitHub feature is a method there.
- **Kept in the database.** `github_link` holds who is signed in, how (`cli` or `token`) and how the last sync went; `repositories` every repository he can reach (his own, those he collaborates on, his organizations'), as GitHub had them at the last sync: name, owner, description, visibility, fork, archived, language, default branch, open issues and pull requests, and the last push in local time.
  A sync adds the new, updates the changed and deletes the gone; disconnecting deletes the list with the link.
  When GitHub stops accepting the sign-in, the link says so and the page asks to connect again, the list staying in sight.
- **The page** is a ruled sheet: the repositories last pushed first, each name opening it on GitHub, another's with its owner, a public one or a fork marked; then its open issues, language and last push in columns; the archived ones folded under their own row; and the account at the foot.
  A field at the header's right finds them by every word written, in their name, description or language.
- **Synced by the scheduler** every `[github].sync_minutes` (60) and on demand.
- **Read by Claude** through `list_repositories(query, include_archived)` over MCP.

### Plan truth

- The app database is canonical for cross-project plan state.
- Repo trackers (wayfinder maps and the like) remain per-project working artifacts, not synced or mirrored.

### Manual entry

The web UI writing to the same database; nothing extra to build.

## 7. Nudging and notifications

Per [Decision: AI nudging and notifications](tracker/tickets/013-ai-nudging.md):

- **Triggers (rule-based, no Claude in the loop)**:
  1. Upcoming due dates within about 3 days, task not done.
  2. Needs-review backlog: tasks sitting in needs_review beyond a threshold.
  3. A bill of Finances due within about 3 days and not yet seen paid; its nudge retires once a payment is seen.
  4. Activity without plan update (arrives with v2 data): sessions ran in a project but no MCP plan update followed.
  Missed blocks were the first, until task blocks went (2026-10-02).
- Nudges are templated by APScheduler jobs; Claude remains the planner Oscar talks to, not a background voice.
- A task's nudge shows only while its fact still holds: finishing a task, or clearing its review, retires the nudge without a dismissal.
- **Channels**: an in-app nudge center (inbox/banner, each nudge dismissable or actionable) plus phone push via a relay.
  Windows toasts explicitly not used.
- **Cadence**: a morning digest bundles the day's shape, upcoming dues, bills and the review backlog; it is the only push, the rest waiting in the app.
  The time-sensitive break-through push (a block just missed) went with task blocks, and its quiet hours with it.

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
- Real client JS is limited to a few focused vanilla islands, each built well once: the calendar (its grid and Today's timeline: drawing, writing and dragging events, their cards), Calendar's sheet of days, the task sheet (one editor for adding and editing, with its line-based description editor), Today's notebook (the same line editor in prose mode, with the sheet as its task box), and the chats with Claude on Nutrition and Spending (the answer streamed as it is written).

### Background jobs

APScheduler inside the FastAPI process; jobs share app code and database sessions:

- Daily recurrence materialization (8-week rolling horizon).
- Work-calendar ICS poll, a few times a day, morning-weighted.
- Hook-spool ingestion at startup (v2).
- Nudge trigger evaluation and morning digest.
- Daily backup snapshot.
- Garmin sync, every half hour while connected.
- GitHub sync, every hour while connected.

### Deployment and backups

- **A desktop app, wholly local** (Oscar's call on 2026-10-03, replacing that morning's PWA and the scheduled task behind it): a Windows program of its own, built from the repo and installed per user, with no repo, Python, browser or Task Scheduler needed to run it.
  One process holds everything: its window (Edge WebView2 over the app's own pages), the server on `127.0.0.1:8377` (and the Tailscale interface) and the scheduler, since Claude's MCP, the jobs and the phone all need it whether a window is open or not.
  Closing the window hides it to a tray icon, where it keeps running; it starts there at sign-in, which the hook-spool design assumes, and Quit is on the tray icon's menu.
  The tray icon's menu opens Today, Calendar, Projects or New task; a number on the taskbar button and a dot on the tray icon count the nudges waiting; the title bar takes the page's paper and ink.
  Its data lives in its own folder (`%LOCALAPPDATA%\Personal Calendar`): the database, created and migrated by the app as it starts, its logs, backups, the machine's secrets and its settings over the shipped defaults.
  A change reaches it through its Update button, there while origin's master (fetched in the background; changes land through merged PRs) is past the installed commit: it builds that commit (never uncommitted work) in the background and stages it beside the running version, then offers Restart, which waits for Oscar (his call on 2026-10-04); the restart hands over in a second or two, the new window coming up over the old at the same page; the installed app never runs the repo's code.
  The installer left in the repo by each build is the whole app for another machine.
  Windows only, built with PyInstaller and Inno Setup; a Tauri shell stays the alternative if WebView2 through pywebview falls short.
- The in-app daily backup job uses SQLite's backup API to write dated snapshots into a cloud-synced folder; retain about 30.
- Restore is quitting the app and copying a snapshot back over the database file.

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
