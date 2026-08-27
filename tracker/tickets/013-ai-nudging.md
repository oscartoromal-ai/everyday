---
id: 13
title: "Decision: AI nudging and notifications"
labels: [wayfinder:grilling]
status: open
assignee:
blocked-by: [9]
parent: map
---

## Question

How does the planner proactively reach Oscar?

Decide what triggers nudges (missed calendar blocks, stale projects, sessions with activity but no plan update, upcoming deadlines) and through which channels (web app UI, Windows notifications, phone).

Graduated from the fog by [Decision: AI integration architecture](007-ai-integration-decision.md), which fixed the mechanisms nudges build on (app DB canonical, lifecycle hooks, MCP planner tools).
Channel choice depends on deployment and reachability, so this waits on [Architecture: framework, storage, frontend, deployment](009-architecture.md).
