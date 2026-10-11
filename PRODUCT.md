# PRODUCT.md

## What this is

A locally-run personal planner for one user (Oscar): calendar, to-dos, and projects in one place, doubling as the control panel for work delegated to Claude.
Full spec in SPEC.md; this file carries the design-relevant product truth.

## Audience and scene

- One user, a software engineer, on Windows 11 desktop most of the day and on a phone (via Tailscale) mornings and evenings.
- Daily ritual: a morning glance at the day's shape; quick captures and check-offs during the day; occasional deliberate planning passes.
- The app must feel calm and trustworthy, never gamified or noisy.

## Mode

Operate. Every surface is task completion: scan today, check things off, replan, review delegated work.

## Core objects (v1)

- Tasks planned in their lists, each project's on its Tasks tab and those without a day on Plan (Oscar's call on 2026-10-04), worked from Today, with lifecycle todo / in_progress / blocked / needs_review / done / cancelled, and a history of every change.
  Each task is an object with its own page, for one too long for its row: its title, its fields and its description written at length, saved as it is written (Oscar's call on 2026-10-03), opened from wherever tasks are listed (Oscar's call on 2026-10-04).
  The page takes the window's width, the map of its project at its left (context, workstreams, tasks), and its agent work, outline and history as panes of the sidebar at its right beside the agent window, its agent work only once it is Claude's task (Oscar's call on 2026-10-11).
- Today as a notepad: notes in Markdown for each day, beside the day's timeline (for now; the notebook that turned lines into tasks is set aside), under a glance at the day (what is on now and next, and readiness, sleep and body battery from Garmin), with the day's due and planned tasks offered to write in.
- "Delegated to Claude" list section with status chips: queued, running, needs review.
- Projects with workstreams (lanes of their work, computed progress), seen together on Projects as a timeline under what needs attention (each one's health, progress, deadlines and span, and its workstreams', on shared weeks; Oscar's call on 2026-10-04), each opening on a page of its own: the project, its repositories, and its context for the agents working on it (its AGENTS.md first, then other Markdown documents in folders and subfolders, each written on a page of its own; files in the project's folder of the everyday files, its master copy, which agents write too), with its tasks as the next tab and its Gantt chart after it: a spreadsheet of its tasks as bars over weeks or days, a bar running from the task's start day to its due (Oscar's call on 2026-10-04).
- Calendar: a day, three days or a week of local events (written, dragged and changed on the grid) and read-only work events (a cancelled one struck through); tasks take no time on it (Oscar's call on 2026-10-02).
  Or its sheet: four weeks of days as spreadsheet rows, where he stays, the day's plan and a column per habit, all written in place (Oscar's call on 2026-10-02, after his Excel).
- Nutrition: a day of eating, read from its Markdown file against the plan's targets, beside the day's chat with Claude, who writes that file from what Oscar says.
- Garmin: what Oscar's watch measured, a day at a time (steps, energy burned, sleep, heart rate, HRV, stress, body battery, readiness, activities) with the fortnight before it, synced from Garmin Connect once he connects it on the page.
- Finances: a month's spending by category against its budgets beside a chat with Claude, who sorts and budgets with Oscar; accounts and net worth from his banks' CSV exports (Revolut, ING); bills and subscriptions, seen paid; and savings goals.
- Models: the Claude and OpenAI models this machine can use, found through Claude Code and the Codex CLI signed in on it, and the one each of the app's features runs on (its chats first), set up from Settings.
- The everyday files (Oscar's call on 2026-10-04): a folder for agentic work, `C:\everyday-files` by default, with each repository's main clone once (`repos/`), each project's context (`projects/`) and the folders runs work in (`work/`); tasks are to be handed to coding agents from the app, through any agent system behind one interface, T3 Code first, their work reported back to the task.
- Repositories: the GitHub repositories Oscar can reach, last pushed first, found by their words, synced from GitHub once he connects it on the page (in one click, through the GitHub CLI's sign-in).

## Brand commitments (user-pinned 2026-09-26, replacing Brasa v2 from 2026-09-25 and the 2026-08-28 "calm paper planner")

- Visual direction: **Neon Signage**, from Oscar's central design-language repo (`C:/Users/me/design-language/systems/neon-signage/SYSTEM.md`).
  Pink and cyan neon over black glass by night, the same signs unlit and printed on a pale sky by day; ink draws the interface; pink is you, cyan is time; Inter only.
- The app consumes the system only through the repo's token contract, so switching to another of Oscar's systems (Brasa v2, Tokyo Night, Sumi & Neon) is one command.
- Inputs (user-pinned 2026-09-30, replacing the 2026-09-27 settei plates): written on the line, as Today's notes are. Forms on Health and Finances are ruled, numbered sheets, one field per row; elsewhere a field is its name over a single rule. No boxes, no graph paper, no red pencil.
- Theme: Day and Night, following the system theme until the user picks one.
- Pixel-perfection matters; quality over development cost (SPEC.md section 10).

## Constraints

- Server-rendered Jinja + HTMX; no build step; the only real client JS is a few small islands: the calendar's grid (Calendar's days and Today's timeline: drag, draw, an event's card and composer), Calendar's sheet of days, the command menu (Ctrl+K), the task composer and description editor, Today's notepad, a project's Gantt sheet, and the chats with Claude on Nutrition and Spending (the answer streamed as Claude writes it).
  The notepad's, a project document's and a task description's editors are CodeMirror 6, one committed file (`app/static/vendor/codemirror.js`, with the Lezer Markdown parser) built from `scripts/vendor/codemirror`, as htmx is one committed file; the app still builds nothing.
  Every place Markdown is written (a task's description, a project's documents, Today's notes) is the one engine, `markdown-live.js`: written and shown as it reads, as Obsidian's Live Preview does, with its Source and Reading modes, tables and highlighted code.
- Works on desktop and phone widths; phone gets the full UI, not a cut-down version.
- No login screens, no marketing surfaces; the app opens straight into Today.
