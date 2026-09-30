# Personal Calendar

Oscar's locally-run personal planner: a hybrid calendar, to-do lists, and projects in one app, doubling as the control panel for work delegated to Claude.
It runs as a single FastAPI process on Oscar's own machine, backed by one SQLite database, with no cloud backend and no login screen.
Claude reads and writes the same plan data through a mounted MCP server.
The full spec, including the domain model, the work-calendar integration, nudges, and the security model, lives in [SPEC.md](SPEC.md).

## Dev setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
uv run alembic upgrade head
uv run watchfiles --filter python "uvicorn app.main:app --port 8378" app
```

The dev server serves at `http://127.0.0.1:8378`, beside the always-on app on 8377, and restarts when a Python file under `app/` changes (templates and static files are picked up without a restart).
It runs a single interface and no scheduler.
It opens the same database as the always-on app unless `PC_STORAGE__DB_PATH` points it at a copy.
Restarts go through `watchfiles`, not `uvicorn --reload`: on Windows, uvicorn restarts its worker with a console Ctrl+C event, and in a terminal without a real console (Git Bash, a background job, an agent's shell) that event reaches nobody, so the reload waits forever while the old code keeps serving.
Avoid `fastapi dev` on Windows: its banner prints emoji that crash a cp1252 console.
To run it the way it runs in production, with the scheduler and every configured bind host, use the installed script instead:

```
uv run personal-calendar
```

## Tests and lint

```
uv run pytest
uv run ruff check .
```

Both must stay green.
Fix lint errors, test failures, and flaky tests on sight, even ones unrelated to what you're changing (SPEC.md section 10).

## Connecting Claude Code to the MCP server

With the app running, add it as a user-level MCP server:

```
claude mcp add --scope user --transport http personal-calendar http://127.0.0.1:8377/mcp/
```

This gives any Claude Code session the planner tools (list/upsert projects and tasks, update task status, get the agenda, read the day's notes and a task's history, schedule a block, add an event) against the same database the web UI uses.
No auth is required locally; the trust boundary is the network (localhost and the tailnet), not a token.

## Nutrition chat setup

Nutrition's chat runs Claude through the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk), which drives the Claude Code CLI installed and logged in on this machine: no API key is needed, and it runs on that login.

1. Install Claude Code and log in once (`claude`, then `/login`).
2. On Windows the SDK only runs a native `claude.exe`, never npm's `claude.cmd` shim.
   With `[nutrition].claude_cli` empty in `config.toml`, the app finds `claude` on PATH and, when that is the npm shim, the `claude.exe` npm installed beside it; otherwise set `claude_cli` to a `claude.exe`.
3. `[nutrition].dir` names the folder of Markdown files it reads and writes (`nutrition/` in the repo by default); `[nutrition].model` the model.

The files are the record, outside the database and its backups: git keeps their history.

## Work-calendar setup

The work calendar syncs in read-only, via a published ICS feed, subject/time/location only.

1. In Outlook, publish the work calendar at the "Can view titles and locations" level and copy the ICS URL it gives you.
2. Save that URL, and nothing else, into `local/work-calendar-ics-url.txt`.
   That file is git-ignored; the app reads it at runtime and it never enters the repo or the tracker.
3. Poll times are set in `config.toml` under `[work_calendar]`, morning-weighted by default (`06:30`, `12:30`, `16:30`).
4. To sync outside the scheduled times, use the "Sync work" button on the calendar page.

## Phone push setup

Push notifications go through a managed [ntfy.sh](https://ntfy.sh) topic.

1. Pick an unguessable topic name (ntfy topics are unauthenticated by name alone) and create an access token for it at ntfy.sh.
2. Put the topic name into `local/ntfy-topic.txt` and the token into `local/ntfy-token.txt`.
   Both files are git-ignored.
3. Quiet hours and the morning digest time are set in `config.toml` under `[push]`.
   Only the morning digest and genuinely time-sensitive nudges (a block just missed) push through; everything else waits for the in-app nudge center.

## Tailscale access

The phone reaches the app over Tailscale, with no port forwarding and no public exposure.

1. Install Tailscale on this machine and on the phone, and join both to the same tailnet.
2. Set `server.tailscale_ip` in `config.toml` to this machine's `100.x` Tailscale address.
   `uv run personal-calendar` then binds both `127.0.0.1` and that address.
3. Add the machine's Tailscale MagicDNS name and its `100.x` address to `server.extra_hosts` in `config.toml`, so the browser-guard middleware accepts requests addressed to them.

## Backups and restore

A daily job (03:30 local time) snapshots the database with SQLite's backup API into the directory configured at `[backup].dir` in `config.toml`, defaulting to `backups/` under the repo root.
Point `dir` at a cloud-synced folder for off-machine durability; the exact path is TBD, Oscar's to set.
Snapshots are named `personal-calendar-YYYY-MM-DD.db`; the job keeps the newest `[backup].retain` of them (30 by default) and prunes the rest.

To restore:

1. Stop the app (close the terminal running it, or stop the "Personal Calendar" scheduled task).
2. Copy the desired snapshot over `data/personal-calendar.db`.
3. Start the app again.

## Windows autostart

`scripts/run-app.ps1` runs the app in the foreground of whatever shell invokes it.
`scripts/install-startup-task.ps1` registers a Windows Task Scheduler task named "Personal Calendar" that runs `run-app.ps1` hidden, at logon, via `powershell -WindowStyle Hidden -ExecutionPolicy Bypass`.

To install it:

```
.\scripts\install-startup-task.ps1
```

This makes the app effectively always-up while Oscar is logged in, which the work-calendar poll and nudge jobs assume.
The task has no execution time limit; Task Scheduler's default of 72 hours would stop the app after three days.

The hidden app's output goes to `data/logs/personal-calendar.log` (rotated at 5 MB, five kept), including why it stopped: Ctrl+C, a closed console, or an uncaught error.

To restart it, for example after pulling changes:

```
Stop-ScheduledTask -TaskName "Personal Calendar"; Start-ScheduledTask -TaskName "Personal Calendar"
```

Stopping the task stops the whole app.
Task Scheduler only terminates the PowerShell process it launched, so `run-app.ps1` first joins a kill-on-close job object; the app's process chain (uv, the entry-point shim, the interpreter) inherits it and exits with that PowerShell process instead of living on as an orphan.
To remove the task later:

```
Unregister-ScheduledTask -TaskName "Personal Calendar" -Confirm:$false
```
