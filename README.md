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

Develop in the repo (the dev server, the tests), commit, and merge the pull request on GitHub.
The app fetches the repo's `origin/master` in the background every minute, whatever the repo has checked out.
Once it is past the installed app's commit, the app builds that commit by itself, in the background, while the app carries on, and stages it beside the running version.
The foot of its sidebar (and the command menu, Ctrl+K) says **Updating…** meanwhile, then **Restart to update**, and waits for you.
An update whose libraries are the running version's (`uv.lock` and the freezing unchanged) takes seconds: it copies the running version and puts the new code in; one that changes them freezes the app anew, a few minutes.
Pressing Restart restarts the app on the new version in about a second: the new version, started beforehand to stand by with its code and window loaded, comes up where the old window was, at the same page, over it, and the old one goes; its database migrates as it takes over.
Only commits go into an update, never uncommitted work, which is built in a worktree of the app's own (`data/update-worktree`, kept between updates with its Python environment) by the app's own copy of `desktop/update.ps1`, bundled with it.
If the build or the restart fails, the button says so and offers Retry (a commit that failed is not built again by itself, only once master moves on); why is in `data/logs/update.log` (the build), `data/logs/update-console.log` (a script that would not run at all) or `data/logs/personal-calendar.log` (the restart, and `standby.log` for the version standing by) in the app's home.
A restart that fails comes back up on the version it was running.
**Update** shows only when the app has not started one itself; Settings' Check for updates looks at GitHub at once.
Windows' Installed apps lists the version with the commit it was built from.

### Building and installing by hand

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) besides the dev setup (`winget install JRSoftware.InnoSetup --scope user`).

```
.\desktop\build.ps1            # build build\Personal-Calendar-Setup.exe from the working tree
.\desktop\build.ps1 -Install   # build it and install it over the running app
```

