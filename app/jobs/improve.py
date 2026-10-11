"""The daily scan for what to improve in the app (improve/ in the repo).

The app that runs all day starts it, once a day: after [improve].after, or as
soon as it is next up and awake (a machine asleep or off at that hour misses
no day). It runs origin's master's scan, never the repo's working copy: a
checkout of its own in the improve/ folder beside the app's database
(improve/checkout, a worktree of the repo, its environment kept between
runs), brought to origin's master each time. The scan reads the app's
database and log, and writes its report, ledger and brief into improve/
(improve/scan.py). It runs at low priority with no window, what it prints
going to improve/scan.log.

Around the scan, the picks are fixed by agents (improve/run.py): first the
picks being fixed are followed (a pull request gated, merged or closed),
then after the scan the next pick is handed to an agent, when [improve]
runner names one and fewer than max_open are being fixed. Between days the
follow runs on its own every hour, so a pull request opened is gated soon.

The installed app finds its repo where [improve] repo says, else in
build-info.json (app/desktop/update.py) when it was built on this machine;
run from the repo, it is the repo.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from datetime import date, datetime, time
from pathlib import Path

from app.config import FROZEN, HOME, REPO_ROOT, get_settings

log = logging.getLogger(__name__)

REMOTE = "origin"
BRANCH = "master"
# Windows' process creation flags: no console window, below normal priority
# (which the scan's own processes, its tests, inherit).
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
GIT_TIMEOUT = 300
SCAN_TIMEOUT = 4 * 3600
# The day's run and the follows between, one at a time.
_lock = threading.Lock()


def folder() -> Path:
    """Beside the database, as its logs are (app/serve.py)."""
    return get_settings().db_path.parent / "improve"


def repo() -> Path | None:
    """The app's repo on this machine: as configured, else the one it was
    built from; None when it is not on this machine."""
    path = REPO_ROOT
    if configured := get_settings().improve.repo:
        path = Path(configured)
    elif FROZEN:
        from app.desktop.update import build_info

        info = build_info()
        path = Path(info["repo"]) if info and info.get("repo") else None
    return path if path and (path / ".git").exists() else None


def last_run(marker: Path) -> date | None:
    try:
        return date.fromisoformat(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def due(now: datetime, last: date | None, after: str) -> bool:
    """Whether the day's scan is to start: not yet run today, and past its time."""
    hour, minute = after.split(":")
    return last != now.date() and now.time() >= time(int(hour), int(minute))


def _run(cmd: list[str], timeout: float, **kwargs) -> None:  # noqa: ANN003
    flags = CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    env = {
        # Never a prompt for credentials: there is no one to answer it. Nor
        # the app's own configuration: the scan is told where the data is.
        **{k: v for k, v in os.environ.items() if not k.startswith("PC_")},
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
    }
    subprocess.run(
        cmd,
        check=True,
        timeout=timeout,
        env=env,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        **kwargs,
    )


def checkout_master(repo: Path, checkout: Path, git: str, output) -> None:  # noqa: ANN001
    """`checkout` brought to origin's master, as fetched now; made the first time."""
    _run(
        [git, "-C", str(repo), "fetch", "--quiet", REMOTE, BRANCH],
        GIT_TIMEOUT,
        stdout=output,
        stderr=subprocess.STDOUT,
    )
    target = f"{REMOTE}/{BRANCH}"
    if (checkout / ".git").exists():
        # Its untracked files go, its ignored ones (the environment) stay.
        for cmd in (["checkout", "--quiet", "--detach", "--force", target], ["clean", "-fdq"]):
            _run(
                [git, "-C", str(checkout), *cmd],
                GIT_TIMEOUT,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
    else:
        _run(
            [git, "-C", str(repo), "worktree", "prune"],
            GIT_TIMEOUT,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        _run(
            [git, "-C", str(repo), "worktree", "add", "--detach", "--force", str(checkout), target],
            GIT_TIMEOUT,
            stdout=output,
            stderr=subprocess.STDOUT,
        )


def _steps(settings, checkout: Path) -> dict[str, list[str]]:  # noqa: ANN001
    """The scan's commands, run in the checkout: following the picks being
    fixed, the scan, and handing the next pick to an agent."""
    from app.serve import log_path

    data = [
        "--db",
        str(settings.db_path),
        "--logs",
        str(log_path().parent),
        "--out",
        str(folder()),
        "--project",
        settings.improve.project,
    ]
    runs = [
        "--everyday",
        str(settings.everyday_dir),
        "--repo",
        str(repo()),
        "--runner",
        settings.improve.runner or "none",
        "--model",
        settings.improve.model,
        "--max-open",
        str(settings.improve.max_open),
    ]
    python = [shutil.which("uv") or "uv", "run", "--quiet", "python", "-m"]
    return {
        "follow": [*python, "improve.run", "follow", *data, *runs],
        "scan": [*python, "improve.scan", "--home", str(HOME), *data],
        "launch": [*python, "improve.run", "launch", *data, *runs],
    }


def run(now: datetime | None = None) -> bool:
    """The day's scan run, when it is due; whether it ran."""
    settings = get_settings()
    marker = folder() / "last-run.txt"
    now = now or datetime.now()
    if not settings.improve.enabled or not due(now, last_run(marker), settings.improve.after):
        return False
    source, git, uv = repo(), shutil.which("git"), shutil.which("uv")
    if not source or not git or not uv:
        log.info("Improvement scan skipped: no repo, git or uv on this machine")
        return False

    with _lock:
        folder().mkdir(parents=True, exist_ok=True)
        # Once a day, failed or not: a scan that fails is not tried again all day.
        marker.write_text(now.date().isoformat(), encoding="utf-8")
        checkout = folder() / "checkout"
        log.info("Improvement scan starting, from %s's %s/%s", source, REMOTE, BRANCH)
        steps = _steps(settings, checkout)
        with (folder() / "scan.log").open("w", encoding="utf-8") as output:
            try:
                checkout_master(source, checkout, git, output)
                for name in ("follow", "scan", "launch"):
                    output.write(f"\n== {name}\n")
                    output.flush()
                    _run(
                        steps[name],
                        SCAN_TIMEOUT,
                        cwd=checkout,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                    )
            except (OSError, subprocess.SubprocessError):
                log.warning("Improvement scan failed; see %s", folder() / "scan.log", exc_info=True)
                return True
    log.info("Improvement scan done: %s", folder() / "reports" / f"{now.date()}.md")
    return True


def follow() -> bool:
    """The picks being fixed followed between days: a pull request opened
    is gated, one merged or closed settles its pick. Whether it ran: not
    before the first day's scan has made the checkout, nor while it runs."""
    settings = get_settings()
    checkout = folder() / "checkout"
    if not settings.improve.enabled or not (checkout / ".git").exists() or not repo():
        return False
    if not _lock.acquire(blocking=False):
        return False
    try:
        with (folder() / "follow.log").open("w", encoding="utf-8") as output:
            _run(
                _steps(settings, checkout)["follow"],
                SCAN_TIMEOUT,
                cwd=checkout,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
    except (OSError, subprocess.SubprocessError):
        log.warning(
            "Following the improvements failed; see %s", folder() / "follow.log", exc_info=True
        )
    finally:
        _lock.release()
    return True
