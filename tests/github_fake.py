"""A stand-in for GitHub's REST API, served through an httpx transport, so
the app's own client (sources/github.py) runs its requests, paging and
error handling against it; and one for the GitHub CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.sources.github import GitHubAccount, GitHubCli

LOGIN = "oscartoromal-ai"
NAME = "Oscar"
CLI_TOKEN = "gho_cli"
PASTED_TOKEN = "github_pat_pasted"


def repo_payload(
    github_id: int, name: str, pushed_at: str | None = "2026-10-03T22:00:00Z", **extra: Any
) -> dict[str, Any]:
    owner = extra.pop("owner", LOGIN)
    return {
        "id": github_id,
        "name": name,
        "full_name": f"{owner}/{name}",
        "owner": {"login": owner, "type": "User"},
        "description": f"What {name} is",
        "private": True,
        "fork": False,
        "archived": False,
        "language": "Python",
        "default_branch": "main",
        "html_url": f"https://github.com/{owner}/{name}",
        "open_issues_count": 0,
        "pushed_at": pushed_at,
        **extra,
    }


class FakeGitHub:
    """GitHub's API as far as the app reads it: /user and /user/repos,
    paged by per_page and followed through the Link header."""

    def __init__(self) -> None:
        self.tokens = {CLI_TOKEN, PASTED_TOKEN}
        self.repos: list[dict[str, Any]] = [repo_payload(1, "everyday-app")]
        self.per_page: int | None = None  # GitHub's; None: as asked
        self.fail: httpx.Response | Exception | None = None
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.fail, Exception):
            raise self.fail
        if self.fail is not None:
            return self.fail
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in self.tokens:
            return httpx.Response(401, json={"message": "Bad credentials"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": LOGIN, "name": NAME})
        if request.url.path == "/user/repos":
            size = self.per_page or int(request.url.params.get("per_page", 30))
            page = int(request.url.params.get("page", 1))
            chunk = self.repos[(page - 1) * size: page * size]
            headers = {}
            if page * size < len(self.repos):
                url = request.url.copy_merge_params({"page": page + 1})
                headers["Link"] = f'<{url}>; rel="next"'
            return httpx.Response(200, json=chunk, headers=headers)
        return httpx.Response(404, json={"message": "Not Found"})


class FakeCli:
    """`gh auth token`: its token while signed in, exit 1 when not."""

    def __init__(self, token: str | None = CLI_TOKEN) -> None:
        self.token = token
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        return (0, f"{self.token}\n") if self.token else (1, "")


def fake_account(
    tmp_path: Path, github: FakeGitHub, cli: FakeCli | None, installed: bool = True
) -> GitHubAccount:
    """The app's GitHub sign-in over the stand-ins; gh not installed when
    `installed` is false."""
    gh = GitHubCli("gh.exe" if installed else None, run=cli or FakeCli(None))
    return GitHubAccount(tmp_path / "local" / "github-token.txt", gh, transport=github.transport())
