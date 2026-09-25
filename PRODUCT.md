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

- Tasks planned on the Tasks page (grouped by do-date, undated ones first in line), worked from Today, and planned across days on the Weeks view, with lifecycle todo / in_progress / blocked / needs_review / done / cancelled.
- "Delegated to Claude" list section with status chips: queued, running, needs review.
- Missed marker on tasks whose scheduled calendar block passed uncompleted (derived, shown as an error badge).
- Projects with milestones (target dates, computed progress).
- Calendar: local events, read-only work events, deliberately scheduled task blocks, faded ghost outlines for today's missed blocks.

## Brand commitments (user-pinned 2026-09-26, replacing Brasa v2 from 2026-09-25 and the 2026-08-28 "calm paper planner")

- Visual direction: **Neon Signage**, from Oscar's central design-language repo (`C:/Users/me/design-language/systems/neon-signage/SYSTEM.md`).
  Pink and cyan neon over black glass by night, the same signs unlit and printed on a pale sky by day; ink draws the interface; pink is you, cyan is time; Inter only.
- The app consumes the system only through the repo's token contract, so switching to another of Oscar's systems (Brasa v2, Tokyo Night, Sumi & Neon) is one command.
- Theme: Day and Night, following the system theme until the user picks one.
- Pixel-perfection matters; quality over development cost (SPEC.md section 10).

## Constraints

- Server-rendered Jinja + HTMX; no build step; the only real client JS is a few small islands: the calendar drag (week grid and Today's timeline), the Weeks drag-to-replan, and the task composer and description editor.
- Works on desktop and phone widths; phone gets the full UI, not a cut-down version.
- No login screens, no marketing surfaces; the app opens straight into Tasks, where the day's plan is made.
