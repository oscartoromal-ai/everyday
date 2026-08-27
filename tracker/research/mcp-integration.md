# Integration Options for Claude as Planner over a Local Python Web App

Findings for ticket [Research: how Claude acts as planner over the app](../tickets/005-research-mcp-integration.md).

This document examines the integration approaches for enabling Claude to act as a planner over a local Python-backed web app (calendar, todos, projects), covering entry points, architecture patterns, auth, and cross-surface compatibility.

## 1. MCP Server Exposing App Operations

### Current State of Python MCP SDK and FastMCP

The Python MCP ecosystem has evolved into two viable paths as of August 2026.

**Official Python SDK (`mcp` package):** The official MCP SDK from modelcontextprotocol is a reference implementation that ships the decorator API as its recommended high-level interface.
FastMCP 1.0 was folded into the official SDK in 2024, and both still coexist within it.

**Standalone FastMCP:** The independent FastMCP project reached stable v3.0 on February 18, 2026, and is now maintained by PrefectHQ at github.com/PrefectHQ/fastmcp.
FastMCP 3.x is recommended for building from scratch: it has the lowest boilerplate, supports stdio and streamable HTTP transports, and is the de-facto community standard.

The June 2026 official SDK v2.0 beta renamed its bundled class from `FastMCP` to `MCPServer` to avoid confusion with the standalone project.

**Recommendation:** Pick standalone FastMCP unless your environment requires the official `mcp` package exclusively.

### Transports and Claude Surface Coverage

MCP defines three production transports as of July 2026.

**Stdio Transport (Default):**
- Standard input/output communication: a parent process launches the MCP server as a subprocess and pipes JSON-RPC over stdin/stdout.
- Zero network involvement.
- Claude Desktop and Claude Code both support stdio.
- Requires the server to run on the same machine as the client.
- Lowest latency and simplest setup for local use.

**Streamable HTTP (2026 Production Standard):**
- Long-lived HTTP connection with server-sent events for responses.
- This replaced HTTP + SSE with a single bidirectional stream.
- Supports multiple concurrent clients.
- Required for remote servers exposed over HTTPS.
- Supported by Claude Desktop, Claude Code, and claude.ai web/mobile via custom connectors.
- FastMCP 3.x has native ASGI support for mounting alongside FastAPI.

**SSE (Deprecated):**
- Server-Sent Events was the interim transport; the 2026 spec moved to Streamable HTTP.
- Still available for backward compatibility but not recommended for new projects.

**Claude Surface Compatibility:**

| Surface | Stdio | Streamable HTTP | HTTPS Requirement |
|---------|-------|-----------------|-------------------|
| Claude Code (CLI) | Yes | Yes | No (local HTTP OK) |
| Claude Desktop | Yes | Yes | No (local HTTP OK) |
| claude.ai web/mobile | No | Yes | Yes (HTTPS, public URL) |
| Claude Agent SDK | Yes (custom tools) | Yes (MCP connector) | No (local OK) |
| Claude Managed Agents | No | Yes (MCP tunnels) | No (private tunnel) |

### Sharing Database and Backend with Web App

FastAPI (or any ASGI framework) can mount an MCP server alongside its REST routes in a single process, port, and deployment.

FastMCP 3.x generates a standard ASGI application that can be mounted into a FastAPI app using `app.mount()`.
Both interfaces (REST and MCP) share identical access to your database, backend services, and authentication layer.
One process, one port: your REST endpoints answer at `/api/...` while MCP routes answer at `/mcp/...`.

FastAPI middleware (CORS, logging, rate limits, request validation) applies uniformly to both MCP and REST traffic through the outer app.

**Important:** If FastMCP is configured with OAuth, avoid layering FastAPI's CORSMiddleware on top of it; FastMCP already handles CORS for OAuth routes, and duplication can create conflicts.

### Official Documentation References

