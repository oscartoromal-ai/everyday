"""The daily scan: findings gathered from every source, entered in the
ledger, the most pressing picked, and the day's report written.

    uv run python -m improve.scan [--only tests,lint] [--home ...]

It reads the live app's data (its home, the installed app's by default) and
runs the checkout's own tests, lint and dependencies: run it from a checkout
of origin's master, as the app does (app/jobs/improve.py). It writes into the
improve/ folder beside the app's database (data/improve/ in its home):

- ledger.json, the findings across days (ledger.py);
- reports/<day>.md, what it found and what each source said (and .json);
- brief.md, the pick as a brief for an agent to fix it; none when nothing is
  left to pick.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from improve import live_home, sources
from improve.findings import Finding
from improve.ledger import Entry, Ledger

CHECKOUT = Path(__file__).resolve().parent.parent
# The brief's template, filled in for the pick.
BRIEF = Path(__file__).with_name("brief.md")
SOURCES = ("log", "usage", "tests", "lint", "vulnerabilities", "dependencies", "tasks")
# How far back the use is read, and the log on a first scan.
USAGE_DAYS = 7
# How many of the most used routes the report lists.
TOP_ROUTES = 20

# What fixing each kind of finding asks, for its brief.
ASKS = {
    "failing-test": "A test fails on master. Make it pass by fixing what it tests, or the test "
    "itself when that is what is wrong; never by skipping it.",
    "error": "The live app logged this error. Find what Oscar was doing when it happened (the "
    "log around it says which pages were asked for), then fix its cause.",
    "failing-route": "This route answered with a server error in the live app. Its traceback "
    "is in the live app's log, around the times it failed.",
    "vulnerable-dependency": "Update the package to a release with the fix "
    "(`uv lock --upgrade-package <name>`), and check the app still works.",
    "flaky-test": "This test fails only sometimes. Find why (timing, order, state shared "
    "between tests) and make it pass every time; never by retrying or skipping it.",
    "lint": "Fix what ruff finds in the code, not by ignoring the rule.",
    "task": "Oscar gave Claude this task on the app's project. Do it as its notes say.",
    "slow-route": "This page or action is slow to start answering. Measure where the time "
    "goes, then make it faster without changing what it does.",
    "slow-tests": "The tests are slow, and every change waits on them. Find where their time "
    "goes (the slowest are below) and make them faster without testing less.",
    "outdated-dependency": "Bring these packages up to their latest releases "
    "(`uv lock --upgrade-package <name>` each), reading their changelogs for anything that "
    "changes how the app behaves.",
}


@dataclass
class SourceResult:
    found: int = 0
    seconds: float = 0
    problem: str | None = None


@dataclass
class Report:
    day: date
    commit: str
    started: datetime
    finished: datetime | None = None
    sources: dict[str, SourceResult] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    new: set[str] = field(default_factory=set)
    pick: Entry | None = None
    routes: list[sources.RouteStats] = field(default_factory=list)


def _gather(report: Report, name: str, source: Callable[[], list[Finding]]) -> None:
    started = time.monotonic()
    result = report.sources[name] = SourceResult()
    try:
        found = source()
    except sources.SourceFailed as exc:
        result.problem = str(exc)
    except Exception as exc:  # noqa: BLE001 - one source failing leaves the others standing
        result.problem = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
    else:
        result.found = len(found)
        report.findings += found
    result.seconds = time.monotonic() - started


def _commit(checkout: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=checkout,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip() or "unknown"


def scan(
    *,
    checkout: Path,
    db: Path,
    logs: Path,
    out: Path,
    project: str = "",
    only: tuple[str, ...] = SOURCES,
    now: datetime | None = None,
) -> Report:
    now = now or datetime.now()
    today = now.date()
    ledger = Ledger.load(out / "ledger.json")
    report = Report(today, _commit(checkout), now)
    log_since = ledger.last_scan or now - timedelta(days=USAGE_DAYS)
    usage_since = today - timedelta(days=USAGE_DAYS)

    def usage() -> list[Finding]:
        report.routes = sources.route_stats(db, usage_since)
        return sources.route_use(report.routes, usage_since)

    gatherers: dict[str, Callable[[], list[Finding]]] = {
        "log": lambda: sources.log_errors(logs, log_since),
        "usage": usage,
        "tests": lambda: sources.tests(checkout),
        "lint": lambda: sources.lint(checkout),
        "vulnerabilities": lambda: sources.vulnerable_dependencies(checkout),
        "dependencies": lambda: sources.outdated_dependencies(checkout),
        "tasks": lambda: sources.tasks(db, checkout, project),
    }
    for name in SOURCES:
        if name in only:
            _gather(report, name, gatherers[name])

    report.new = {e.fingerprint for e in ledger.meet(report.findings, today)}
    # The log is read from where this scan read it to, should a source have failed.
    if "log" in only and not report.sources["log"].problem:
        ledger.last_scan = now
    candidates = ledger.candidates(today)
    report.pick = candidates[0] if candidates else None
    report.finished = datetime.now()

    reports = out / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{today}.md").write_text(render_report(report, ledger), encoding="utf-8")
    (reports / f"{today}.json").write_text(
        json.dumps(report_json(report, ledger), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    brief = out / "brief.md"
    if report.pick:
        brief.write_text(render_brief(report.pick, today, logs), encoding="utf-8")
    else:
        brief.unlink(missing_ok=True)
    ledger.save()
    return report


def render_brief(entry: Entry, today: date, logs: Path) -> str:
    seen = (
        f"first met on {entry.first_seen}, {entry.occurrences} time(s) over {entry.scans} scan(s)"
    )
    if entry.reopened:
        seen += f"; it came back {entry.reopened} time(s) after being fixed"
    live_log = ""
    if entry.kind in ("error", "failing-route"):
        log = logs / "personal-calendar.log"
        live_log = f"\nThe live app's log: `{log}` (read it, never write to it).\n"
    return BRIEF.read_text(encoding="utf-8").format(
        title=entry.title,
        today=today,
        kind=entry.kind,
        fingerprint=entry.fingerprint,
        seen=seen,
        evidence=entry.evidence,
        live_log=live_log,
        ask=ASKS[entry.kind],
    )


def render_report(report: Report, ledger: Ledger) -> str:
    lines = [f"# Improvement scan, {report.day}", ""]
    took = (report.finished - report.started).total_seconds() / 60 if report.finished else 0
    lines += [f"Ran from {report.commit}, at {report.started:%H:%M}, for {took:.0f} minute(s).", ""]

    lines += ["## The pick", ""]
    if report.pick:
        p = report.pick
        lines += [f"**{p.title}** ({p.kind}, `{p.fingerprint}`), its brief in brief.md.", ""]
    else:
        lines += ["Nothing to pick.", ""]

    lines += ["## Found", ""]
    if report.findings:
        lines += ["| Kind | Finding | Times | Status | Since |", "| --- | --- | --- | --- | --- |"]
        for f in sorted(report.findings, key=lambda f: (f.rank, -f.occurrences)):
            entry = ledger.entries[f.fingerprint]
            status = "new" if f.fingerprint in report.new else entry.status
            title = f.title.replace("|", "\\|")
            lines.append(
                f"| {f.kind} | {title} | {f.occurrences} | {status} | {entry.first_seen} |"
            )
    else:
        lines.append("Nothing.")
    lines.append("")

    lines += ["## Sources", ""]
    for name, result in report.sources.items():
        said = (
            f"could not run: {result.problem.splitlines()[0]}"
            if result.problem
            else (f"{result.found} finding(s)")
        )
        lines.append(f"- {name}: {said} ({result.seconds:.0f}s)")
    lines.append("")

    if report.routes:
        lines += [
            f"## Use, the last {USAGE_DAYS} days",
            "",
            "| Route | Requests | Failed | Average ms | Slowest ms |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in report.routes[:TOP_ROUTES]:
            lines.append(
                f"| `{r.route}` | {r.requests} | {r.failures} | {r.average_ms} | {r.slowest_ms} |"
            )
        lines.append("")
    return "\n".join(lines)


def report_json(report: Report, ledger: Ledger) -> dict:
    return {
        "day": report.day.isoformat(),
        "commit": report.commit,
        "started": report.started.isoformat(timespec="seconds"),
        "finished": report.finished.isoformat(timespec="seconds") if report.finished else None,
        "sources": {name: vars(result) for name, result in report.sources.items()},
        "findings": [
            {
                "fingerprint": f.fingerprint,
                "kind": f.kind,
                "title": f.title,
                "occurrences": f.occurrences,
                "new": f.fingerprint in report.new,
                "status": ledger.entries[f.fingerprint].status,
            }
            for f in report.findings
        ],
        "pick": report.pick.fingerprint if report.pick else None,
        "routes": [vars(r) for r in report.routes],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m improve.scan", description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=live_home(),
        help="the app's home, whose data is read (the installed app's)",
    )
    parser.add_argument("--db", type=Path, help="its database (default: data/ in the home)")
    parser.add_argument(
        "--logs", type=Path, help="its logs' folder (default: data/logs/ in the home)"
    )
    parser.add_argument(
        "--out", type=Path, help="where to write (default: data/improve/ in the home)"
    )
    parser.add_argument(
        "--project", default="", help="the project the app's tasks are on, when none lists the repo"
    )
    parser.add_argument(
        "--only", default=",".join(SOURCES), help=f"the sources to read, of {', '.join(SOURCES)}"
    )
    args = parser.parse_args(argv)
    only = tuple(s.strip() for s in args.only.split(",") if s.strip())
    if unknown := set(only) - set(SOURCES):
        parser.error(f"no source {', '.join(sorted(unknown))}")
    out = args.out or args.home / "data" / "improve"
    report = scan(
        checkout=CHECKOUT,
        db=args.db or args.home / "data" / "personal-calendar.db",
        logs=args.logs or args.home / "data" / "logs",
        out=out,
        project=args.project,
        only=only,
    )
    print(out / "reports" / f"{report.day}.md")
    if report.pick:
        print(f"Picked: {report.pick.title} ({report.pick.fingerprint})")


if __name__ == "__main__":
    main()
