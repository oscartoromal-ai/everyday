"""Where findings come from.

Each source reads one thing and returns its findings; the scan runs each on
its own, so one that cannot run (a tool missing, the network down) leaves the
others' findings standing. The live app's data is only ever read: its
database opened read-only, its log as text. The tests, lint and dependencies
are the checkout's the scan runs from (origin's master).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from improve.findings import Finding

# A route is slow when its responses take this long to start, on average over
# at least this many requests.
SLOW_ROUTE_MS = 500
SLOW_ROUTE_REQUESTS = 5
# The tests are slow when the whole suite takes this long.
SLOW_SUITE_SECONDS = 600
# How many lines of a traceback or a test's output a finding keeps.
EVIDENCE_LINES = 60


class SourceFailed(Exception):
    """A source could not be read; its message says why."""


def run_tool(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    """A tool run in `cwd`, its output read as text. Nothing of the app's own
    configuration (PC_*) reaches it: the tests must never find the live app's
    home."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PC_")}
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            # Nothing it runs ever waits on input: there is no one to give it.
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceFailed(f"{' '.join(cmd[:3])}: {exc}") from exc


def _uv() -> str:
    return shutil.which("uv") or "uv"


def tail(text: str, lines: int = EVIDENCE_LINES) -> str:
    kept = text.rstrip().splitlines()
    if len(kept) > lines:
        kept = ["...", *kept[-lines:]]
    return "\n".join(kept)


def _block(text: str) -> str:
    return f"```\n{text}\n```"


def connect_ro(db: Path) -> sqlite3.Connection:
    """The live app's database, opened so nothing can be written to it."""
    if not db.exists():
        raise SourceFailed(f"no database at {db}")
    return sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)


# -- The live app's log ------------------------------------------------------

# A record's first line, as app/serve.py's logging writes it.
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ ([A-Z]+) ([\w.]+): (.*)$")
FRAME = re.compile(r'^\s+File "(?P<file>[^"]+)", line \d+, in (?P<func>.+)$')
# A traceback's lines that are not its exception's.
TRACEBACK_PROSE = ("Traceback ", "During handling of", "The above exception")


@dataclass
class LogRecord:
    at: datetime
    level: str
    logger: str
    lines: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return LOG_LINE.match(self.lines[0]).group(4)

    def exception(self) -> str | None:
        """Its traceback's last exception line ("KeyError: 'x'"), if it has one."""
        found = None
        for line in self.lines[1:]:
            if line and not line[0].isspace() and not line.startswith(TRACEBACK_PROSE):
                found = line
        return found

    def frames(self) -> list[tuple[str, str]]:
        """Its traceback's frames, outermost first, as (file, function); the
        file with forward slashes."""
        frames = []
        for line in self.lines[1:]:
            if match := FRAME.match(line):
                frames.append((match["file"].replace("\\", "/"), match["func"].strip()))
        return frames


def read_log(path: Path) -> list[LogRecord]:
    records: list[LogRecord] = []
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            line = line.rstrip("\n").lstrip("\ufeff")
            if match := LOG_LINE.match(line):
                at = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S")
                records.append(LogRecord(at, match[2], match[3], [line]))
            elif records:
                records[-1].lines.append(line)
    return records


def log_files(log_dir: Path) -> list[Path]:
    """The app's log and its rotated copies, oldest first."""
    rotated = sorted(log_dir.glob("personal-calendar.log.*"), key=lambda p: -int(p.suffix[1:] or 0))
    current = log_dir / "personal-calendar.log"
    return [*rotated, *([current] if current.exists() else [])]