This is how the app is first installed, and how to try uncommitted changes in it (the version then carries a `+` after its commit).
PyInstaller freezes the app with its own Python (`desktop/personal-calendar.spec`), the C# compiler that comes with Windows builds its launcher (`desktop/launcher.cs`), and Inno Setup wraps both into a per-user installer (`desktop/installer.iss`) that needs no admin rights.
Python and the libraries are frozen; the app's own code and files (`app/`, and the ones `desktop/app-files.txt` lists) go in as they are, so that an update can put them in a copy of the running version (`build.ps1 -Reuse`).
Every build then checks itself (`--self-check`, `app/selfcheck.py`): it compiles the app's code, imports all of it, and makes sure every module it imports anywhere is in the build.
Its first page, Modules, ticks the modules the machine should have: Health, Finances and Code can be left out (Planner and Projects are always in), and the app then has nothing of them, neither pages nor Claude's tools for them.
Its next page, Everyday files, chooses the folder for agentic work, `C:\everyday-files` to start with (see [Where the data lives](#where-the-data-lives)), and makes it.
Setup writes both choices to `install.toml` in the app's home and remembers them for the next install, a silent one included; run Setup again to change them.
The installer puts the app in `%LOCALAPPDATA%\Programs\Personal Calendar`, adds it to the Start menu, and, unless unticked, starts it in the tray when Oscar signs in (the `Personal Calendar` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
That folder holds the launcher, `Personal Calendar.exe`, which the shortcuts start, and each version in a folder of its own, `app-<commit>`; the launcher starts the one `current.txt` names.
An update stages the next version in a folder beside the running one, and the new version rewrites `current.txt` once its window is up; the version before it goes at the next update.
The installed app runs the code it was built from, never the repo's.
Installing over a running app asks it to quit first (`POST /desktop/quit`), replaces it, and opens the new one.
Uninstalling it (Installed apps) removes the program and its sign-in entry and keeps its data.

### Another machine

`build\Personal-Calendar-Setup.exe`, left in the repo by every build by hand, is the whole app: copy it to another Windows 10 or 11 machine and run it, with nothing else to install (WebView2 comes with Windows).
Windows warns about it first, since it is not signed (More info, then Run anyway).
That machine starts with an empty database of its own, and has no Update button unless the repo is checked out at the same path.
For work, untick Finances (or Health) on Setup's Modules page.

After changing `app/static/favicon.svg`, redraw the icons with `uv run python scripts/make_icons.py`.

### Where the data lives

Everything the app keeps lives under its home, `%LOCALAPPDATA%\Personal Calendar`:

- `data/personal-calendar.db`: the database, created and migrated by the app as it starts; an app older than its database refuses to start rather than touch it.
- `data/logs/personal-calendar.log`: what the app logs, rotated at 5 MB, five kept, including why it stopped.
- `data/desktop.json` and `data/webview/`: the window's place and the window's own browser storage (theme, sidebar, compact rows).
- `data/improve/`: the daily improvement scan's reports, ledger and brief, and its checkout of master (see [Improving itself](#improving-itself)).
- `backups/`: the daily snapshots (see [Backups and restore](#backups-and-restore)).
- `local/`: the machine's secrets (work-calendar feed, ntfy, Garmin's token, a GitHub token if one was pasted), git-ignored in a repo checkout.
- `config.toml`: this machine's settings, over the defaults in the repo's `config.toml` that the app is built with, key by key; relative paths in either resolve against the home.
- `install.toml`: the modules this machine was installed without (`[install] without`) and the everyday files' folder (`[everyday_files] dir`), written by Setup on every install, over both.
- `keys.toml`: the keys chosen over the defaults (see [Keys](#keys)), git-ignored in a repo checkout.

`PC_HOME` names another home, and run from the repo the home is the repo itself.

The everyday files live outside the home, in `C:\everyday-files` unless another folder was chosen on Setup's Everyday files page (SPEC.md, Agent runs):

- `repos/`: each repository's main clone, once.
- `projects/`: a folder for each project, its context: its documents as Markdown files (AGENTS.md first) and `project.toml` (its id and repositories). These files are the master copy: the app reads them into the database as it starts, as a project's page opens, and as they change while it runs, so an editor or an agent may write them; a folder made there is a new project.
- `work/`: the folders agents work in.

Run from the repo, the app keeps its own `everyday-files/` in it (git-ignored), never the real one.
On Oscar's machine the home's `config.toml` keeps Nutrition's files in the repo (`[nutrition].dir`), where git keeps their history.

## Keys

Every action a key does is listed in `app/services/keys.py`, with an id, where it works and its default keys.
The keys chosen over them live in `keys.toml` in the app's home, an action a line:

```toml
[keys]
"app.search" = "Ctrl+P"          # one key
"task.new" = ["N", "Shift+N"]    # several
"app.theme" = []                 # none
```

Keyboard (Settings, or Ctrl+K "Change the keys") writes it, and so can any text editor: the app reads it again as it changes, and lists there what in it could not be used.
`GET /ui/keys` returns every action, its keys and its defaults as JSON, `PUT /ui/keys/<action>` with `{"keys": [...]}` sets an action's, and `DELETE /ui/keys/<action>` (or `/ui/keys`, every one) puts the defaults back.
`uv run python -m app.services.keys` prints them all.

## Recording a change

Every pull request that changes the app adds a file to `changes/`, named `YYYY-MM-DD-what.md`, saying what changed for Oscar, one item per change:

```
- Feature: Give tasks a priority, shown wherever tasks are
  Lines indented under a change say more, in Markdown.
- Fix: The Update button no longer fails at once
```

A change is a **Major** (a new area of the app, or one reshaped), a **Feature** (something new or changed in one) or a **Fix** (what was wrong, put right).
Nobody writes a version number: each commit on master's line that brings change files is a version, numbered from the one before it by its largest change (a Major bumps the major number, a Feature the minor, a Fix the patch), so pull requests open at once never claim the same number or conflict.
The Changelog, opened from Settings (or Ctrl+K), lists every version and what it changed, and Settings says which version is running; `uv run python -m app.changelog` prints the same.
A change written after it shipped names its commit on master's line in front matter (`shipped: <commit>`), as the files for the versions before `changes/` existed do.
A file is never renamed once merged: its version is the commit that added it.
The tests read every file in `changes/`, and the build refuses one written wrong.

## Tests and lint

```
uv run pytest
uv run ruff check .
```

Both must stay green.
Fix lint errors, test failures, and flaky tests on sight, even ones unrelated to what you're changing (SPEC.md section 10).

## Improving itself

Every day the app scans itself for what could be better (`improve/`).
After 02:30, or as soon as it is next up and awake, the installed app fetches origin's master into a checkout of its own (`data\improve\checkout`, a worktree of the repo) and runs `python -m improve.scan` there, at low priority.
The scan reads the live app's log and database, never writing to them, and runs master's tests, lint and dependency checks.

What it looks for, the most pressing first: tests failing on master, errors in the app's log, routes answering with server errors, vulnerable dependencies, flaky tests, lint, tasks on the app's project whose owner is Claude, slow routes, a slow test suite, outdated dependencies.
The tasks are the project's that lists the repo on its page; `[improve] project` in the home's `config.toml` names one otherwise.

Each finding goes into a ledger, `data\improve\ledger.json`, which remembers it across days: open, picked (being fixed), done (its fix merged; it opens again should it come back) or ignored.
The day's report is `data\improve\reports\<day>.md`, and the most pressing open finding is written up in `data\improve\brief.md`, a brief for an agent to fix it.

The pick is then fixed by an agent (`improve/run.py`), and everything around the fix is scripted:

- **Launch**, after the scan: when fewer than `[improve] max_open` picks are being fixed (one by default), the next is handed to the runner `[improve] runner` names (`t3`: T3 Code, `app/services/agent_runs.py`; empty only scans).
  It gets a worktree of the repo on a branch of its own (`improve/<day>-<fingerprint>`, in T3 Code's worktrees folder), and a T3 thread in full-access mode with the brief, where to work, and the app project's AGENTS.md.
- **Follow**, before the scan and every hour between: each pick's pull request is found from its branch on GitHub.
  Its newest commit passes master's gate (`improve.check`, run on a checkout of it in `data\improve\gate`), which comments the outcome on the pull request once per commit, and says so loudly when the change touches the loop itself.
  Merged, the pick is done; closed unmerged, it is ignored (Oscar turned it down).
  A run that ended without a pull request opens its pick again, and after two such runs the pick is given up on.
  The run's state comes from T3 itself (working, waiting on Oscar, finished, failed, gone), never from the agent.
- Nothing merges on its own: Oscar reviews the pull requests (his call on 2026-10-04).

For the routes, the app counts its own use (`app/usage.py`): each request by the route that answered it and the day, with whether it failed and how long its response took to start.
It keeps routes only (`GET /projects/{project_id}`), never what was looked at.

By hand, from a checkout:

```
uv run python -m improve.scan                 # over the live app's data; --only tests,lint for some sources
uv run python -m improve.ledger list
uv run python -m improve.ledger mark <fingerprint> ignored --note "why"
uv run python -m improve.check                # the gate a fix passes: lint and tests (--build builds the app too)
uv run python -m improve.run follow --repo C:\Users\me\personal-calendar
uv run python -m improve.run launch --repo C:\Users\me\personal-calendar
```

`[improve] enabled = false` in the home's `config.toml` turns the daily scan off, and `runner = ""` keeps the scan but launches no agent.

## Connecting Claude Code to the MCP server

With the app running, add it as a user-level MCP server:

```
claude mcp add --scope user --transport http personal-calendar http://127.0.0.1:8377/mcp/
```

This gives any Claude Code session the planner tools (list/upsert projects and tasks, update task status, report on a task, get the agenda, read the day's notes, a task's history and a project's context, add an event, list the GitHub repositories) against the same database the web UI uses.
No auth is required locally; the trust boundary is the network (localhost and the tailnet), not a token.

## Agents reporting on a task

An agent working on a task reports on it with one HTTP call, any agent system, MCP or not (SPEC.md, Agent runs):

```
curl -X POST http://127.0.0.1:8377/api/tasks/62/report -H "Content-Type: application/json" \
  -d '{"status": "needs_review", "note": "Ready for a look.", "outcome": "Added the window.", "pull_requests": ["https://github.com/me/app/pull/41"]}'
```

Every field is optional.
`status` goes as far as `needs_review` (`in_progress`, `blocked`, `needs_review`), never `done`: a task is done once its pull requests all merge, which the app reads from GitHub every few minutes, or when Oscar says so.
A note is kept as one of the task's updates, and the outcome is written over the one it had; all of it shows on the task's page, under Agent work.
The JSON body stands in for the pages' CSRF token, so no cookie is needed; MCP's `report_task` does the same.

## Models and the chats

The app reaches models through the CLIs signed in on this machine, never an API key of its own: Claude through Claude Code, OpenAI through the Codex CLI.
Models, opened from Settings (or Ctrl+K), shows how each stands, the models it offers and the one each of the app's features runs on.

1. Install Claude Code and sign it in once (`npm install -g @anthropic-ai/claude-code`, then `claude auth login`); for OpenAI, the Codex CLI (`npm install -g @openai/codex`, then `codex login`).
2. Each is found on PATH; on Windows the Agent SDK only runs a native `claude.exe`, so npm's `claude.cmd` shim leads to the `claude.exe` beside it.
   A CLI found elsewhere is pointed to on Models.
3. Nutrition's and Spending's chats run Claude through the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk) on the model and effort chosen for them on Models.
   `[nutrition].dir` names the folder of Markdown files Nutrition's chat reads and writes (`nutrition/` in the app's home by default).

The files are the record, outside the database and its backups: git keeps their history.

## Agent window setup

The agent window (Agent at the foot of the sidebar, or A) chats with Claude or Codex, the CLIs set up above (Models and the chats), on this machine's sign-ins, so it runs on your subscriptions and needs no API key.
Each is a use of its own on Models ("Agent window: Claude", "Agent window: Codex"), where its model and effort are chosen.
An agent whose CLI is not installed or not signed in says so in the window, with the commands that put it right.

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

## GitHub setup

Repositories (under Code in the sidebar, or 8) lists the GitHub repositories Oscar can reach, synced from GitHub.

1. Open Repositories.
   When the [GitHub CLI](https://cli.github.com) on this machine is signed in, it lists the accounts it is signed in to; press Connect on one.
   That is all: the app asks `gh` for the account's sign-in at each sync (`gh auth token --user`) and keeps no copy of it.
2. Without the CLI, install it (`winget install GitHub.cli`) and sign in once (`gh auth login`), then press Check again.
3. Or paste a token instead.
   "Make one on GitHub" opens GitHub's form already filled in for a read-only, metadata-only token; choose All repositories, Generate token, and paste it.
   It is kept in a file of the account's own in `local/github-tokens/` in the app's home (`[github].tokens_dir`).
4. To connect another account, sign gh in to it too (`gh auth login` again), then open Add another account under the accounts and press Connect on it, or paste a token for it.
   A repository two accounts reach is listed once.
5. The first sync starts on connecting; after that the app syncs every account every hour while it runs (`[github].sync_minutes`), or on Sync now.
6. If GitHub stops accepting an account's sign-in (the CLI signed out of it, or its token revoked), its row says so and asks to connect it again; its repositories stay, and the other accounts sync on.
   Disconnect on an account forgets the repositories only it reached and deletes its pasted token; the CLI stays signed in.

Every request to GitHub goes through `app/sources/github.py`, the one GitHub client, so a later GitHub feature (issues, pull requests) is a method there.

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
