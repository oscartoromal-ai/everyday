# Automatic Work Reporting to Local Web Apps: Mechanisms for Claude Code and Agents

Findings for ticket [Research: how Claude Code sessions can auto-report work](../tickets/004-research-session-capture.md).

## 1. Claude Code Hooks: Event-Driven Reporting

### Available Hook Events and Payloads

Claude Code fires hooks at specific points in its lifecycle.
The following events are relevant for reporting work progress to a local API:

**Session Lifecycle:**
- `SessionStart` (with matcher values: `startup`, `resume`, `clear`, `compact`, `fork`)
- `SessionEnd` (with matcher values: `clear`, `resume`, `logout`, `prompt_input_exit`, `other`)

**Work/Tool Execution:**
- `UserPromptSubmit` - fires when user submits a prompt
- `PreToolUse` - before a tool call executes (can block)
- `PostToolUse` - after a tool call succeeds
- `PostToolUseFailure` - after a tool call fails
- `PostToolBatch` - after a full batch of parallel tool calls resolves
- `Stop` - when Claude finishes responding

**Other Reportable Events:**
- `SubagentStart` and `SubagentStop` - subagent lifecycle
- `TaskCreated` and `TaskCompleted` - background tasks
- `Notification` - when Claude needs input
- `PreCompact` and `PostCompact` - context compaction events
- `FileChanged`, `CwdChanged`, `DirectoryAdded` - filesystem changes

### Hook JSON Payload Structure

All hooks receive common base fields in JSON via stdin:

```json
{
  "session_id": "abc123",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
  "cwd": "/home/user/my-project",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "agent_id": "optional-for-subagents",
  "agent_type": "optional-agent-name",
  "effort": { "level": "medium" }
}
```

Event-specific examples:

**SessionStart:**
```json
{
  "hook_event_name": "SessionStart",
  "start_reason": "startup|resume|clear|compact|fork",
  "model": "claude-3-5-sonnet-20241022"
}
```

**UserPromptSubmit:**
```json
{
  "hook_event_name": "UserPromptSubmit",
  "user_input": {
    "text": "The user's prompt text",
    "images": []
  }
}
```

**PostToolUse:**
```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "npm test"
  },
  "tool_use_id": "toolu_01ABC123...",
  "tool_result": {
    "type": "text",
    "text": "stdout output"
  }
}
```

**Stop:**
- Fires when Claude finishes responding; provides conversation checkpoint

### Posting to localhost HTTP API

A hook command can POST to `http://localhost:<port>` using `curl` or equivalent.
The hook receives the full JSON on stdin, so it can parse and forward it.

Example hook configuration in `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "jq -c '{event: .hook_event_name, session: .session_id, reason: .start_reason}' | curl -s -X POST http://localhost:3000/claude/session-start -H 'Content-Type: application/json' -d @-"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "jq -c '{event: .hook_event_name, session: .session_id, tool: .tool_name, timestamp: now}' | curl -s -X POST http://localhost:3000/claude/tool-use -H 'Content-Type: application/json' -d @-"
          }
        ]
      }
    ]
  }
}
```

### Data Available at Each Hook Point

| Hook Event | Data Available |
|------------|----------------|
| SessionStart | session_id, start_reason (startup/resume/clear/compact/fork), model, project directory, cwd |
| UserPromptSubmit | user_input.text, images, session_id, timestamp via prompt_id |
| PreToolUse | tool_name, tool_input (command/file path/query), tool_use_id, can extract intent |
| PostToolUse | tool_name, tool_input, tool_result.text (output), tool_use_id, success status |
| PostToolUseFailure | tool_name, error message, tool_use_id, failure reason |
| Stop | implicitly signals turn completion; signals readiness for next user input |
| SubagentStart | subagent name/id, parent session_id |
| SubagentStop | subagent result, parent session_id |
| TaskCreated/TaskCompleted | task description, task_id, status |

### Setup Cost

**Low.** Add hook configuration to `.claude/settings.json` or project `.claude/settings.json`.
Minimal overhead: hooks run out-of-process in the shell, so a slow HTTP POST does not block Claude's execution.
Hook command output is optional; exit code 2 blocks the action, other codes are informational.

### Windows-Specific Caveats

On Windows PowerShell 5.1:

