---
id: 9
title: "Architecture: framework, storage, frontend, deployment"
labels: [wayfinder:grilling]
status: open
assignee:
blocked-by: [7, 8, 12]
parent: map
---

## Question

Fix the technical architecture for the spec: Python web framework, data storage, frontend approach, and how the app runs locally on Oscar's Windows machine (startup, persistence, backups).
Constraints already decided: Python backend, local web app, prefer quality, simplicity, robustness, and long-term sustainability over development cost.
Blocked on the work calendar decision (a calendar-pull job changes storage and background-job needs; was the Google sync decision before that was resolved as no-Google), the AI integration decision (MCP server vs REST changes the API surface), and the domain model.
