"""Repositories: the GitHub repositories Oscar can reach, kept as GitHub
has them.

Connecting (sources/github.py) records the link: who is signed in, and how.
A sync then fetches every repository and keeps them (Repository): new ones
added, changed ones updated, and ones gone from GitHub (deleted, or no
longer his to reach) deleted here. The list is GitHub's, not a history of
his: disconnecting deletes it with the link.

The account is anything shaped as Account, so tests stand in a fake.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import GitHubLink, GitHubSource, Repository
from app.services.syncing import Syncing
from app.sources.github import GitHub, GitHubError, GitHubSignedOut

log = logging.getLogger(__name__)


class Account(Protocol):
    def api(self, source: GitHubSource) -> GitHub: ...


# ---- the link ----


def link(db: Session) -> GitHubLink | None:
    return db.scalars(select(GitHubLink).order_by(GitHubLink.id)).first()


def connect(
    db: Session, user: dict[str, Any], source: GitHubSource, now: datetime | None = None
) -> GitHubLink:
    """Record the link once signed in; a second sign-in replaces the first."""
    db.execute(delete(GitHubLink))
    row = GitHubLink(
        source=source, login=user.get("login") or "", name=user.get("name") or "",
        connected_at=now or datetime.now(),
    )
    db.add(row)
    db.flush()
    return row


def disconnect(db: Session) -> None:
    """Forget the link, and the repositories with it."""
    db.execute(delete(GitHubLink))
    db.execute(delete(Repository))
    db.flush()


# ---- reading GitHub's repositories ----


def _moment(value: Any) -> datetime | None:
    """GitHub's UTC time ("2026-10-04T00:34:43Z") in local wall time."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment


def repository_fields(raw: dict[str, Any]) -> dict[str, Any] | None:
    """A Repository's columns from GitHub's repository, or None when it has
    no id or name to keep it by."""
    github_id, full_name = raw.get("id"), raw.get("full_name")
    if not isinstance(github_id, int) or not full_name:
        return None
    owner, _, name = str(full_name).partition("/")
    return {
        "github_id": github_id,
        "full_name": str(full_name),
        "owner": (raw.get("owner") or {}).get("login") or owner,
        "name": raw.get("name") or name,
        "description": (raw.get("description") or "").strip(),
        "private": bool(raw.get("private")),
        "fork": bool(raw.get("fork")),
        "archived": bool(raw.get("archived")),
        "language": raw.get("language") or "",
        "default_branch": raw.get("default_branch") or "",
        "html_url": raw.get("html_url") or f"https://github.com/{full_name}",
        "open_issues": int(raw.get("open_issues_count") or 0),
        "pushed_at": _moment(raw.get("pushed_at")),
    }


# ---- syncing ----


def keep_repositories(db: Session, found: list[dict[str, Any]]) -> None:
    """The repositories as GitHub has them now: new ones added, changed
    ones updated, and ones not found deleted."""
    wanted = {}
    for raw in found:
        fields = repository_fields(raw)
        if fields:
            wanted[fields["github_id"]] = fields
    kept = {row.github_id: row for row in db.scalars(select(Repository))}
    for github_id, row in kept.items():
        if github_id not in wanted:
            db.delete(row)
    for github_id, fields in wanted.items():
        row = kept.get(github_id)
        if row is None:
            db.add(Repository(**fields))
        else:
            for name, value in fields.items():
                setattr(row, name, value)
    db.flush()


def sync(db: Session, account: Account, now: datetime | None = None) -> int:
    """Fetch every repository and keep them; the link notes how it went.
    Returns how many there are. A GitHub error is recorded on the link (and
    raised), the repositories kept before staying as they were."""
    now = now or datetime.now()
    row = link(db)
    if row is None:
        return 0
    try:
        with account.api(row.source) as api:
            user = api.user()
            found = api.repositories()
    except GitHubError as exc:
        row.sync_error = str(exc)
        row.signed_out = isinstance(exc, GitHubSignedOut)
        db.flush()
        raise
    keep_repositories(db, found)
    # gh may since have signed in as someone else: the link follows.
    row.login, row.name = user.get("login") or row.login, user.get("name") or ""
    row.synced_at, row.sync_error, row.signed_out = now, "", False
    db.flush()
    return len(found)


syncing = Syncing("github-sync")


def run_sync(factory: Callable[[], Session], account: Account) -> None:
    """A whole sync in its own session, committed at its end: for a thread."""
    with factory() as db:
        if link(db) is None:
            return
        try:
            count = sync(db, account)
            log.info("GitHub sync: %d repositories", count)
        except GitHubError as exc:
            log.warning("GitHub sync failed: %s", exc)
        except Exception:
            log.exception("GitHub sync crashed")
            db.rollback()
            row = link(db)
            if row is not None:
                row.sync_error = "The sync stopped on an error. It is in the app's log."
        db.commit()


# ---- reading ----


def _matches(repo: Repository, words: list[str]) -> bool:
    text = f"{repo.full_name} {repo.description} {repo.language}".lower()
    return all(word in text for word in words)


def repositories(
    db: Session, query: str = "", *, archived: bool | None = None
) -> list[Repository]:
    """The repositories kept, last pushed first (never pushed to last),
    those holding every word of `query` in their name, description or
    language; archived ones alone, or none of them, when asked."""
    stmt = select(Repository).order_by(
        Repository.pushed_at.is_(None), Repository.pushed_at.desc(), Repository.full_name
    )
    if archived is not None:
        stmt = stmt.where(Repository.archived.is_(archived))
    found = list(db.scalars(stmt))
    words = query.lower().split()
    return [r for r in found if _matches(r, words)] if words else found


def repository_dict(r: Repository) -> dict[str, Any]:
    return {
        "full_name": r.full_name, "description": r.description, "language": r.language,
        "private": r.private, "fork": r.fork, "archived": r.archived,
        "default_branch": r.default_branch, "url": r.html_url,
        "open_issues_and_pulls": r.open_issues,
        "pushed_at": r.pushed_at.isoformat(timespec="minutes") if r.pushed_at else None,
    }