- Use `curl.exe` (available natively since Windows 10 1803) or WSL Bash
- Escape quotes: `\"` in PowerShell or use single quotes where possible
- Path separators: hook receives normalized JSON, but the `cwd` field may use backslashes; the curl command string must escape them
- Hooks run in PowerShell by default on Windows unless the command specifies another shell (e.g., `bash.exe -c "..."`)

Example for Windows PowerShell:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "powershell.exe -Command \"$input | ConvertFrom-Json | Select-Object -Property session_id, tool_name, cwd | ConvertTo-Json | Invoke-WebRequest -Uri 'http://localhost:3000/claude/tool-use' -Method POST -ContentType 'application/json' -Body $_\""
          }
        ]
      }
    ]
  }
}
```

Alternatively, use WSL Bash from PowerShell:

```json
{
  "type": "command",
  "command": "bash.exe -c \"jq -c '{event: .hook_event_name, session: .session_id}' | curl -s -X POST http://localhost:3000/claude/event -H 'Content-Type: application/json' -d @-\""
}
```

### Failure Modes

- **HTTP endpoint unreachable:** hook command fails silently or exits non-zero; the action (tool use, session start) proceeds unless the hook exits 2
- **Slow endpoint:** hook completion delays the session; long POST timeouts freeze the UI
- **JSON parse errors:** if the hook command fails to parse hook JSON, the action still proceeds but the POST is skipped
- **Permission issues:** on Windows, if the hook script is not executable or the curl command lacks PATH access, the command fails; on Linux/macOS, scripts must be executable (`chmod +x`)
- **Schema mismatch:** if the local API expects a different JSON shape, the hook's jq filter must transform the data; misaligned schemas silently lose data

**Mitigation:** Add timeout to curl (`--max-time 5`), write hook output to a local log file for debugging, and test with `claude` CLI in bare mode first.

### Strengths
- Real-time, granular event firing at precise lifecycle points
- Full context (session ID, tool names, inputs, outputs) in each hook
- Works across all Claude Code sessions automatically (interactive and headless `-p`)
- No external dependencies beyond shell tools like `curl` or `jq`
- Deterministic: hook runs every time the event fires

### Limitations
- Hooks are shell commands, so complex parsing requires `jq` or equivalent
- Hooks are fire-and-forget; the local API cannot block Claude Code actions (exit 2 can veto, but not modify)
- No built-in retry logic; if the HTTP endpoint times out, the hook fails silently by default
- Hooks run in the Claude Code process's shell context, so environment variables and PATH may not match the user's login shell

---

## 2. OpenTelemetry Support in Claude Code

### What Metrics and Events Are Exported

Claude Code has **comprehensive OpenTelemetry (OTel) support** for tracking usage, costs, and tool activity.

**Metrics (time series data):**
- `claude_code.session.count` - CLI sessions started
- `claude_code.cost.usage` - Session cost in USD
- `claude_code.token.usage` - Tokens used (input, output, cache)
- `claude_code.lines_of_code.count` - Lines modified
- `claude_code.active_time.total` - Active usage time (seconds)
- `claude_code.code_edit_tool.decision` - Code edit permission decisions

**Events (detailed logs):**
- `claude_code.user_prompt` - User prompt submission
- `claude_code.assistant_response` - Model responses
- `claude_code.api_request` - API calls to Claude
- `claude_code.api_error` - API failures
- `claude_code.api_refusal` - Model refusals
- `claude_code.tool_result` - Tool execution results
- `claude_code.tool_decision` - Tool permission decisions (accept/reject)
- `claude_code.mcp_server_connection` - MCP server connectivity
- `claude_code.auth` - Login/logout events
- `claude_code.permission_mode_changed` - Permission mode changes

**Standard attributes on all signals:**
- `session.id` - Unique session identifier
- `user.id` - Anonymous user identifier
- `organization.id` - Organization UUID (when authenticated)
- `user.email` - Email address (when authenticated)
- Custom attributes from `OTEL_RESOURCE_ATTRIBUTES`

### Pointing at a Local Collector

**Environment variables to configure:**

```bash
# Enable telemetry
export CLAUDE_CODE_ENABLE_TELEMETRY=1

# Choose exporters
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp

# Configure OTLP endpoint (gRPC default)
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Or HTTP with JSON (port 4318)
export OTEL_EXPORTER_OTLP_PROTOCOL=http/json
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/metrics
```

**Per-signal endpoints (advanced):**

```bash
export OTEL_EXPORTER_OTLP_METRICS_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://localhost:4318/v1/metrics

export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4317
```

**Authentication headers (optional):**

```bash
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer your-token"
```

**Distributed tracing (beta):**

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4317
```

### Content Logging and Filtering

Control what content is exported:

```bash
# Log user prompts (default: redacted)
export OTEL_LOG_USER_PROMPTS=1

# Log assistant responses (default: redacted)
export OTEL_LOG_ASSISTANT_RESPONSES=1

# Log tool details (commands, parameters, names)
export OTEL_LOG_TOOL_DETAILS=1

# Log full tool input/output content
export OTEL_LOG_TOOL_CONTENT=1

# Log complete API request/response bodies (or save to files)
export OTEL_LOG_RAW_API_BODIES=1
# Or: export OTEL_LOG_RAW_API_BODIES=file:/path/to/dir
```

### Granularity

Metrics are time-series aggregates (cumulative, gauge, histogram).
Events are structured logs with full context.
Traces (beta) correlate prompts to API requests and tool executions via `TRACEPARENT` environment variable and trace headers.

Events fire at these points:
- User submits prompt
- Model responds
- API request sent / API error
- Tool call result returned
- Permission decision made (allow/deny)
- MCP server connection status changes
- Auth state changes

**Per-session granularity:** all signals include `session.id`, so you can correlate work to a specific Claude Code session.

### Setup Cost

**Low to moderate.** Requires:
1. Local OTLP collector running on localhost (e.g., OpenTelemetry Collector, Jaeger, Tempo, or custom HTTP server)
2. Environment variables set when launching Claude Code (or in managed settings for organizations)
3. Optional: collection, transport, and storage backend

For personal use, a single lightweight collector process can receive signals from all sessions.

### Windows Configuration

Set environment variables before launching Claude Code:

**PowerShell:**
```powershell
$env:CLAUDE_CODE_ENABLE_TELEMETRY="1"
$env:OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
claude
```

**Batch/CMD:**
```batch
set CLAUDE_CODE_ENABLE_TELEMETRY=1
set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
claude
```

Or store in `~/.claude/settings.json` via managed settings:

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"
  }
}
```

### Failure Modes

- **Collector not running:** signals are buffered, then dropped if the buffer fills; no error is shown to the user
- **Network unreachable:** OTel client retries with exponential backoff; after max retries, signals are dropped
- **gRPC vs HTTP mismatch:** if endpoint expects HTTP but gRPC is configured, connection errors occur; trace/metric signals may be lost
- **Token expiration:** if Bearer token in headers expires, future signals fail authentication; no auto-refresh

### Strengths
- Decoupled from Claude Code; signals are sent asynchronously, not blocking the session
- Rich structured data: every event includes session ID, user ID, organization, and timestamp
- Integrates with standard observability platforms (OpenTelemetry ecosystem)
- Beta distributed tracing correlates a user prompt to all the API requests and tool calls it spawns
- Works in headless mode (`claude -p`) and cloud agents automatically

### Limitations
- Requires an external OTLP collector; cannot POST directly to an arbitrary HTTP API (OTel has a standardized format)
- Signals are batched and sent on an interval (not real-time); latency depends on batch size and export interval
- Redacts user prompts and responses by default for privacy; must explicitly enable `OTEL_LOG_*` flags to export content
- No in-session UI to show what is being exported; debugging requires access to the collector

---

## 3. Session Transcript Files on Disk

### Where Transcripts Are Stored

By default, Claude Code stores transcripts as JSONL at:

```
~/.claude/projects/<project>/<session-id>.jsonl
```

Where `<project>` is your working directory path with non-alphanumeric characters replaced by dashes.
For paths exceeding 200 characters, Claude Code truncates the name and appends a hash of the full path.

**Configurable locations:**

```bash
# Move storage off ~/.claude
export CLAUDE_CONFIG_DIR=/custom/path

