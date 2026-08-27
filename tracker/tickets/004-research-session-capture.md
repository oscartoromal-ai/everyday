---
id: 4
title: "Research: how Claude Code sessions can auto-report work"
labels: [wayfinder:research]
status: open
assignee:
blocked-by: []
parent: map
---

## Question

By what mechanisms can Claude Code sessions and agents automatically report the work they are doing to a local web app, so AI agent work shows up in Oscar's system without manual entry?
Surface the concrete options and their reliability on Windows:

- Claude Code hooks: which events exist (session start/end, tool use, stop), what payloads they carry, and how a hook could POST status to a local API.
- OpenTelemetry or other telemetry Claude Code emits.
- Reading session transcript/history files from disk.
- An MCP tool the session itself calls to log progress.
- Any scheduled-agent or cloud-session considerations.

For each: what data is available (task description, status, repo, timestamps), setup cost, and failure modes.
