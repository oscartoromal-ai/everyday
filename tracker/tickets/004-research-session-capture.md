---
id: 4
title: "Research: how Claude Code sessions can auto-report work"
labels: [wayfinder:research]
status: closed
assignee: claude (charting session)
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

## Resolution

Full findings: [session-capture.md](../research/session-capture.md).
Gist: hooks are the deterministic backbone (rich lifecycle events with session id, tool names, inputs and results, POSTable to localhost via curl; low setup, works in interactive and headless runs; Windows needs care with PowerShell escaping).
An app-exposed MCP `report_work` tool adds semantic task-level reporting but depends on Claude choosing to call it (CLAUDE.md instructions raise reliability).
OpenTelemetry gives resilient metrics/events but needs an OTLP collector and is batched, not real-time.
Transcript JSONL files are complete but undocumented and version-unstable; tailing them is viable but not recommended.
Recommended shape: hooks for deterministic capture plus an MCP reporting tool for semantics; design the app API idempotent to duplicate reports.