# Name the project directory yourself (v2.1.234+)
export CLAUDE_CODE_PROJECT_DIR_NAME=my-project
```

### Transcript Format

Each line is a JSON object (newline-delimited JSON / JSONL).
The entry format is **internal to Claude Code and changes between versions**, so scripts that parse these files directly can break on any release.

Example structure (for reference only, subject to change):

```json
{"type": "message", "role": "user", "content": "fix the bug", "timestamp": "2026-08-27T10:30:00Z", "session_id": "abc123"}
{"type": "tool_use", "tool": "Bash", "input": {"command": "npm test"}, "tool_use_id": "toolu_123", "session_id": "abc123"}
{"type": "tool_result", "tool": "Bash", "content": "Tests passed", "tool_use_id": "toolu_123", "session_id": "abc123"}
{"type": "message", "role": "assistant", "content": "All tests passed.", "session_id": "abc123"}
```

### Recommended Access Methods

To build on session data reliably:

1. **Use `/export`** to export a rendered transcript for human reading
2. **Use `claude -p --resume <session-id> --output-format json`** to send a follow-up prompt and capture structured JSON output (session ID, result, usage, cost)
3. **Use hooks with `transcript_path`** field (available in all hook events) to know which file to archive or process
4. **Use the Agent SDK** to read messages programmatically (Python/TypeScript)

### Viability of a Watcher Process Tailing Transcript Files

**Technically viable but not recommended.**

**Pros:**
- No API overhead; tailing is a local filesystem operation
- Captures every event in real-time as it is written
- Session ID is available to correlate work to the session

**Cons:**
- The JSONL format is undocumented and subject to breaking changes between Claude Code releases
- Tail process must handle partial JSON lines (writes are not atomic) and incomplete messages in-flight
- Entries may not be complete (a tool_result may be written after the tool_use, but the pair is not atomic)
- No guaranteed ordering across parallel tool calls or subagents
- When a session is cleared or compacted, history is rewritten; a watcher must detect and handle that
- Cannot distinguish between actual errors and temporary write delays

**Better approach:** use `/export` or hooks with transcript_path to know when a session ends, then read the full transcript once.

### Data Available in Transcripts

- User prompts (text and images)
- Assistant responses
- Tool calls (name, input parameters, full command or query)
- Tool results (stdout, stderr, structured data)
- Metadata (session_id, timestamps implied by ordering)

### Setup Cost

**None.** Transcripts are written automatically.
No configuration needed; they exist by default.

### Failure Modes

- **Disk space full:** transcript writes fail silently; older sessions are cleaned up after 30 days (configurable via `cleanupPeriodDays` setting)
- **File locking (Windows):** if another process has the transcript file open, writes may block or fail; briefly impacts session responsiveness
- **Permission denied:** if Claude Config directory lacks write permission, transcripts are not written; session continues but history is lost
- **Symbolic links or network paths:** if `CLAUDE_CONFIG_DIR` points to a network drive or symlink, performance is degraded and reliability depends on network stability

### Strengths
- Zero setup; transcripts exist automatically
- Can be exported or accessed after a session ends
- Contains complete conversation and tool history
- Session ID is embedded, making it easy to correlate to other logs

### Limitations
- Format is undocumented and version-dependent; parsing is unsupported
- Entries are not atomic; partial writes are possible
- Watcher processes must handle race conditions and re-writes during compaction
- No API to query transcripts; must read files from disk or use `/export`

---

## 4. MCP Tools: Session-Called Reporting Mechanism

### How Sessions Call MCP Tools

An MCP (Model Context Protocol) server exposes tools that Claude can call.
The local app would implement a "report_work" or "log_activity" MCP tool.

**How sessions discover and call MCP tools:**

1. **Tool Discovery:** At session startup, Claude Code loads configured MCP servers from:
   - `.mcp.json` in the project directory
   - `~/.claude.json` (per-user configuration)
   - Plugin-provided servers

2. **Tool Search (Deferred Loading):** For Claude 4.5+ models:
   - Only server names and instructions load initially
   - Tools load on-demand when Claude searches for them
   - Minimizes context window impact

3. **Tool Invocation:** When Claude needs to report work:
   - Claude analyzes if an MCP tool is applicable
   - Claude calls the tool with parameters
   - MCP server (running locally) receives the call and processes it
   - Result is returned to Claude

### Setting Up a Local MCP Server for Work Reporting

Create an MCP server that exposes a `report_work` tool.

**Example (Node.js via stdio transport), `.mcp.json` at project root:**

```json
{
  "mcpServers": {
    "personal-calendar": {
      "type": "stdio",
      "command": "node",
      "args": ["./mcp-server.js"]
    }
  }
}
```

**MCP server implementation (`mcp-server.js`):**

```javascript
const { Server, Tool, StdioMessageReader, StdioMessageWriter } = require("@modelcontextprotocol/sdk/server");

