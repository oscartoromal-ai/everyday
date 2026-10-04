"""Repositories' routes: the page and its list (found by its words),
connecting GitHub accounts (through the GitHub CLI's sign-ins, or a token),
syncing, and disconnecting one."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, sessionmaker

from app.db import DbSession
from app.models import GitHubSource
from app.services import github as github_svc
from app.sources.github import GitHubAccount, GitHubError, GitHubUnavailable, account
from app.ui.repositories_view import account_ctx, cli_ctx, list_ctx, page_ctx
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


def get_github() -> GitHubAccount:
    """The app's GitHub sign-ins, or a stand-in under test."""
    return account()


GitHub = Annotated[GitHubAccount, Depends(get_github)]


@router.get("/repositories")
def repositories_page(request: Request, db: DbSession, q: str = ""):
    ctx = page_ctx(db, q, datetime.now())
    return templates.TemplateResponse(
        request, "repositories.html", {"request": request, "active": "repositories", **ctx}
    )


@router.get("/ui/repositories/list")
def repositories_list(request: Request, db: DbSession, q: str = ""):
    ctx = list_ctx(db, q, datetime.now())
    return templates.TemplateResponse(
        request, "partials/repositories_list.html", {"request": request, **ctx}
    )


def _account(request: Request, db: Session, error: str = "") -> Response:
    ctx = {"request": request, **account_ctx(db, datetime.now()), "error": error}
    return templates.TemplateResponse(request, "partials/github_account.html", ctx)


def _start_sync(db: Session, github: GitHubAccount) -> None:
    """The sync, in its own thread and session, on the request's database.
    One running already syncs an account connected meanwhile before it ends."""
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    github_svc.syncing.start(lambda: github_svc.run_sync(factory, github))


def _connected(db: Session, github: GitHubAccount, user: dict, source: GitHubSource,
               token: str = "") -> Response:
    """Signed in: the link recorded (its token kept, for a pasted one), the
    sync begun, the page drawn again around it."""
    link = github_svc.connect(db, user, source)
    if source == GitHubSource.token:
        github.keep_token(link.id, token)
    else:
        github.forget(link.id)  # a token kept from before is no longer its sign-in
    db.commit()
    _start_sync(db, github)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.get("/ui/github/cli")
def github_cli(request: Request, db: DbSession, github: GitHub):
    """The accounts the GitHub CLI here is signed in to, those not connected
    yet offered: asked once the page is up, since it asks gh, which asks
    GitHub."""
    logins, error = [], ""
    try:
        logins = github.cli.logins()
    except GitHubUnavailable as exc:
        error = str(exc)
    ctx = {
        "request": request, "installed": github.cli.installed, "error": error,
        **cli_ctx(db, logins),
    }
    return templates.TemplateResponse(request, "partials/github_cli.html", ctx)


@router.post("/ui/github/connect/cli")
def github_connect_cli(
    request: Request, db: DbSession, github: GitHub, login: Annotated[str, Form()] = ""
):
    try:
        user = github.cli_user(login) if login else None
    except GitHubError as exc:
        return _account(request, db, str(exc))
    if user is None:
        return _account(
            request, db, f"The GitHub CLI is not signed in as {login or 'that account'}. "
            "Run gh auth login first."
        )
    return _connected(db, github, user, GitHubSource.cli)


@router.post("/ui/github/connect/token")
def github_connect_token(
    request: Request, db: DbSession, github: GitHub, token: Annotated[str, Form()] = ""
):
    try:
        user = github.check_token(token)
    except GitHubError as exc:
        return _account(request, db, str(exc))
    return _connected(db, github, user, GitHubSource.token, token)


@router.post("/ui/github/sync")
def github_sync(request: Request, db: DbSession, github: GitHub):
    if github_svc.links(db):
        _start_sync(db, github)
    return _account(request, db)


@router.get("/ui/github/account")
def github_account(request: Request, db: DbSession):
    response = _account(request, db)
    # Asked after a sync (its poll): once it is done, the list is drawn again.
    if request.headers.get("HX-Trigger") == "github-account" and not github_svc.syncing.running:
        response.headers["HX-Trigger"] = "github:synced"
    return response


@router.post("/ui/github/{link_id}/disconnect")
def github_disconnect(db: DbSession, github: GitHub, link_id: int):
    github_svc.syncing.wait(30)  # a sync ending now would bring its list back
    link = github_svc.get_link(db, link_id)
    if link is None:
        raise HTTPException(404, "No such GitHub account is connected")
    github.forget(link.id)
    github_svc.disconnect(db, link)
    db.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})