def _app_frame(frames: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The innermost frame in the app's own code, its file from app/ on (the
    same in the installed app as run from the repo)."""
    for file, func in reversed(frames):
        if "site-packages/" in file:
            continue
        if file.startswith("app/"):
            return file, func
        if (at := file.rfind("/app/")) >= 0:
            return file[at + 1 :], func
    return None


def log_errors(log_dir: Path, since: datetime) -> list[Finding]:
    """The errors the live app logged since `since`, one finding for each
    place they came from, however often."""
    groups: dict[str, list[LogRecord]] = defaultdict(list)
    titles: dict[str, str] = {}
    for path in log_files(log_dir):
        for record in read_log(path):
            if record.at < since or record.level not in ("ERROR", "CRITICAL"):
                continue
            exception = record.exception()
            if exception:
                kind = re.match(r"[\w.]+", exception)
                exc_type = kind[0] if kind else exception[:60]
                frames = record.frames()
                where = _app_frame(frames) or (frames[-1] if frames else ("?", "?"))
                key = f"{record.logger}|{exc_type}|{where[0]}:{where[1]}"
                titles[key] = f"{exc_type.rsplit('.', 1)[-1]} in {where[0]}:{where[1]}"
            else:
                # The same message but for its numbers is the same error.
                key = f"{record.logger}|{re.sub(r'[0-9]+', 'N', record.message)}"
                titles[key] = f"{record.logger}: {record.message[:100]}"
            groups[key].append(record)
    findings = []
    for key, records in groups.items():
        last = records[-1]
        evidence = (
            f"Logged {len(records)} time(s) by `{last.logger}` since {since:%Y-%m-%d %H:%M}, "
            f"first at {records[0].at:%Y-%m-%d %H:%M}, last at {last.at:%Y-%m-%d %H:%M}.\n\n"
            "The last:\n\n" + _block(tail("\n".join(last.lines)))
        )
        findings.append(Finding("error", key, titles[key], evidence, len(records)))
    return findings


# -- The live app's use (app/usage.py) ---------------------------------------


@dataclass
class RouteStats:
    route: str
    requests: int
    failures: int
    total_ms: int
    slowest_ms: int

    @property
    def average_ms(self) -> int:
        return round(self.total_ms / self.requests) if self.requests else 0


def route_stats(db: Path, since: date) -> list[RouteStats]:
    """Each route's use since `since`, the most used first."""
    with closing(connect_ro(db)) as connection:
        try:
            rows = connection.execute(
                "SELECT route, sum(requests), sum(failures), sum(total_ms), max(slowest_ms) "
                "FROM route_use WHERE day >= ? GROUP BY route ORDER BY sum(requests) DESC",
                (since.isoformat(),),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            # A database from before the app counted its use.
            if "no such table" in str(exc):
                return []
            raise
    return [RouteStats(*row) for row in rows]


def route_use(stats: list[RouteStats], since: date) -> list[Finding]:
    """The routes failing, and the ones slow, in the live app's use."""
    findings = []
    for s in stats:
        counts = (
            f"Since {since}: {s.requests} request(s), {s.failures} failed; responses started "
            f"in {s.average_ms} ms on average, {s.slowest_ms} ms at the slowest."
        )
        if s.failures:
            title = f"{s.route} failed {s.failures} time(s)"
            findings.append(Finding("failing-route", s.route, title, counts, s.failures))
        if s.requests >= SLOW_ROUTE_REQUESTS and s.average_ms >= SLOW_ROUTE_MS:
            title = f"{s.route} takes {s.average_ms} ms to start answering"
            findings.append(Finding("slow-route", s.route, title, counts))
    return findings


# -- The checkout's tests ----------------------------------------------------

SUMMARY = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$")
DURATION = re.compile(r"^\s*([\d.]+)s (call|setup|teardown)\s+(\S+)\s*$")
TOTAL = re.compile(r" in ([\d.]+)s\b")
SECTION = re.compile(r"^_{3,} (.+?) _{3,}$")


@dataclass
class TestRun:
    exit_code: int
    output: str
    failed: list[str]
    durations: list[tuple[float, str]]
    seconds: float | None

    def section(self, nodeid: str) -> str | None:
        """What pytest wrote of a test's failure."""
        name = ".".join(nodeid.split("::")[1:]) or nodeid
        sections: dict[str, list[str]] = {}
        current = None
        for line in self.output.splitlines():
            if match := SECTION.match(line):
                current = sections.setdefault(match[1].removeprefix("ERROR at setup of "), [])
            elif line.startswith("=") and current is not None:
                current = None
            elif current is not None:
                current.append(line)
        lines = sections.get(name)
        return "\n".join(lines) if lines else None


def parse_pytest(exit_code: int, output: str) -> TestRun:
    failed, durations, seconds = [], [], None
    for line in output.splitlines():
        if match := SUMMARY.match(line):
            failed.append(match[2])
        elif match := DURATION.match(line):
            durations.append((float(match[1]), f"{match[2]} {match[3]}"))
        elif (match := TOTAL.search(line)) and ("passed" in line or "failed" in line):
            seconds = float(match[1])
    return TestRun(exit_code, output, list(dict.fromkeys(failed)), durations, seconds)


def run_pytest(checkout: Path, *args: str) -> TestRun:
    out = run_tool(
        [_uv(), "run", "pytest", "-p", "no:cacheprovider", "--tb=short", "-rfE", *args],
        checkout,
        timeout=3 * 3600,
    )
    return parse_pytest(out.returncode, out.stdout + out.stderr)


def tests(checkout: Path) -> list[Finding]:
    """The tests failing on master, those that fail only sometimes (passing
    when run again), and the suite when it is slow."""
    run = run_pytest(checkout, "--durations=25")
    # 0: all passed; 1: some failed. Anything else is the suite not running.
    if run.exit_code not in (0, 1) or (run.exit_code == 1 and not run.failed):
        return [
            Finding(
                "failing-test",
                "suite",
                "The test suite does not run",
                f"`pytest` exited {run.exit_code}:\n\n" + _block(tail(run.output)),
            )
        ]
    findings = []
    if run.failed:
        again = run_pytest(checkout, *run.failed)
        for nodeid in run.failed:
            flaky = nodeid not in again.failed
            output = run.section(nodeid) or again.section(nodeid) or ""
            if flaky:
                title = f"{nodeid} fails only sometimes"
                evidence = "It failed in the full run, then passed run again. It failed with:"
            else:
                title = f"{nodeid} fails"
                evidence = "It failed in the full run, and again on its own:"
            evidence += "\n\n" + _block(tail(output or "(pytest wrote nothing of it)"))
            findings.append(
                Finding("flaky-test" if flaky else "failing-test", nodeid, title, evidence)
            )
    if run.seconds and run.seconds >= SLOW_SUITE_SECONDS:
        slowest = "\n".join(f"- {s:.1f}s {what}" for s, what in run.durations)
        findings.append(
            Finding(
                "slow-tests",
                "suite",
                f"The tests take {run.seconds / 60:.0f} minutes",
                f"The whole suite took {run.seconds:.0f}s. The slowest:\n\n{slowest}",
            )
        )
    return findings


# -- The checkout's lint -----------------------------------------------------


def lint(checkout: Path) -> list[Finding]:
    """What ruff finds, a finding for each of its rules broken."""
    out = run_tool(
        [_uv(), "run", "ruff", "check", "--output-format", "json", "--exit-zero", "."],
        checkout,
        timeout=600,
    )
    try:
        problems = json.loads(out.stdout or "[]")
    except ValueError as exc:
        raise SourceFailed(f"ruff wrote no JSON: {tail(out.stdout + out.stderr, 5)}") from exc
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for problem in problems:
        by_rule[problem["code"] or "syntax"].append(problem)
    findings = []
    for rule, found in sorted(by_rule.items()):
        places = "\n".join(
            f"- {Path(p['filename']).resolve().relative_to(checkout.resolve()).as_posix()}"
            f":{p['location']['row']}: {p['message']}"
            for p in found[:30]
        )
        title = f"ruff {rule}: {found[0]['message'][:80]} ({len(found)} place(s))"
        findings.append(Finding("lint", rule, title, places, len(found)))
    return findings


# -- The checkout's dependencies ---------------------------------------------


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_dependencies(checkout: Path) -> set[str]:
    """The packages pyproject.toml names, the app's and its dev tools'."""
    project = tomllib.loads((checkout / "pyproject.toml").read_text(encoding="utf-8"))
    specs = list(project["project"].get("dependencies", []))
    for group in project.get("dependency-groups", {}).values():
        specs += [spec for spec in group if isinstance(spec, str)]
    return {_normalized(re.match(r"[A-Za-z0-9_.-]+", spec)[0]) for spec in specs}


def site_packages(checkout: Path) -> Path:
    venv = checkout / ".venv"
    found = [venv / "Lib" / "site-packages"] if sys.platform == "win32" else []
    found += list(venv.glob("lib/python*/site-packages"))
    for path in found:
        if path.exists():
            return path
    raise SourceFailed(f"no virtual environment in {checkout}")


def vulnerable_dependencies(checkout: Path) -> list[Finding]:
    """The installed packages with known vulnerabilities (pip-audit, which
    asks the Python Packaging Advisory Database)."""
    out = run_tool(
        [
            _uv(),
            "tool",
            "run",
            "pip-audit",
            "--path",
            str(site_packages(checkout)),
            "--format",
            "json",
            "--progress-spinner",
            "off",
        ],
        checkout,
        timeout=900,
    )
    try:
        audit = json.loads(out.stdout)
    except ValueError as exc:
        raise SourceFailed(f"pip-audit wrote no JSON: {tail(out.stderr, 5)}") from exc
    findings = []
    for dep in audit.get("dependencies", []):
        if not dep.get("vulns"):
            continue
        details = "\n".join(
            f"- {v['id']}: fixed in {', '.join(v.get('fix_versions') or ['no release yet'])}. "
            f"{(v.get('description') or '').strip()[:300]}"
            for v in dep["vulns"]
        )
        count = len(dep["vulns"])
        findings.append(
            Finding(
                "vulnerable-dependency",
                # The version updated to, should it be vulnerable too, is another finding.
                f"{dep['name']}|{dep['version']}",
                f"{dep['name']} {dep['version']} has {count} known vulnerabilit"
                f"{'y' if count == 1 else 'ies'}",
                details,
                count,
            )
        )
    return findings


def outdated_dependencies(checkout: Path) -> list[Finding]:
    """The packages pyproject.toml names with newer releases, as one finding:
    they are brought up to date together."""
    out = run_tool([_uv(), "pip", "list", "--outdated", "--format", "json"], checkout, timeout=600)
    try:
        listed = json.loads(out.stdout or "[]")
    except ValueError as exc:
        raise SourceFailed(f"uv pip list wrote no JSON: {tail(out.stderr, 5)}") from exc
    direct = direct_dependencies(checkout)
    outdated = [p for p in listed if _normalized(p["name"]) in direct]
    if not outdated:
        return []
    lines = "\n".join(f"- {p['name']} {p['version']} to {p['latest_version']}" for p in outdated)
    return [
        Finding(
            "outdated-dependency",
            "direct",
            f"{len(outdated)} dependencies have newer releases",
            lines,
            len(outdated),
        )
    ]


# -- The tasks given to Claude on the app's project ---------------------------


def repo_slug(checkout: Path) -> str | None:
    """The repo's owner/name on its origin ("oscartoromal-ai/everyday-app")."""
    out = run_tool(["git", "remote", "get-url", "origin"], checkout, timeout=30)
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", out.stdout.strip())
    return match[1] if match else None


def app_project(connection: sqlite3.Connection, slug: str | None, name: str) -> int | None:
    """The project the app's work is planned on: the one listing its repo,
    else the one named `name`."""
    if slug:
        for project_id, location in connection.execute(
            "SELECT project_id, location FROM project_repos"
        ):
            if slug.lower() in location.lower():
                return project_id
    if name:
        row = connection.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
        if row:
            return row[0]
    return None


def tasks(db: Path, checkout: Path, project_name: str) -> list[Finding]:
    """The tasks still to do on the app's project that Oscar gave Claude
    (owner claude): his own are his."""
    with closing(connect_ro(db)) as connection:
        project_id = app_project(connection, repo_slug(checkout), project_name)
        if project_id is None:
            raise SourceFailed("no project lists the repo, nor is one named as configured")
        rows = connection.execute(
            "SELECT id, title, notes, priority, due FROM tasks "
            "WHERE project_id = ? AND owner = 'claude' AND status = 'todo' "
            # The most pressing first: the order the pick takes them in.
            "ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 WHEN 'low' THEN 4 ELSE 3 END, due IS NULL, due, id",
            (project_id,),
        ).fetchall()
    findings = []
    for task_id, title, notes, priority, due in rows:
        facts = ", ".join(
            fact
            for fact in (f"priority {priority}" if priority else "", f"due {due}" if due else "")
            if fact
        )
        evidence = f"Task {task_id} on the app's project{f' ({facts})' if facts else ''}."
        if notes.strip():
            evidence += "\n\n" + notes.strip()
        findings.append(Finding("task", str(task_id), title, evidence))
    return findings