const server = new Server({
  name: "personal-calendar-mcp",
  version: "1.0.0"
});

// Expose the report_work tool
server.tool("report_work", {
  description: "Report a task or work item to the personal calendar system",
  inputSchema: {
    type: "object",
    properties: {
      task_title: { type: "string", description: "Brief task description" },
      task_description: { type: "string", description: "Detailed description" },
      status: { type: "string", enum: ["in_progress", "completed", "blocked"], description: "Task status" },
      project: { type: "string", description: "Project or context" },
      duration_minutes: { type: "integer", description: "Time spent (minutes)" },
      tags: { type: "array", items: { type: "string" } }
    },
    required: ["task_title", "status"]
  }
}, async (params) => {
  // POST to local web app API
  const response = await fetch("http://localhost:3000/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: params.task_title,
      description: params.task_description,
      status: params.status,
      project: params.project,
      duration_minutes: params.duration_minutes,
      tags: params.tags,
      source: "claude-code",
      timestamp: new Date().toISOString()
    })
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return { status: "logged", task_id: (await response.json()).id };
});

// Start server
const reader = new StdioMessageReader(process.stdin);
const writer = new StdioMessageWriter(process.stdout);
server.connect(reader, writer);
```

### Encouraging Claude to Call the Tool

To make Claude Code reliably call an MCP tool for reporting:

**Via CLAUDE.md instructions:**

```markdown
# Work Logging

