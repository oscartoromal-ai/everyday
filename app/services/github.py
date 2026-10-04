"""Repositories: the GitHub repositories Oscar can reach, kept as GitHub
has them, through every account of his he has connected.

Connecting (sources/github.py) records a link per account: who is signed
in, and how. A sync then fetches each account's repositories and keeps them
(Repository): new ones added, changed ones updated, and ones gone from
GitHub (deleted, or no longer his to reach) deleted here. A repository two
of his accounts reach is one repository, reached by both, and is kept while
any of them reaches it. The list is GitHub's, not a history of his:
disconnecting an account deletes what only it reached.

The accounts are anything shaped as Accounts, so tests stand in a fake.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import GitHubLink, GitHubSource, Repository
from app.services.syncing import Syncing
from app.sources.github import GitHub, GitHubError, GitHubSignedOut

log = logging.getLogger(__name__)


class Accounts(Protocol):
    def api(self, link: GitHubLink) -> GitHub: ...


# ---- the links ----


def links(db: Session) -> list[GitHubLink]:
    """Every account connected, first connected first."""
    return list(db.scalars(select(GitHubLink).order_by(GitHubLink.id)))


def get_link(db: Session, link_id: int) -> GitHubLink | None:
    return db.get(GitHubLink, link_id)


def _same_account(db: Session, user: dict[str, Any]) -> GitHubLink | None:
    """The link to this GitHub account, if it is connected already: by its
    id, which a rename keeps, else by its login."""
    user_id, login = user.get("id"), str(user.get("login") or "")
    if isinstance(user_id, int):
        row = db.scalars(select(GitHubLink).where(GitHubLink.user_id == user_id)).first()
        if row is not None:
            return row
    return db.scalars(
        select(GitHubLink).where(func.lower(GitHubLink.login) == login.lower())
    ).first()


def connect(
    db: Session, user: dict[str, Any], source: GitHubSource, now: datetime | None = None
) -> GitHubLink:
    """Record the link once signed in. Signing in again as an account
    connected already signs it in the new way, its repositories kept."""
    row = _same_account(db, user)
    if row is None:
        row = GitHubLink(connected_at=now or datetime.now())
        db.add(row)
    row.source = source
    row.user_id = user.get("id") if isinstance(user.get("id"), int) else row.user_id
    row.login, row.name = user.get("login") or "", user.get("name") or ""
    row.sync_error, row.signed_out = "", False
    db.flush()
    return row


def _drop_unreached(db: Session) -> None:
    """The repositories no connected account reaches any more, deleted."""
    db.execute(delete(Repository).where(~Repository.links.any()))


def disconnect(db: Session, link: GitHubLink) -> None:
    """Forget the account, and the repositories only it reached."""
    db.delete(link)
    db.flush()
    _drop_unreached(db)
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


def keep_repositories(db: Session, link: GitHubLink, found: list[dict[str, Any]]) -> None:
    """The repositories the account reaches as GitHub has them now: new ones
    added, changed ones updated, and ones it no longer reaches let go of,
    deleted once no account reaches them."""
    wanted = {}
    for raw in found:
        fields = repository_fields(raw)
        if fields:
            wanted[fields["github_id"]] = fields
    link.repositories = [r for r in link.repositories if r.github_id in wanted]
    known = {
        row.github_id: row
        for row in db.scalars(select(Repository).where(Repository.github_id.in_(wanted)))
    }
    for github_id, fields in wanted.items():
        row = known.get(github_id)
        if row is None:
            row = Repository(**fields)
            db.add(row)
        else:
            for name, value in fields.items():
                setattr(row, name, value)
        if row not in link.repositories:
            link.repositories.append(row)
    db.flush()
    _drop_unreached(db)
    db.flush()


def sync_link(
    db: Session, accounts: Accounts, link: GitHubLink, now: datetime | None = None
) -> int:
    """Fetch the account's repositories and keep them; the link notes how it
    went. Returns how many it reaches. A GitHub error is recorded on the
    link (and raised), the repositories kept before staying as they were."""
    try:
        with accounts.api(link) as api:
            user = api.user()
            found = api.repositories()
    except GitHubError as exc:
        link.sync_error = str(exc)
        link.signed_out = isinstance(exc, GitHubSignedOut)
        db.flush()
        raise
    keep_repositories(db, link, found)
    # A rename on GitHub is followed; its id, which a rename keeps, learnt.
    link.login, link.name = user.get("login") or link.login, user.get("name") or ""
    if isinstance(user.get("id"), int):
        link.user_id = user["id"]
    link.synced_at, link.sync_error, link.signed_out = now or datetime.now(), "", False
    db.flush()
    return len(found)


def sync(db: Session, accounts: Accounts, now: datetime | None = None) -> int:
    """Sync every account, each on its own and committed as it is done: one
    GitHub refuses keeps its error on its link, and the others sync all the
    same. An account connected while the sync runs is synced before it
    ends. Returns how many repositories are kept."""
    tried: set[int] = set()
    while pending := [(row.id, row.login) for row in links(db) if row.id not in tried]:
        for link_id, login in pending:
            tried.add(link_id)
            row = get_link(db, link_id)
            if row is None:  # disconnected meanwhile
                continue
            try:
                count = sync_link(db, accounts, row, now)
                log.info("GitHub sync of %s: %d repositories", login, count)
            except GitHubError as exc:
                log.warning("GitHub sync of %s failed: %s", login, exc)
            except Exception:
                log.exception("GitHub sync of %s crashed", login)
                db.rollback()
                if (row := get_link(db, link_id)) is not None:
                    row.sync_error = "The sync stopped on an error. It is in the app's log."
            db.commit()
    return db.scalar(select(func.count()).select_from(Repository)) or 0


syncing = Syncing("github-sync")


def run_sync(factory: Callable[[], Session], accounts: Accounts) -> None:
    """A whole sync in its own session: for a thread."""
    with factory() as db:
        sync(db, accounts)


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


# owner/name in a repository's URL on GitHub, over HTTPS or SSH.
_ON_GITHUB = re.compile(
    r"github\.com[/:]([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$", re.IGNORECASE
)


def full_name_of(location: str) -> str | None:
    """owner/name, lowercased, of a repository written as its URL on GitHub
    (https://github.com/me/app, git@github.com:me/app.git), or None for a
    folder or another host."""
    found = _ON_GITHUB.search(location.strip())
    return f"{found[1]}/{found[2]}".lower() if found else None


def repository_dict(r: Repository) -> dict[str, Any]:
    return {
        "full_name": r.full_name, "description": r.description, "language": r.language,
        "private": r.private, "fork": r.fork, "archived": r.archived,
        "default_branch": r.default_branch, "url": r.html_url,
        "open_issues_and_pulls": r.open_issues,
        "pushed_at": r.pushed_at.isoformat(timespec="minutes") if r.pushed_at else None,
        "accounts": [link.login for link in r.links],
    }
