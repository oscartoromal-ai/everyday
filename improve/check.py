"""The gate a fix passes before its pull request: lint, then the tests, green.

    uv run python -m improve.check [--build] [--json] [--repo <checkout>]

Each step's outcome is printed, a failing one with the end of its output;
it exits 1 when any step fails. --build also builds the desktop app
(desktop/build.ps1, never installing it), for a change that could break the
frozen app: a new file it must bundle, a new dependency. --json prints the
whole as JSON instead, for a script to read. --repo checks another checkout
(a pull request's) with this one's gate, which that pull request cannot
change.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from improve import sources
from improve.scan import CHECKOUT


def steps(build: bool, repo: Path = CHECKOUT) -> list[tuple[str, list[str]]]:
    uv = shutil.which("uv") or "uv"
    found = [
        ("lint", [uv, "run", "ruff", "check", "."]),
        ("tests", [uv, "run", "pytest", "-p", "no:cacheprovider", "--tb=short", "-rfE"]),
    ]
    if build:
        found.append(
            (
                "build",
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(repo / "desktop" / "build.ps1"),
                ],
            )
        )
    return found


def check(build: bool = False, repo: Path = CHECKOUT) -> list[dict]:
    outcomes = []
    for name, cmd in steps(build, repo):
        started = time.monotonic()
        try:
            out = sources.run_tool(cmd, repo, timeout=3 * 3600)
            ok, output = out.returncode == 0, out.stdout + out.stderr
        except sources.SourceFailed as exc:
            ok, output = False, str(exc)
        outcomes.append(
            {
                "step": name,
                "ok": ok,
                "seconds": round(time.monotonic() - started),
                "output": "" if ok else sources.tail(output),
            }
        )
    return outcomes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m improve.check", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--build", action="store_true", help="also build the desktop app")
    parser.add_argument("--json", action="store_true", help="print the outcome as JSON")
    parser.add_argument("--repo", type=Path, default=CHECKOUT, help="the checkout to check")
    args = parser.parse_args(argv)
    outcomes = check(args.build, args.repo)
    passed = all(o["ok"] for o in outcomes)
    if args.json:
        print(json.dumps({"ok": passed, "steps": outcomes}, indent=2))
    else:
        for o in outcomes:
            print(f"{'ok  ' if o['ok'] else 'FAIL'} {o['step']} ({o['seconds']}s)")
            if o["output"]:
                print(o["output"], end="\n\n")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