When you complete a task or make progress, report it to the personal calendar system.
Use the `report_work` tool from the `personal-calendar` MCP server.
Include the task name, current status (in_progress, completed, or blocked), and time spent.
```

**Via hooks to auto-call after key events:**

A `PostToolUse` hook could invoke `curl` to call the MCP tool indirectly (though less reliable than Claude calling it).
Better: use a subagent or system prompt to instruct Claude to call the tool.

**Via Agent SDK with instructions:**

If using the Agent SDK or `claude -p`, set a system prompt instructing the agent to call `report_work` after completing work, with the MCP server in the SDK's mcp_config.

### Reliability Analysis

**How reliably Claude calls MCP tools:**

- **High reliability:** If the tool is in the system prompt and Claude is explicitly instructed to use it after each task
- **Medium reliability:** If the tool is available but not explicitly instructed; Claude uses it opportunistically based on relevance
- **Variable reliability:** If the tool is optional (no instruction); Claude may skip it to finish faster

**Failure modes:**

- **MCP server crashes:** If the stdio process dies, the tool becomes unavailable; Claude receives an error and cannot report
- **Tool output error:** If the HTTP call to the local app fails, Claude sees the error; can be retried or logged
- **Model decides not to use it:** If Claude does not see the tool as helpful (e.g., for a small task), it may skip reporting entirely
- **Timeout:** If the MCP tool's HTTP call hangs, the tool call times out; Claude is notified and may retry

### Enforcing Tool Calls via Settings or Hooks

**CLAUDE.md approach (most reliable for instructions):** add a standing "always report completed work via report_work" instruction.

**Hook-based enforcement (post-session check):** a `SessionEnd` hook can grep the transcript for `report_work` calls and warn if none were made.
This is a **post-hoc check only**; it cannot force Claude to call the tool before ending.

**Agent SDK approach (most controllable):** the SDK allows intercepting tool decisions programmatically and always allowing the reporting tool.

### Setup Cost

**Moderate.** Requires:
1. Writing an MCP server that exposes the `report_work` tool
2. Deploying the server (stdio subprocess on the same machine)
3. Configuring `.mcp.json` to load it
4. Writing CLAUDE.md instructions to encourage Claude to use it
5. Testing that Claude calls the tool (may require iterative prompting)

### Strengths
- Claude controls when to report (can be context-aware and selective)
- Tool parameters are fully customizable (task name, status, duration, tags, etc.)
- Works in all Claude Code sessions automatically (interactive and headless)
- MCP server can implement custom business logic (e.g., validation, aggregation)
- Integrates with the built-in permission system

### Limitations
- Requires Claude to "decide" to call the tool; not guaranteed
- If MCP server crashes, reporting breaks until it restarts
- Tool invocation adds latency to Claude's response (must wait for the tool result)
- Requires custom code (MCP server) to run and maintain
- No automatic fallback if the tool fails; Claude must handle the error

---

## 5. Scheduled/Cloud Agents and Headless Runs (claude -p)

### Managed Agents Reporting

**Managed Agents** is an Anthropic-hosted agentic harness, separate from Claude Code.
It runs agent sessions in a cloud sandbox and provides a REST API for starting sessions and retrieving results.

**Key difference from Claude Code:** Managed Agents is hosted by Anthropic; you do not run it yourself.
The Claude Agent SDK, by contrast, is a library you host in your own process.

**Reporting mechanisms available in Managed Agents:**

1. **Session Event Stream (SSE):** real-time event updates as the session executes (messages, tool calls, results, status).
2. **Webhooks:** POST callbacks on session start/end, tool call completion, and errors.
3. **Polling Session Events:** fetch the complete event history via `GET /v1/sessions/{session_id}/events`.
4. **Scheduled Deployments:** a cron schedule creates sessions automatically; `deployment_run` records track each execution.

Deployments are created via the API (agent + environment + cron schedule); each run's session events can then be listed to see what the agent did.

### Reporting in `claude -p` (Headless Mode)

**Headless runs** use the `claude -p` flag for non-interactive, one-off task execution.

**Available reporting mechanisms:**

1. **Structured JSON output:**
   ```bash
   claude -p "Summarize changes" --output-format json
   ```
   Returns result text, session_id, usage, and cost as JSON.

2. **Streaming JSON output:**
   ```bash
   claude -p "Run tests" --output-format stream-json --verbose
   ```
   Emits newline-delimited JSON events (user input, assistant response, tool calls, results).

3. **Hooks still work:** `SessionEnd` and other hooks fire in headless runs, so the same POST-to-localhost hook covers interactive and headless sessions.

4. **Exit code reflects success:** exit code 0 = success; non-zero = failure, so scripts can branch on it.

5. **Piping results:** capture stdout/stderr to files for later ingestion.

### Agent SDK Reporting

The **Agent SDK** (Python and TypeScript) is a library, not a hosted service.
You run it in your own process and receive events programmatically: hook callbacks fire on tool use, and the run result exposes output, token usage, and cost as objects.
This gives the richest programmatic access but requires writing and hosting the harness yourself.

### Setup Cost and Failure Modes

**Managed Agents:**
- Setup cost: Moderate (define agent, environment, deployment via API)
- Reporting cost: Low (event stream is built-in)
- Failure modes: Cloud outage, rate limits, session timeout, Anthropic-hosted service issues

**Headless `claude -p`:**
- Setup cost: Minimal (add `--output-format json` flag)
- Reporting cost: None (output is already structured)
- Failure modes: Process crash, stdout buffering delays, timeout if CLI hangs

**Agent SDK:**
- Setup cost: Moderate (write SDK code to instantiate and run)
- Reporting cost: Low (hooks and result access are built-in)
- Failure modes: Process crash, uncaught exceptions, MCP server unavailability

### Comparison: Which Works Where

| Mechanism | Interactive Sessions | claude -p | Managed Agents | Agent SDK |
|-----------|----------------------|-----------|-----------------|-----------|
| Hooks (SessionStart/End/etc) | Yes | Yes | No | Yes (via SDK) |
| OpenTelemetry | Yes | Yes | No | No (must use SDK hooks) |
| Session transcripts (files) | Yes | Yes (in ~/.claude/projects/) | No (server-side only) | Yes (depends on SDK host) |
| MCP tools | Yes | Yes | Yes | Yes |
| Event streams/webhooks | No | No | Yes | Yes (via SDK callbacks) |

### Windows-Specific Considerations for Headless Runs

On Windows PowerShell 5.1, `claude -p ... --output-format json` output can be piped through `ConvertFrom-Json` and POSTed to the local API with `Invoke-WebRequest`.
Scheduled runs via Windows Task Scheduler can invoke Claude with specific hooks and MCP servers pre-configured.

---

## Comparison and Recommendation Shape

| Mechanism | Data Richness | Setup Cost | Reliability | Best For |
|-----------|---------------|------------|-------------|----------|
| **Hooks (PostToolUse, Stop, etc)** | High (tool name, input, output, session ID) | Low (JSON config) | High (fire every time) | Real-time event capture, per-action logging |
| **OpenTelemetry** | Medium (metrics + structured events) | Moderate (collector + env vars) | High (async, resilient) | Organization-wide observability, long-term trends |
| **Transcript files (JSONL)** | Very high (full conversation) | None (automatic) | Medium (file system dependent) | Post-session analysis, history review, debugging |
| **MCP tools** | High (custom params, structured result) | Moderate (MCP server code) | Medium (Claude must choose to call) | Flexible reporting with business logic, integration with calendar app |
| **Managed Agents (scheduled)** | High (full event stream, webhooks) | Moderate (API setup) | High (managed by Anthropic) | Long-running autonomous tasks, cron scheduling |
| **claude -p + JSON output** | Medium (result + cost + tokens) | Low (CLI flag) | High (synchronous) | CI/CD, one-off tasks, external tool integration |
| **Agent SDK hooks** | Very high (programmatic access) | Moderate (SDK code) | High (in-process) | Custom agents, full control |

### Recommended Combinations for Windows 11 with a Local Calendar Web App

**Scenario 1: Interactive Sessions with Real-Time Reporting - Hooks + MCP Tool**

1. Configure a `PostToolUse` (or `Stop`/`SessionEnd`) hook to POST key events to the calendar app's API
2. Add an MCP server that exposes a `log_activity`/`report_work` tool
3. Instruct Claude via CLAUDE.md to call the tool after completing tasks
4. Combine: hooks capture all actions deterministically; the MCP tool captures semantic task completions

**Rationale:** Hooks are deterministic and fire every time; MCP tools let Claude add semantic meaning (is this a task completion or just a step?).

**Scenario 2: Scheduled Automated Tasks - Managed Agents + Webhooks + Scheduled Deployments**

Managed Agents handles scheduling; webhooks eliminate polling; Anthropic manages the infrastructure.

**Scenario 3: Headless CI/CD Runs - claude -p with JSON output + Hooks**

No external dependencies; structured output is synchronous; exit code can trigger follow-up actions in the script.

**Scenario 4: Maximum Coverage - Hooks + OTel + MCP Tool + Transcripts**

Layered approach covers all failure modes; hooks are fast and deterministic; OTel is resilient; MCP adds business logic; transcripts provide forensic evidence.

### Implementation Priority for a Windows 11 Local Setup

1. Start (about 30 minutes): add a `PostToolUse`/`SessionEnd` hook POSTing to the local API; verify curl escaping from PowerShell.
2. Next (1-2 hours): write a `report_work` MCP tool, load via `.mcp.json`, add a CLAUDE.md instruction.
3. Advanced (2-4 hours): local OTLP collector plus telemetry env vars, ingest into the app database.
4. Autonomous scheduling (1-2 hours): Managed Agents deployment or an Agent SDK script.

### Key Success Factors

1. **Timeout handling:** add `--max-time 5` to curl commands so slow HTTP endpoints do not freeze Claude Code
2. **Error logging:** capture hook and MCP tool errors to a local log file for debugging
3. **Idempotency:** design the calendar API to handle duplicate reports (same task reported twice) gracefully
4. **Testing:** start with hooks in interactive sessions; verify the local API receives data before adding MCP or scheduled agents
5. **Path escaping:** on Windows, use absolute paths in hook commands and escape backslashes in JSON
6. **Security:** store API credentials in environment variables, not in `.claude/settings.json`

---

## Sources

- https://code.claude.com/docs/en/hooks-guide.md
- https://code.claude.com/docs/en/hooks.md
- https://code.claude.com/docs/en/monitoring-usage.md
- https://code.claude.com/docs/en/sessions.md
- https://code.claude.com/docs/en/mcp.md
- https://code.claude.com/docs/en/headless.md
- https://code.claude.com/docs/en/agent-sdk/overview.md
- https://platform.claude.com/docs/en/managed-agents/overview.md
- https://platform.claude.com/docs/en/managed-agents/scheduled-deployments.md
- https://platform.claude.com/docs/en/managed-agents/webhooks.md
