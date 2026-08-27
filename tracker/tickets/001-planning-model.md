---
id: 1
title: "Planning model: how todos and the calendar interact"
labels: [wayfinder:prototype]
status: closed
assignee: claude (planning-model session)
blocked-by: []
parent: map
---

## Question

How should the to-do list and the calendar relate when Oscar plans his days: time-blocking (tasks are scheduled onto the calendar as blocks, the calendar is the plan, the list is the backlog), side by side (calendar holds events, todos carry due dates, no blocks), or a hybrid?
Oscar is genuinely unsure, so resolve this HITL with cheap throwaway UI prototypes to react to, not by argument.
Consult the `impeccable` skill when building the prototypes.
The answer fixes the core interaction model the domain model and spec hang on.

## Resolution

Oscar compared three interactive mockups (asset: [planning-model.html](../prototypes/planning-model.html)) showing the same day under time-blocking, side-by-side, and hybrid models.

Decision: **hybrid**.
To-dos live in lists by default; a task gets a calendar block only when Oscar chooses to give it a slot (protected time for deep work), so the calendar shows real events plus deliberately scheduled tasks, never a forced block per task.

Claude's delegated work appears as a **"Delegated to Claude" list section** with status chips (queued, running, needs review), not as a parallel lane on the calendar.

Missed blocks: when a scheduled block passes uncompleted, the task **falls back to the list wearing a visible "missed" marker** until replanned or completed, and the empty slot stays on today's calendar as a **faded ghost outline** (gone tomorrow).
The calendar's future is a plan; its past stays honest.