- [Model Context Protocol Overview](https://modelcontextprotocol.io)
- [Building MCP Servers](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server)
- [Claude Code MCP Integration Guide](https://code.claude.com/docs/en/mcp.md)
- [FastMCP Getting Started](https://gofastmcp.com/getting-started/welcome)
- [FastMCP + FastAPI Integration](https://gofastmcp.com/integrations/fastapi)
- [Claude Agent SDK Custom Tools](https://code.claude.com/docs/en/agent-sdk/custom-tools.md)

---

## 2. REST API Called via Bash (curl) from Claude Code or Skills

### Approach

Claude Code and the Claude Agent SDK have built-in Bash tool access.
A skill or CLAUDE.md guidance can wrap curl calls to your app's REST API.
Claude can read responses, parse JSON, and make subsequent calls.

### Advantages

- **Simplicity for small apps:** No MCP boilerplate; just HTTP verbs on familiar endpoints.
- **No subprocess overhead:** HTTP client is built-in.
- **Works offline or with custom auth:** Static API keys in headers, bearer tokens, basic auth.
- **Tooling flexibility:** Works with any web framework (FastAPI, Flask, Django, etc.).
- **Portable:** Skill guidance travels with your CLAUDE.md and can be version-controlled.

### Disadvantages

- **Permission prompts on every Bash call:** Without allowlisting in settings.json, Claude sees a permission dialog for each curl invocation. The `/fewer-permission-prompts` skill can scan transcripts and auto-allowlist read-only calls.
- **Poor discoverability:** Tools live in documentation strings or comments; Claude doesn't see structured schemas like MCP provides.
- **No schema validation:** Bash/curl loops are error-prone; Claude can misformat payloads or misread responses.
- **Not portable to claude.ai web or managed agents:** Bash is only available in Claude Code.
- **No automatic tool search:** All curl patterns must fit in context.

### Setup Example

Store API routes in your CLAUDE.md:

```markdown
## Calendar App API

- GET /api/tasks?date=YYYY-MM-DD - List tasks for a date
- POST /api/tasks - Create a task
  Body: {"title": "...", "date": "YYYY-MM-DD"}
- PUT /api/tasks/{id} - Update a task
```

Claude Code calls via Bash:

```bash
curl http://localhost:8000/api/tasks?date=2026-08-27 \
  -H "Authorization: Bearer YOUR_API_KEY"
```

---

## 3. CLI Invocation

### Approach

Your app exposes a command-line interface (e.g., `calendar-cli task add "Meeting" 2026-08-28`).
Claude Code invokes it via Bash.

### Advantages

- **Familiar CLI patterns:** Unix-style arguments and piped output.
- **Local by default:** Works on localhost without network exposure.
- **Simple auth:** Environment variables, config files, or no auth if run locally.

### Disadvantages

- **Same permission prompts as REST/Bash:** Each CLI invocation needs Bash approval.
- **Same discoverability gaps:** No structured tool schema; Claude must guess argument formats.
- **Process overhead:** Launching a subprocess for each operation is slower than HTTP.
- **Not portable:** Only works in Claude Code; can't reach claude.ai web, mobile, or Managed Agents.
- **Stateless:** CLI commands don't share session context unless explicitly threaded.

### Comparison to REST

REST via Bash and CLI via Bash have identical permission and discoverability drawbacks.
REST is preferred because HTTP libraries are more robust, and MCP can later wrap the same endpoints without rewriting.

---

## 4. Auth Story for Local Deployment

### Localhost Trust Model

**Local Stdio MCP or Local HTTP (Claude Code / Claude Desktop):**
- No authentication required; the operating system enforces access control.
- Claude runs under your user account and launches the MCP server as a subprocess.
- Network is local; interception is a physical-machine threat, not a network threat.
- API keys are unnecessary.

**Localhost with Bash/REST or CLI:**
- Can use static API keys stored in Claude's environment variables (set in settings.json with `env`).
- Can use `.netrc` or API key headers.
- Still local-only; keys are only transmitted over localhost.

### Remote Deployment (HTTPS MCP for claude.ai, Mobile, Managed Agents)

**OAuth 2.1 (Recommended for user-facing integrations):**
- Required by MCP November 2025 spec for public remote servers.
- Claude initiates OAuth flow in the browser; the server receives short-lived tokens.
- Tokens don't live in Claude's config; they're stored securely after user consent.
- Revocation is straightforward: user logs out of the connector.

**Static Bearer Tokens (For personal or internal servers):**
- API key stored in MCP server config as a custom header or via `headersHelper` script.
- Simple but less secure: token doesn't expire unless manually revoked.
- Suitable for personal deployments where you control the network.

**MCP Tunnels (For Managed Agents + private MCP servers):**
- Managed Agents can connect to MCP servers inside your private network via a lightweight gateway you deploy.
- Gateway makes a single outbound HTTPS connection to Anthropic; no inbound firewall rules needed.
- No public HTTPS endpoint; traffic is encrypted end-to-end.
- Best for compliance/data-residency scenarios.

### Auth Configuration in Claude Code and Agent SDK

Claude Code MCP server config (`.mcp.json` or `~/.claude/mcp.json`) supports:

```json
{
  "mcpServers": {
    "calendar": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

Or for dynamic tokens:

```json
{
  "mcpServers": {
    "calendar": {
      "type": "http",
      "url": "https://api.example.com/mcp",
      "headersHelper": "/opt/bin/refresh-auth-token.sh"
    }
  }
}
```

The helper script outputs JSON:

```bash
#!/bin/bash
echo '{"Authorization": "Bearer '$(get-fresh-token)'"}'
```

For Managed Agents, MCP server credentials and tunnels are configured in the agent definition, separate from the session.

### Documentation References

- [Claude Code MCP Authentication](https://code.claude.com/docs/en/mcp.md#authentication)
- [MCP Authorization and Security](https://modelcontextprotocol.io/docs/tutorials/security/authorization)

---

## 5. Serving Three Intake Paths Simultaneously

The user wants three concurrent workflows:

a) **Claude Code sessions auto-reporting work** (e.g., a daily standup agent reads your calendar and todos, summarizes them).
b) **Claude-as-planner creating/updating entries conversationally** (e.g., "Schedule a meeting for next Tuesday").
c) **Human manual entry via web UI** (existing browser interface).

All three must read and write the same database without conflicts.

### Recommended Architecture

**Single FastAPI backend with shared SQLite (or PostgreSQL) database:**

- **SQLite:** Good for single-machine or low-concurrency apps; FastMCP server and REST endpoints access the same `.db` file.
- **PostgreSQL:** Better for production; supports concurrent writes and remote access.

**Mount MCP server alongside REST routes:**

FastMCP 3.x runs as ASGI middleware inside FastAPI, sharing:
- Database connection pool or ORM session factory.
- Authentication state (if OAuth or API key validation).
- Middleware (logging, request tracking, rate limits).

Both REST and MCP operate on the same data, so a manual entry via the web UI is immediately visible to Claude via MCP tools, and vice versa.

**Workflow Example:**

1. Human creates a task via the web UI: `POST /api/tasks` writes to the database.
2. Claude Code session starts and calls MCP tool `get_tasks()`.
3. MCP server queries the same database; Claude sees the human's new task.
4. Claude updates the task status via MCP tool `update_task()`.
5. Human refreshes the web UI; it reads the updated database.

**Concurrency Handling:**

- SQLite: Single-writer rule means MCP and REST calls serialize at the database level. Acceptable if latency is under 100ms; not suitable for high-concurrency.
- PostgreSQL: Multiple concurrent writers; use versioning (optimistic locking) or row-level locking (pessimistic) to prevent clobbering.

### Data-Sharing Tools (MCP Resources and Tools)

Expose app operations as MCP tools:

```python
from fastmcp import FastMCP
from fastapi import FastAPI

mcp = FastMCP("calendar-planner", "1.0.0")
app = FastAPI()

# Shared database connection
db = get_database_connection()

@mcp.tool()
def get_tasks(date: str) -> list[dict]:
    """Retrieve tasks for a date from the shared database."""
    return db.query("SELECT * FROM tasks WHERE date = ?", [date])

@mcp.tool()
def create_task(title: str, date: str) -> dict:
    """Create a task in the shared database."""
    task_id = db.execute(
        "INSERT INTO tasks (title, date) VALUES (?, ?)",
        [title, date]
    )
    return {"id": task_id, "title": title, "date": date}

# Mount MCP and REST on the same app
app.mount("/mcp", mcp.asgi())

@app.post("/api/tasks")
async def rest_create_task(title: str, date: str):
    return create_task(title, date)  # Reuses MCP handler
```

### Integration Points Across Surfaces

| Intake | Tool | Surface | Auth | Concurrency |
|--------|------|---------|------|-------------|
| Claude Code auto-report | MCP server (stdio or HTTP) | Claude Code | Localhost (none needed) | Serialized at DB level |
| Claude planner (conversational) | MCP tools or Agent SDK custom tools | Claude Code, Claude Agent SDK, Managed Agents | Localhost or OAuth | Serialized at DB level |
| Human manual entry | REST API | Web browser | Session cookie or API key | Application-level locking |

### Avoiding Conflicts

1. **Use transactions:** Wrap read-modify-write operations in database transactions.
2. **Implement optimistic locking:** Include a `version` column; update only if version hasn't changed.
3. **Rate-limit or serialize critical operations:** If calendar slots are precious, enforce single-writer via a lock table.

### Documentation References

- [MCP Resources and Tools Specification](https://modelcontextprotocol.io/docs/2026-07-28/learn/server-concepts)
- [SQLite as Shared Backend](https://www.sqlite.org/bestpractice.html)
- [FastAPI + Database Concurrency](https://fastapi.tiangolo.com/)

---

## Comparison and Recommendation Shape

### Option Matrix

| Option | Claude Code | Claude Desktop | claude.ai Web/Mobile | Claude Agent SDK | Managed Agents | Setup Cost | Portability | Long-Term Maintenance |
|--------|-------------|-----------------|---------------------|------------------|----------------|-----------|-------------|----------------------|
| **MCP Server (Stdio)** | Yes | Yes | No | Yes (custom tools) | No | Low | Low (local only) | Very Low |
| **MCP Server (HTTP)** | Yes | Yes | No (needs HTTPS) | Yes | No | Medium | Medium (localhost) | Low |
| **MCP Server (HTTPS Remote)** | Yes | Yes | Yes (OAuth) | Yes (tunnels) | Yes | High | High | Medium |
| **REST + Bash/CLI** | Yes | No | No | No | No | Low | Very Low | Very Low (Claude Code only) |
| **Claude Agent SDK Custom Tools** | Yes | No | No | Yes | No | Medium | Low (in-process) | Low |
| **Claude Managed Agents** | No | No | No | No | Yes | Very High | High | High (cloud-hosted) |

### Recommendation for Three Intake Paths

**Single Best Option: FastMCP 3.x Server + FastAPI with Shared SQLite Backend**

Start with this stack if the user is developing locally and wants Claude to plan across Claude Code, Claude Desktop, and the web UI:

1. **FastAPI app** serves the web UI and REST API.
2. **FastMCP 3.x server** mounted at `/mcp/` on the same app; shares the SQLite database and authentication.
3. **Claude Code/Desktop** connects via local HTTP: `http://localhost:8000/mcp` (no HTTPS, no auth needed).
4. **Web browser** accesses the UI at `http://localhost:8000/`.
5. **Same SQLite database** powers all three; transactions prevent conflicts.

**Setup Cost:** Low (FastMCP + FastAPI examples are abundant).
**Maintenance:** Very low (single codebase, single deployment).
**Scaling Path:** If the user later needs claude.ai web or mobile access, expose the same MCP server over HTTPS with OAuth and register it as a remote connector.

### Alternative: REST + Claude Code (if MCP feels heavyweight)

If the user prefers minimal boilerplate and accepts Claude Code-only planning:

1. FastAPI app serves both UI and REST API.
2. Claude Code calls endpoints via Bash; `/fewer-permission-prompts` allowlists read-only calls.
3. Use CLAUDE.md to document API routes and request formats.
4. Same SQLite backend for all.

**Setup Cost:** Minimal.
**Trade-off:** No discoverability; permission prompts on writes; doesn't scale to claude.ai or Managed Agents.

### Hybrid Path (Maximum Reach)

If the user wants to support Claude Code now and claude.ai later:

1. **Start with local FastMCP + FastAPI** (low cost, immediate value).
2. **Add remote HTTPS endpoint** (expose via ngrok for testing, then a real domain).
3. **Implement OAuth** (for claude.ai registration).
4. **Register in the Claude Connector Directory** (optional, for discoverability).

This path defers the scaling cost and lets you test the integration locally before committing to HTTPS infrastructure.

---

## Key Takeaways

1. **MCP is the future-proof choice:** A single FastMCP server at localhost works with Claude Code, Claude Desktop, and the web UI today, and scales to claude.ai, mobile, and Managed Agents without rewriting.

2. **FastMCP 3.x + FastAPI is the minimal viable stack:** One process, one port, shared database, no subprocess overhead. Documentation and examples are mature as of August 2026.

3. **Local stdio MCP requires zero authentication:** Claude runs under your user account; the OS enforces isolation. Add API keys only if you expose the app over HTTPS or share it with others.

4. **Concurrent access to a shared database is manageable:** Use transactions and optimistic locking. SQLite is fine for single-machine prototypes; scale to PostgreSQL if multiple writers contend frequently.

5. **REST + Bash is viable but limiting:** Works today in Claude Code, but permission prompts and poor discoverability become pain points as the app grows. Reserve it for simple cases or as a fallback if MCP setup stalls.

---

## Sources

- https://modelcontextprotocol.io
- https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server
- https://code.claude.com/docs/en/mcp.md
- https://gofastmcp.com/getting-started/welcome
- https://gofastmcp.com/integrations/fastapi
- https://code.claude.com/docs/en/agent-sdk/custom-tools.md
- https://platform.claude.com/docs/en/managed-agents/overview
- https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop
- https://startdebugging.net/2026/07/mcp-stdio-vs-http-vs-sse-transport-which-to-choose/
- https://mcp.directory/blog/fastmcp-vs-fastapi-mcp-vs-python-sdk-2026
- https://dev.to/sraveend/shipping-a-mcp-server-alongside-your-api-48d7
- https://medium.com/@ekkyarmandi/mount-stream-authenticate-fastmcp-with-fastapi-ea2ef6f45b2a
- https://www.agentcat.com/guides/building-mcp-server-python-fastmcp/
