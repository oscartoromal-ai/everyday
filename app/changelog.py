"""The app's versions, and what each one changed.

Every pull request that changes the app adds a file to changes/ saying what
changed, one item per change, each of a kind:

    - Feature: Give tasks a priority, shown wherever tasks are
      Lines indented under it say more, in Markdown.
    - Fix: The Update button no longer fails at once

A Major change is a new area of the app, or one reshaped; a Feature is
something new or changed in one; a Fix puts right what was wrong.

Nobody writes a version number. The changes a commit on master's line (its
first parents: a merged pull request, or a commit made on master itself)
brings make a version, numbered from the one before it by the largest of
them: a Major bumps the major number, a Feature the minor, a Fix the patch.
So two pull requests open at once never claim the same number, and their
files never conflict. A file shipped by the commit that added it, unless
it names another (`shipped: <commit>` in its front matter): that is how
the changes from before this file existed sit in the versions they shipped
in. Files not yet committed are Unreleased.

Run from the repo, the versions are read from git as they are asked for
(again only once a commit or a change file has moved on). The installed
app has no git history: desktop/build.ps1 writes them into changelog.json,
bundled with it (`python -m app.changelog --json <path>`).
"""

from __future__ import annotations

import functools
import json
import logging
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from app.config import FROZEN, REPO_ROOT

log = logging.getLogger(__name__)

CHANGES = "changes"
# Bundled with the installed app (desktop/personal-calendar.spec).
BUNDLED = REPO_ROOT / "changelog.json"
# What each kind is called in a change file, largest first, and the part of
# the version it bumps.
KINDS = ("major", "feature", "fix")
_ITEM = re.compile(r"-\s+(?P<kind>\w+):\s*(?P<summary>.+)")
_FRONT = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---\r?\n", re.DOTALL)


class ChangeFileError(ValueError):
    """A change file the changelog cannot read; it names the file."""


@dataclass(frozen=True)
class Change:
    kind: str  # one of KINDS
    summary: str
    details: str = ""  # Markdown


@dataclass(frozen=True)
class Release:
    # None for the changes not yet committed.
    version: str | None
    released: date | None
    commit: str | None
    changes: tuple[Change, ...]

    @property
    def kind(self) -> str:
        """The largest of its changes, the part of the version it bumped."""
        return min((c.kind for c in self.changes), key=KINDS.index)


@dataclass(frozen=True)
class ChangeFile:
    name: str
    shipped: str | None  # a commit, when it names one
    changes: tuple[Change, ...]


def parse(name: str, text: str) -> ChangeFile:
    """A change file: its optional front matter, then its items."""
    shipped = None
    front = _FRONT.match(text)
    if front:
        meta = yaml.safe_load(front["yaml"]) or {}
        if not isinstance(meta, dict) or set(meta) - {"shipped"}:
            raise ChangeFileError(f"{name}: its front matter can only say `shipped: <commit>`")
        shipped = str(meta["shipped"]) if meta.get("shipped") is not None else None
        text = text[front.end():]
    changes: list[Change] = []
    item: dict | None = None

    def close() -> None:
        if item:
            details = "\n".join(item["details"]).strip("\n")
            changes.append(Change(item["kind"], item["summary"], details))

    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            if item:
                item["details"].append("")
            continue
        if line[0].isspace():
            if not item:
                raise ChangeFileError(f"{name}:{number}: an indented line under no change")
            item["details"].append(line[2:] if line.startswith("  ") else line.lstrip())
            continue
        match = _ITEM.fullmatch(line.rstrip())
        kind = match["kind"].lower() if match else None
        if kind not in KINDS:
            raise ChangeFileError(
                f"{name}:{number}: a change starts `- Major: `, `- Feature: ` or `- Fix: `"
            )
        close()
        item = {"kind": kind, "summary": match["summary"].strip(), "details": []}
    close()
    if not changes:
        raise ChangeFileError(f"{name}: no changes in it")
    return ChangeFile(name, shipped, tuple(changes))


def read_files(changes_dir: Path) -> list[ChangeFile]:
    return [
        parse(path.name, path.read_text(encoding="utf-8"))
        for path in sorted(changes_dir.glob("*.md"))
    ]


def bump(version: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if kind == "major":
        return major + 1, 0, 0
    if kind == "feature":
        return major, minor + 1, 0
    return major, minor, patch + 1


# ---- from git ----


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=30,
    )
    return out.stdout


def _mainline(repo: Path) -> list[tuple[str, date]]:
    """HEAD's first parents, oldest first, each with its day."""
    lines = _git(repo, "log", "--first-parent", "--reverse", "--format=%H %cI", "HEAD")
    line = [row.split() for row in lines.splitlines() if row.strip()]
    return [(sha, datetime.fromisoformat(when).date()) for sha, when in line]


def _added(repo: Path) -> dict[str, str]:
    """Each change file's name, and the first of HEAD's first parents to
    bring it (against its own first parent, so a merge brings what its
    pull request added)."""
    out = _git(
        repo, "log", "--first-parent", "--diff-merges=first-parent", "--diff-filter=A",
        "--no-renames", "--reverse", "--name-only", "--format=%x00%H", "HEAD", "--", CHANGES,
    )
    added: dict[str, str] = {}
    for block in out.split("\0")[1:]:
        sha, *paths = [line for line in block.splitlines() if line]
        for path in paths:
            added.setdefault(path.rsplit("/", 1)[-1], sha)
    return added


