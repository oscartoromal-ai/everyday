"""Repositories as the page draws it: the repositories, found by their
words, archived ones folded away, and the GitHub account."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import GitHubLink, Repository
from app.services import github as github_svc
from app.sources.github import NEW_TOKEN_URL


def pushed(moment: datetime | None, now: datetime) -> str:
    """When it was last pushed to, for a column: 12 min ago, 3 h ago,
    Yesterday, Wed (this week), 29 Sep (this year), Aug 2025."""
    if moment is None:
        return ""
    ago = now - moment
    if ago < timedelta(minutes=1):
        return "Just now"
    if ago < timedelta(hours=1):
        return f"{int(ago.total_seconds() // 60)} min ago"
    if moment.date() == now.date():
        return f"{int(ago.total_seconds() // 3600)} h ago"
    if moment.date() == now.date() - timedelta(days=1):
        return "Yesterday"
    if moment.date() > now.date() - timedelta(days=7):
        return f"{moment:%a}"
    if moment.year == now.year:
        return f"{moment.day} {moment:%b}"
    return f"{moment:%b %Y}"


def synced(moment: datetime | None, now: datetime) -> str:
    """When the last sync finished: 14:05 today, 14:05 yesterday, 14:05, 3 Oct."""
    if moment is None:
        return ""
    if moment.date() == now.date():
        return f"{moment:%H:%M} today"
    if moment.date() == now.date() - timedelta(days=1):
        return f"{moment:%H:%M} yesterday"
    return f"{moment:%H:%M}, {moment.day} {moment:%b}"


def repo_row(r: Repository, first: GitHubLink | None, now: datetime) -> dict[str, Any]:
    return {
        "name": r.name,
        # Another's repository says whose; his first account's own goes by
        # its name (only the one's, so two of his named alike stay apart).
        "owner": r.owner if first is None or r.owner.lower() != first.login.lower() else "",
        "full_name": r.full_name,
        "description": r.description,
        "url": r.html_url,
        "public": not r.private,
        "fork": r.fork,
        "language": r.language,
        "open_issues": r.open_issues,
        "pushed": pushed(r.pushed_at, now),
        "pushed_full": f"Last pushed {r.pushed_at:%a} {r.pushed_at.day} {r.pushed_at:%b %Y, %H:%M}"
        if r.pushed_at else "Never pushed to",
    }


def list_ctx(db: Session, query: str, now: datetime) -> dict[str, Any]:
    """The repositories holding the query's words: the active ones, then
    the archived ones folded away."""
    links = github_svc.links(db)
    first = links[0] if links else None
    query = query.strip()
    found = github_svc.repositories(db, query)
    return {
        "query": query,
        "has_repos": bool(found) or bool(query and github_svc.repositories(db)),
        "repos": [repo_row(r, first, now) for r in found if not r.archived],
        "archived": [repo_row(r, first, now) for r in found if r.archived],
        "running": github_svc.syncing.running,
        # Fetching the first time: an account connected and not yet synced.
        "fetching": any(not link.signed_out and link.synced_at is None for link in links),
        "connected": any(not link.signed_out for link in links),
    }


def account_ctx(db: Session, now: datetime) -> dict[str, Any]:
    """The accounts group: each account connected (who, how, and how its
    last sync went), when the last sync finished, and the ways to connect
    another, folded away unless an account needs connecting again."""
    links = github_svc.links(db)
    last = max((link.synced_at for link in links if link.synced_at), default=None)
    connected = any(not link.signed_out for link in links)
    return {
        "links": links,
        "connected": connected,
        "signed_out": any(link.signed_out for link in links),
        "running": github_svc.syncing.running,
        "synced": synced(last, now),
        "new_token_url": NEW_TOKEN_URL,
    }


def cli_ctx(db: Session, logins: list[str]) -> dict[str, Any]:
    """The GitHub CLI's accounts as Connect offers them: those not connected
    yet, or signed out since, and whether any is connected already."""
    working = {
        link.login.lower() for link in github_svc.links(db) if not link.signed_out
    }
    return {
        "offer": [login for login in logins if login.lower() not in working],
        "all_connected": bool(logins) and all(login.lower() in working for login in logins),
    }


def page_ctx(db: Session, query: str, now: datetime) -> dict[str, Any]:
    return {**account_ctx(db, now), **list_ctx(db, query, now), "today": now.date()}
