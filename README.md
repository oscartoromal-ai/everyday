# Personal Calendar

Oscar's locally-run personal planner: a hybrid calendar, to-do lists, and projects in one app, doubling as the control panel for work delegated to Claude.
It is a Windows desktop app: one process on Oscar's own machine holds the window, a FastAPI server and its jobs, backed by one SQLite database in the app's own folder, with no cloud backend and no login screen.
Claude reads and writes the same plan data through a mounted MCP server.
The full spec, including the domain model, the work-calendar integration, nudges, and the security model, lives in [SPEC.md](SPEC.md).

## Dev setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
uv run alembic upgrade head
uv run watchfiles --filter python "uvicorn app.main:app --port 8378" app
```

The dev server serves at `http://127.0.0.1:8378`, beside the desktop app on 8377, and restarts when a Python file under `app/` changes (templates and static files are picked up without a restart).
It runs a single interface and no scheduler.
Run from the repo, the app's home (see [Where the data lives](#where-the-data-lives)) is the repo itself, so the dev server opens `data/personal-calendar.db`, a copy of its own, not the desktop app's.
To refresh that copy from the live database, run `uv run python scripts/copy-live-db.py`, then `uv run alembic upgrade head` when the repo's code has migrations the copy lacks.
Restarts go through `watchfiles`, not `uvicorn --reload`: on Windows, uvicorn restarts its worker with a console Ctrl+C event, and in a terminal without a real console (Git Bash, a background job, an agent's shell) that event reaches nobody, so the reload waits forever while the old code keeps serving.
Avoid `fastapi dev` on Windows: its banner prints emoji that crash a cp1252 console.
To run the whole app from source, with the scheduler, every configured bind host and the database migrated as it starts, quit the desktop app (both serve on 8377) and use one of the installed scripts:

```
uv run personal-calendar-desktop   # with its window and tray icon
uv run personal-calendar           # the server alone, in the terminal
```

## The desktop app

The app is installed as a Windows program of its own: Start menu entry, taskbar button, its own window (Edge WebView2, no browser) and a tray icon.
One process holds the window, the server on `127.0.0.1:8377` and the scheduler, so Claude's MCP, the jobs and the phone reach it as long as it runs.
Closing the window hides it to the tray, and the app keeps running; Quit, on the tray icon's menu, stops it.
The tray icon's menu also opens Today, Calendar, Projects or New task, and a dot on it, like the number on the taskbar button, counts the nudges waiting.
Launching it again while it runs brings its window forward.

### Updating it

Develop in the repo (the dev server, the tests), and commit.
Once the repo has a commit newer than the installed app's, the app shows **Update** at the foot of its sidebar (and in the command menu, Ctrl+K).
Pressing it builds that commit and installs it in the background, a few minutes, while the app carries on; the app then closes and opens again on the new version, its database migrated as it starts.
Only commits go into an update, never uncommitted work, which is built in a worktree of its own (`desktop/update.ps1`).
If the build or the install fails, the button says so and offers Retry; why is in `data/logs/update.log` in the app's home.
Windows' Installed apps lists the version with the commit it was built from.

### Building and installing by hand

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) besides the dev setup (`winget install JRSoftware.InnoSetup --scope user`).

```
.\desktop\build.ps1            # build build\Personal-Calendar-Setup.exe from the working tree
.\desktop\build.ps1 -Install   # build it and install it over the running app
```

This is how the app is first installed, and how to try uncommitted changes in it (the version then carries a `+` after its commit).
PyInstaller freezes the app with its own Python (`desktop/personal-calendar.spec`), and Inno Setup wraps it into a per-user installer (`desktop/installer.iss`) that needs no admin rights.
The installer puts the app in `%LOCALAPPDATA%\Programs\Personal Calendar`, adds it to the Start menu, and, unless unticked, starts it in the tray when Oscar signs in (the `Personal Calendar` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
The installed app runs the code it was built from, never the repo's.
Installing over a running app asks it to quit first (`POST /desktop/quit`), replaces it, and opens the new one.
Uninstalling it (Installed apps) removes the program and its sign-in entry and keeps its data.

### Another machine

`build\Personal-Calendar-Setup.exe`, left in the repo by every build and every update, is the whole app: copy it to another Windows 10 or 11 machine and run it, with nothing else to install (WebView2 comes with Windows).
Windows warns about it first, since it is not signed (More info, then Run anyway).
That machine starts with an empty database of its own, and has no Update button unless the repo is checked out at the same path.

After changing `app/static/favicon.svg`, redraw the icons with `uv run python scripts/make_icons.py`.

### Where the data lives

Everything the app keeps lives under its home, `%LOCALAPPDATA%\Personal Calendar`:

- `data/personal-calendar.db`: the database, created and migrated by the app as it starts; an app older than its database refuses to start rather than touch it.
- `data/logs/personal-calendar.log`: what the app logs, rotated at 5 MB, five kept, including why it stopped.
- `data/desktop.json` and `data/webview/`: the window's place and the window's own browser storage (theme, sidebar, compact rows).
- `backups/`: the daily snapshots (see [Backups and restore](#backups-and-restore)).
- `local/`: the machine's secrets (work-calendar feed, ntfy, Garmin's token), git-ignored in a repo checkout.
- `config.toml`: this machine's settings, over the defaults in the repo's `config.toml` that the app is built with, key by key; relative paths in either resolve against the home.

`PC_HOME` names another home, and run from the repo the home is the repo itself.
On Oscar's machine the home's `config.toml` keeps Nutrition's files in the repo (`[nutrition].dir`), where git keeps their history.

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

This gives any Claude Code session the planner tools (list/upsert projects and tasks, update task status, get the agenda, read the day's notes and a task's history, add an event) against the same database the web UI uses.
No auth is required locally; the trust boundary is the network (localhost and the tailnet), not a token.

## Nutrition and Spending chat setup

Nutrition's and Spending's chats run Claude through the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk), which drives the Claude Code CLI installed and logged in on this machine: no API key is needed, and it runs on that login.

1. Install Claude Code and log in once (`claude`, then `/login`).
2. On Windows the SDK only runs a native `claude.exe`, never npm's `claude.cmd` shim.
   With `[claude].cli` empty in `config.toml`, the app finds `claude` on PATH and, when that is the npm shim, the `claude.exe` npm installed beside it; otherwise set `cli` to a `claude.exe`.
3. `[nutrition].dir` names the folder of Markdown files Nutrition's chat reads and writes (`nutrition/` in the app's home by default); `[nutrition].model` and `[money].model` the models.

