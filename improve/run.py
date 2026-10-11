"""The agent's part of improving the app: the pick fixed by an agent run.

    uv run python -m improve.run follow [--repo ...] [--out ...]
    uv run python -m improve.run launch [--repo ...] [--out ...] [--logs ...] [--db ...]

All of it scripted around the one step an agent takes: the fix.

`launch` hands the ledger's next pick to an agent (app/services/agent_runs.py,
T3 Code first), when fewer than --max-open picks are still being fixed: a
worktree of the repo on a branch of its own (improve/<day>-<fingerprint>),
the brief (scan.py's) with where to work and the app project's AGENTS.md,
and the entry marked picked with its run.

`follow` looks at each picked entry, deterministically: its pull request is
found from its branch on GitHub (gh). Merged, the entry is done; closed
unmerged, Oscar turned it down: ignored. Open, its newest commit passes
master's gate (check.py, run on a checkout of it here), and the outcome is
commented on the pull request once for each commit. With no pull request,
the run is looked at: working or waiting on Oscar, it is left be; finished,
failed or gone, the entry opens again for another run, until MAX_ATTEMPTS
runs have made nothing (then ignored). A run that found master fixes it
already names the commit that did, in its worktree (OUTCOME, as the brief
says); that commit on master, the entry is done, and met again it opens
again, as any fix that did not hold. A worktree is removed once its entry is
settled and it has nothing uncommitted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.services import agent_runs
from app.services.agent_runs import Brief, Run, RunError, RunState
from improve import live_home, sources
from improve.ledger import Entry, Ledger
from improve.scan import CHECKOUT, render_brief

# Runs that made no pull request before the entry is given up on.
MAX_ATTEMPTS = 2
# Changes to these are the loop changing itself: the gate says so loudly.
SELF = ("improve/", "app/jobs/improve.py", "app/services/agent_runs.py", "app/sources/t3.py")
GATE_MARK = "<!-- improve-gate -->"
# Where the agent works, added to the brief (scan.py's) it is given.
WHERE = Path(__file__).with_name("where.md")
# What a run that found nothing to fix leaves in its worktree (never
# committed: .gitignore), its first line naming the commit that fixed it.
OUTCOME = "improve-outcome.md"
FIXED_BY = re.compile(r"^Already fixed by ([0-9a-f]{7,40})\b", re.IGNORECASE)


@dataclass
class PullRequest:
    url: str
    # OPEN, MERGED or CLOSED.
    state: str
    head: str


def _gh(args: list[str], cwd: Path, stdin: str | None = None) -> str:
    gh = shutil.which("gh") or "gh"
    out = subprocess.run(
        [gh, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # Never the caller's input: empty when there is nothing to give it.
        input=stdin or "",
        timeout=120,
        env={**os.environ, "GH_PROMPT_DISABLED": "1"},
    )
    if out.returncode:
        raise RunError(f"gh {' '.join(args[:2])}: {out.stderr.strip()[-300:]}")
    return out.stdout


def find_pull_request(repo: Path, branch: str) -> PullRequest | None:
    """The pull request from `branch`, the newest should there be several."""
    found = json.loads(
        _gh(
            [
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "all",
                "--limit",
                "1",
                "--json",
                "url,state,headRefOid",
            ],
            repo,
        )
    )
    if not found:
        return None
    return PullRequest(found[0]["url"], found[0]["state"], found[0]["headRefOid"])


def find_improving(repo: Path, fingerprint: str) -> tuple[str, str] | None:
    """An open pull request already saying it improves `fingerprint` (its
    body's "Improves:" line, as the brief asks): its URL and branch."""
    search = f'"Improves: {fingerprint}" in:body'
    found = json.loads(
        _gh(
            [
                "pr",
                "list",
                "--state",
                "open",
                "--search",
                search,
                "--limit",
                "1",
                "--json",
                "url,headRefName",
            ],
            repo,
        )
    )
    return (found[0]["url"], found[0]["headRefName"]) if found else None


def comment(repo: Path, url: str, body: str) -> None:
    _gh(["pr", "comment", url, "--body-file", "-"], repo, stdin=body)


def gate(repo: Path, checkout: Path, branch: str) -> tuple[bool, str]:
    """The branch's newest commit checked by this checkout's gate, in a
    checkout of its own (`checkout`); whether it passed, and the comment."""
    git = ["git", "-c", "advice.detachedHead=false"]
    run = lambda *args, cwd: subprocess.run(  # noqa: E731
        [*git, *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    run(
        "fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", cwd=repo
    )
    if not (checkout / ".git").exists():
        run("worktree", "prune", cwd=repo)
        run("worktree", "add", "--detach", "--force", str(checkout), f"origin/{branch}", cwd=repo)
    else:
        run("checkout", "--quiet", "--detach", "--force", f"origin/{branch}", cwd=checkout)
        run("clean", "-fdq", cwd=checkout)
    sha = run("rev-parse", "--short", "HEAD", cwd=checkout).stdout.strip()
    changed = run("diff", "--name-only", "origin/master...HEAD", cwd=checkout).stdout.split()
    out = sources.run_tool(
        [
            shutil.which("uv") or "uv",
            "run",
            "--quiet",
            "python",
            "-m",
            "improve.check",
            "--json",
            "--repo",
            str(checkout),
        ],
        CHECKOUT,
        timeout=3 * 3600,
    )
    try:
        outcome = json.loads(out.stdout)
    except ValueError:
        outcome = {
            "ok": False,
            "steps": [
                {
                    "step": "gate",
                    "ok": False,
                    "seconds": 0,
                    "output": sources.tail(out.stdout + out.stderr),
                }
            ],
        }
    lines = [
        GATE_MARK,
        f"**Improvement gate** on {sha}: {'passed' if outcome['ok'] else 'FAILED'}",
        "",
    ]
    for step in outcome["steps"]:
        lines.append(f"- {step['step']}: {'ok' if step['ok'] else 'failed'} ({step['seconds']}s)")
    touched = [f for f in changed if f.startswith(SELF)]
    if touched:
        lines += [
            "",
            "**It changes the improvement loop itself:** "
            + ", ".join(f"`{f}`" for f in touched)
            + ". Read those closely.",
        ]
    for step in outcome["steps"]:
        if step["output"]:
            lines += [
                "",
                f"<details><summary>{step['step']}</summary>",
                "",
                "```",
                step["output"],
                "```",
                "",
                "</details>",
            ]
    return outcome["ok"], "\n".join(lines)


def fixed_by(entry: Entry) -> str | None:
    """The commit its run says fixed it already (OUTCOME), if it says so."""
    try:
        text = (Path(entry.worktree) / OUTCOME).read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        return None
    match = FIXED_BY.match(text.strip())
    return match[1] if match else None


def commit_on_master(repo: Path, commit: str) -> bool:
    """Whether `commit` is on origin's master, as last fetched."""
    out = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "origin/master"],
        cwd=repo,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )
    return out.returncode == 0


def _settle(entry: Entry, repo: Path, status: str, today: date, ledger: Ledger, note: str) -> None:
    ledger.mark(entry.fingerprint, status, today, note=note)
    if entry.worktree:
        # One that cannot go now stays for Oscar to look at.
        with suppress(RunError):
            agent_runs.remove_worktree(repo, Path(entry.worktree))


def follow(
    ledger: Ledger,
    repo: Path,
    today: date,
    runner: agent_runs.Runner | None,
    gate_checkout: Path,
    *,
    find: Callable = find_pull_request,
    check: Callable = gate,
    post: Callable = comment,
    on_master: Callable = commit_on_master,
) -> list[str]:
    """Each picked entry looked at and moved on; what happened, a line each."""
    said = []
    picked = [e for e in ledger.entries.values() if e.status == "picked" and e.branch]
    # None: the runner could not be asked, so no run is taken to have ended.
    states: dict[str, RunState] | None = {} if runner else None
    runs = [Run(e.runner, e.run) for e in picked if e.run and runner and e.runner == runner.name]
    if runs:
        try:
            states = runner.states(runs)
        except RunError as exc:
            states = None
            said.append(f"runs not looked at: {exc}")
    for entry in picked:
        try:
            pr = find(repo, entry.branch)
        except RunError as exc:
            said.append(f"not looked at: {entry.title} ({exc})")
            continue
        if pr:
            entry.pr = pr.url
            if pr.state == "MERGED":
                _settle(entry, repo, "done", today, ledger, "its pull request was merged")
                said.append(f"done: {entry.title} ({pr.url})")
            elif pr.state == "CLOSED":
                _settle(
                    entry,
                    repo,
                    "ignored",
                    today,
                    ledger,
                    "its pull request was closed without merging",
                )
                said.append(f"ignored: {entry.title} ({pr.url} closed)")
            elif entry.gated != pr.head:
                try:
                    passed, body = check(repo, gate_checkout, entry.branch)
                    post(repo, pr.url, body)
                except (RunError, OSError, subprocess.SubprocessError) as exc:
                    # Tried again at the next follow.
                    said.append(f"not gated: {entry.title} ({exc})")
                    continue
                entry.gated = pr.head
                said.append(f"gated {'ok' if passed else 'FAILED'}: {entry.title} ({pr.url})")
            else:
                said.append(f"waiting on review: {entry.title} ({pr.url})")
            continue
        if states is None:
            continue
        state = states.get(entry.run, RunState.gone)
        if state in (RunState.working, RunState.waiting):
            said.append(f"{state}: {entry.title}")
            continue
        if (commit := fixed_by(entry)) and on_master(repo, commit):
            _settle(entry, repo, "done", today, ledger, f"already fixed by {commit} on master")
            said.append(f"already fixed: {entry.title} ({commit})")
            continue
        if entry.attempts >= MAX_ATTEMPTS:
            _settle(
                entry,
                repo,
                "ignored",
                today,
                ledger,
                f"{entry.attempts} agent runs made no pull request",
            )
            said.append(f"given up: {entry.title}")
        else:
            _settle(entry, repo, "open", today, ledger, f"its run {state} with no pull request")
            entry.branch = entry.worktree = entry.run = ""
            said.append(f"open again: {entry.title} (run {state}, no pull request)")
    return said


def agents_doc(db: Path, repo_slug: str | None, project: str, everyday: Path) -> str:
    """The app project's AGENTS.md, its file in the project's folder of the
    everyday files (the one at its top); empty without one."""
    try:
        with closing(sources.connect_ro(db)) as connection:
            project_id = sources.app_project(connection, repo_slug, project)
            if project_id is None:
                return ""
            row = connection.execute(
                "SELECT folder FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
    except (sources.SourceFailed, sqlite3.Error):
        return ""
    if not row or not row[0]:
        return ""
    try:
        return (everyday / "projects" / row[0] / "AGENTS.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def branch_for(entry: Entry, today: date) -> str:
    return f"improve/{today}-{re.sub(r'[^a-z0-9]+', '-', entry.fingerprint.lower())}"


def launch(
    ledger: Ledger,
    repo: Path,
    today: date,
    runner: agent_runs.Runner,
    worktrees: Path,
    logs: Path,
    agents: str = "",
    max_open: int = 1,
    prepare: Callable = agent_runs.prepare_worktree,
    existing: Callable = find_improving,
) -> Entry | None:
    """The next pick handed to an agent, when there is room; it, or None.
    One a pull request already improves (the ledger lost, or kept elsewhere)
    is taken up as picked with that pull request, and nothing is launched."""
    in_flight = [e for e in ledger.entries.values() if e.status == "picked"]
    candidates = ledger.candidates(today)
    if len(in_flight) >= max_open or not candidates:
        return None
    entry = candidates[0]
    if found := existing(repo, entry.fingerprint):
        url, branch = found
        ledger.mark(entry.fingerprint, "picked", today, pr=url, note="its pull request was open")
        entry.branch, entry.runner, entry.run, entry.worktree = branch, "", "", ""
        return entry
    branch = branch_for(entry, today)
    worktree = worktrees / branch.replace("/", "-")
    prepare(repo, worktree, branch)
    where = WHERE.read_text(encoding="utf-8").format(worktree=worktree, branch=branch)
    text = render_brief(entry, today, logs) + where
    if agents:
        text += f"\n## The project's AGENTS.md\n\n{agents}\n"
    run = runner.launch(Brief(f"Improve: {entry.title}", text, repo, worktree, branch))
    ledger.mark(entry.fingerprint, "picked", today, note=f"run {run.id}")
    entry.runner, entry.run, entry.branch, entry.worktree = (
        run.runner,
        run.id,
        branch,
        str(worktree),
    )
    entry.attempts += 1
    entry.gated = ""
    return entry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m improve.run", description=__doc__.split("\n")[0]
    )
    parser.add_argument("command", choices=("follow", "launch"))
    home = live_home()
    parser.add_argument(
        "--repo",
        type=Path,
        default=CHECKOUT,
        help="the repo runs work on: their worktrees are of it",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=home / "data" / "improve",
        help="the scan's folder, holding ledger.json",
    )
    parser.add_argument("--logs", type=Path, default=home / "data" / "logs")
    parser.add_argument("--db", type=Path, default=home / "data" / "personal-calendar.db")
    parser.add_argument("--project", default="")
    parser.add_argument(
        "--everyday", type=Path, default=Path("C:/everyday-files"),
        help="the everyday files' folder, where the project's AGENTS.md is",
    )
    parser.add_argument("--runner", default="t3", help="the agent system: t3, or none")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument(
        "--max-open", type=int, default=1, help="the most picks being fixed at once"
    )
    parser.add_argument(
        "--worktrees",
        type=Path,
        help="where runs' worktrees go (default: T3 Code's, ~/.t3/worktrees/<repo>)",
    )
    args = parser.parse_args(argv)

    runner = None
    if args.runner != "none":
        runner = agent_runs.RUNNERS[args.runner](model=args.model)
    ledger = Ledger.load(args.out / "ledger.json")
    today = date.today()
    if args.command == "follow":
        for line in follow(ledger, args.repo, today, runner, args.out / "gate"):
            print(line)
    elif runner:
        worktrees = args.worktrees or Path.home() / ".t3" / "worktrees" / args.repo.name
        agents = agents_doc(args.db, sources.repo_slug(args.repo), args.project, args.everyday)
        entry = launch(
            ledger, args.repo, today, runner, worktrees, args.logs, agents, args.max_open
        )
        print(f"launched: {entry.title} ({entry.run})" if entry else "nothing launched")
    ledger.save()


if __name__ == "__main__":
    main()
