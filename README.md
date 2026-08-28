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
uv run fastapi dev app/main.py
```

The app serves at `http://127.0.0.1:8377`.
`fastapi dev` is the quickest loop for local development (auto-reload, single interface).
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

This gives any Claude Code session the planner tools (list/upsert projects and tasks, update task status, get the agenda, schedule a block, add an event) against the same database the web UI uses.
No auth is required locally; the trust boundary is the network (localhost and the tailnet), not a token.

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
To remove the task later:

```
Unregister-ScheduledTask -TaskName "Personal Calendar" -Confirm:$false
```