The files are the record, outside the database and its backups: git keeps their history.

## Finances setup

Finances (Spending, Accounts, Bills, Goals) is fed by the CSV exports of Oscar's banks: Revolut and ING Australia.

1. Export a statement as CSV from the bank's app or website.
2. On Accounts, choose the file and the account it goes into ("A new account" names one after the bank), then Import.
   Importing the same export again, or one that overlaps, adds only what is new.
3. Sort what landed on Spending, by hand on each transaction's line or by asking Claude in the chat, which also adds rules so later imports sort themselves.

Balances without an export (super, shares) are written by hand on Accounts.

## Garmin setup

Health > Garmin syncs Oscar's Garmin metrics from Garmin Connect, through [python-garminconnect](https://github.com/cyberjunky/python-garminconnect).

1. Open Garmin in the app and sign in with the Garmin Connect email and password, then the code Garmin sends if the account uses two-step sign-in.
2. The password is used once and never stored.
   Garmin's token is saved to `local/garmin/garmin_tokens.json` in the app's home (`[garmin].token_dir` in `config.toml`), and the library keeps it fresh.
3. The first sync fetches the last 30 days; after that the app syncs every 30 minutes while it runs, or on "Sync now" (`[garmin]` in `config.toml`).
4. If Garmin signs the app out, the page asks to sign in again; Disconnect deletes the token, and the synced days stay.

Garmin has no API for individuals, so the library signs in as Garmin's mobile app does, and a change on Garmin's side can break it until the library catches up (`uv lock --upgrade-package garminconnect`).

## Work-calendar setup

The work calendar syncs in read-only, via a published ICS feed, subject/time/location only.

1. In Outlook, publish the work calendar at the "Can view titles and locations" level and copy the ICS URL it gives you.
2. Save that URL, and nothing else, into `local/work-calendar-ics-url.txt` in the app's home.
   The app reads it at runtime and it never enters the repo or the tracker.
3. Poll times are set in `config.toml` under `[work_calendar]`, morning-weighted by default (`06:30`, `12:30`, `16:30`).
4. To sync outside the scheduled times, use the "Sync work" button on the calendar page.

## Phone push setup

Push notifications go through a managed [ntfy.sh](https://ntfy.sh) topic.

1. Pick an unguessable topic name (ntfy topics are unauthenticated by name alone) and create an access token for it at ntfy.sh.
2. Put the topic name into `local/ntfy-topic.txt` and the token into `local/ntfy-token.txt`, in the app's home.
3. The morning digest time is set in `config.toml` under `[push]`.
   Only the morning digest pushes through; everything else waits for the in-app nudge center.

## Tailscale access

The phone reaches the app over Tailscale, with no port forwarding and no public exposure.

1. Install Tailscale on this machine and on the phone, and join both to the same tailnet.
2. Set `server.tailscale_ip` in the home's `config.toml` to this machine's `100.x` Tailscale address.
   The app then binds both `127.0.0.1` and that address.
3. Add the machine's Tailscale MagicDNS name and its `100.x` address to `server.extra_hosts` there too, so the browser-guard middleware accepts requests addressed to them.
4. Quit the app from its tray icon and open it again.

## Backups and restore

A daily job (03:30 local time) snapshots the database with SQLite's backup API into the directory configured at `[backup].dir`, `backups/` in the app's home by default.
Point `dir` at a cloud-synced folder for off-machine durability; the exact path is TBD, Oscar's to set.
Snapshots are named `personal-calendar-YYYY-MM-DD.db`; the job keeps the newest `[backup].retain` of them (30 by default) and prunes the rest.

To restore:

1. Quit the app from its tray icon.
2. Copy the desired snapshot over `data/personal-calendar.db` in the app's home, and delete the `-wal` and `-shm` files beside it.
3. Open the app again.
