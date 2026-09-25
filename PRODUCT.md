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

- Tasks in lists (today via planned_for, backlog) and planned across days on the Weeks view, with lifecycle todo / in_progress / blocked / needs_review / done / cancelled.
- "Delegated to Claude" list section with status chips: queued, running, needs review.
- Missed marker on tasks whose scheduled calendar block passed uncompleted (derived, red-ink moment).
- Projects with milestones (target dates, computed progress).
- Calendar: local events, read-only work events, deliberately scheduled task blocks, faded ghost outlines for today's missed blocks.

## Brand commitments (user-pinned 2026-08-28)

- Visual direction: **calm paper planner**. Warm off-white paper surfaces, ink-dark text, a serif for headings, generous whitespace; an analog planner made digital.
- Theme: light and dark tokens, following the system theme.
- Pixel-perfection matters; quality over development cost (SPEC.md section 10).

## Constraints

- Server-rendered Jinja + HTMX; no build step; the only real client JS is two small islands: the calendar drag (week grid and Today's timeline) and the Weeks drag-to-replan.
- Works on desktop and phone widths; phone gets the full UI, not a cut-down version.
- No login screens, no marketing surfaces; the app opens straight into Today.