def _committed(repo: Path) -> set[str]:
    out = _git(repo, "ls-tree", "--name-only", "HEAD", f"{CHANGES}/")
    return {path.rsplit("/", 1)[-1] for path in out.splitlines() if path}


def from_git(repo: Path) -> list[Release]:
    """The releases, newest first, the unreleased changes (if any) on top."""
    files = read_files(repo / CHANGES)
    mainline = _mainline(repo)
    added = _added(repo)
    committed = _committed(repo)
    by_commit: dict[str, list[Change]] = {}
    unreleased: list[Change] = []
    for f in files:
        if f.shipped:
            found = [sha for sha, _ in mainline if sha.startswith(f.shipped)]
            if len(found) != 1:
                raise ChangeFileError(
                    f"{f.name}: shipped: {f.shipped} is not one commit on master's line"
                )
            by_commit.setdefault(found[0], []).extend(f.changes)
        elif f.name in committed and f.name in added:
            by_commit.setdefault(added[f.name], []).extend(f.changes)
        else:
            unreleased.extend(f.changes)
    releases: list[Release] = []
    version = (0, 0, 0)
    for sha, day in mainline:
        if sha not in by_commit:
            continue
        changes = tuple(sorted(by_commit[sha], key=lambda c: KINDS.index(c.kind)))
        version = bump(version, min((c.kind for c in changes), key=KINDS.index))
        releases.append(Release(".".join(map(str, version)), day, sha, changes))
    releases.reverse()
    if unreleased:
        changes = tuple(sorted(unreleased, key=lambda c: KINDS.index(c.kind)))
        releases.insert(0, Release(None, None, None, changes))
    return releases


# ---- as the app reads them ----


def to_json(releases: list[Release]) -> str:
    def plain(r: Release) -> dict:
        out = asdict(r)
        out["released"] = r.released.isoformat() if r.released else None
        return out

    return json.dumps([plain(r) for r in releases], indent=1)


def from_json(data: list[dict]) -> list[Release]:
    """The releases to_json wrote, read back."""
    return [
        Release(
            r["version"],
            date.fromisoformat(r["released"]) if r["released"] else None,
            r["commit"],
            tuple(Change(**c) for c in r["changes"]),
        )
        for r in data
    ]


@dataclass(frozen=True)
class Running:
    """The app as it runs: its version, and the commit it was built from
    (with a + when built with uncommitted work), or run from."""

    version: str
    commit: str
    installed: bool
    releases: tuple[Release, ...]


def version(found: list[Release] | tuple[Release, ...]) -> str:
    """The version the releases come to: the newest one's."""
    return next((r.version for r in found if r.version), "0.0.0")


_cache: tuple[tuple, Running] | None = None


@functools.cache
def _git_dir(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--absolute-git-dir").strip())


def _fingerprint(repo: Path) -> tuple:
    """What moves when the releases might: the worktree's HEAD and its log
    (a commit, a checkout, a pull), and the change files. Files looked at,
    never git run: every page asks."""
    git_dir = _git_dir(repo)
    marks = []
    for path in (git_dir / "HEAD", git_dir / "logs" / "HEAD", *sorted((repo / CHANGES).glob("*"))):
        try:
            marks.append((path.name, path.stat().st_mtime_ns))
        except OSError:
            marks.append((path.name, None))
    return tuple(marks)


def _read_json(path: Path) -> object:
    try:
        # PowerShell writes UTF-8 with a byte-order mark.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def running() -> Running:
    """The app's version and its releases, newest first: bundled with the
    installed app (with build-info.json, desktop/build.ps1), read from git
    run from the repo."""
    global _cache
    if FROZEN:
        if _cache is None:
            found = tuple(from_json(_read_json(BUNDLED) or []))
            info = _read_json(REPO_ROOT / "build-info.json") or {}
            _cache = ((), Running(version(found), info.get("commit", ""), True, found))
        return _cache[1]
    try:
        fingerprint = _fingerprint(REPO_ROOT)
        if _cache is None or _cache[0] != fingerprint:
            found = tuple(from_git(REPO_ROOT))
            commit = _git(REPO_ROOT, "rev-parse", "--short", "HEAD").strip()
            _cache = (fingerprint, Running(version(found), commit, False, found))
    except (OSError, subprocess.SubprocessError, ChangeFileError):
        # Every page names the version: a change file written wrong (which
        # the tests and the build refuse) or no git costs it, not the page.
        log.warning("Could not read the changelog", exc_info=True)
        return Running("", "", False, ())
    return _cache[1]


def main(argv: list[str]) -> None:
    """`--version` prints the version; `--json <path>` writes the releases
    for the installed app; with neither, prints them as text."""
    found = from_git(REPO_ROOT)
    if argv[:1] == ["--version"]:
        print(version(found))
    elif argv[:1] == ["--json"] and len(argv) == 2:
        Path(argv[1]).write_text(to_json(found), encoding="utf-8")
    else:
        for r in found:
            print(f"{r.version or 'Unreleased'}  {r.released or ''}".rstrip())
            for c in r.changes:
                print(f"  {c.kind.title()}: {c.summary}")


if __name__ == "__main__":
    main(sys.argv[1:])
