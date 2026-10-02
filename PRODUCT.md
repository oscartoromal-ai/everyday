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

- Tasks planned on the Tasks page (grouped by do-date, undated ones first in line), worked from Today, and planned across days on the Weeks view, with lifecycle todo / in_progress / blocked / needs_review / done / cancelled, and a history of every change.
- Today as a notepad: plain notes for each day, beside the day's timeline (for now; the notebook that turned lines into tasks is set aside).
- "Delegated to Claude" list section with status chips: queued, running, needs review.
- Missed marker on tasks whose scheduled calendar block passed uncompleted (derived, shown as an error badge).
- Projects with workstreams (lanes of their work, computed progress), each opening as a Gantt chart: a spreadsheet of its tasks as bars over weeks or days, a bar running from the task's start day to its due.
- Calendar: a day, three days or a week of local events (written, dragged and changed on the grid), read-only work events (a cancelled one struck through), deliberately scheduled task blocks, faded ghost outlines for today's missed blocks.
- Nutrition: a day of eating, read from its Markdown file against the plan's targets, beside the day's chat with Claude, who writes that file from what Oscar says.
- Garmin: what Oscar's watch measured, a day at a time (steps, energy burned, sleep, heart rate, HRV, stress, body battery, readiness, activities) with the fortnight before it, synced from Garmin Connect once he connects it on the page.
- Finances: a month's spending by category against its budgets beside a chat with Claude, who sorts and budgets with Oscar; accounts and net worth from his banks' CSV exports (Revolut, ING); bills and subscriptions, seen paid; and savings goals.

## Brand commitments (user-pinned 2026-09-26, replacing Brasa v2 from 2026-09-25 and the 2026-08-28 "calm paper planner")

- Visual direction: **Neon Signage**, from Oscar's central design-language repo (`C:/Users/me/design-language/systems/neon-signage/SYSTEM.md`).
  Pink and cyan neon over black glass by night, the same signs unlit and printed on a pale sky by day; ink draws the interface; pink is you, cyan is time; Inter only.
- The app consumes the system only through the repo's token contract, so switching to another of Oscar's systems (Brasa v2, Tokyo Night, Sumi & Neon) is one command.
- Inputs (user-pinned 2026-09-30, replacing the 2026-09-27 settei plates): written on the line, as Today's notes are. Forms on Tasks and Health are ruled, numbered sheets, one field per row; elsewhere a field is its name over a single rule. No boxes, no graph paper, no red pencil.
- Theme: Day and Night, following the system theme until the user picks one.
- Pixel-perfection matters; quality over development cost (SPEC.md section 10).

## Constraints

- Server-rendered Jinja + HTMX; no build step; the only real client JS is a few small islands: the calendar's grid (Calendar's days and Today's timeline: drag, draw, an event's card and composer), the command menu (Ctrl+K), the Weeks drag-to-replan, the task composer and description editor, Today's notepad, a project's Gantt sheet, and the chats with Claude on Nutrition and Spending (the answer streamed as Claude writes it).
  The notepad's editor is CodeMirror 6, one committed file (`app/static/vendor/codemirror.js`) built from `scripts/vendor/codemirror`, as htmx is one committed file; the app still builds nothing.
- Works on desktop and phone widths; phone gets the full UI, not a cut-down version.
- No login screens, no marketing surfaces; the app opens straight into Tasks, where the day's plan is made.
