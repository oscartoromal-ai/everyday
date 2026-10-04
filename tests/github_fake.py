"""A stand-in for GitHub's REST API, served through an httpx transport, so
the app's own client (sources/github.py) runs its requests, paging and
error handling against it; and one for the GitHub CLI, signed in to one
account or more."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.sources.github import GitHubAccount, GitHubCli

LOGIN = "oscartoromal-ai"
NAME = "Oscar"
USER_ID = 101
CLI_TOKEN = "gho_cli"
PASTED_TOKEN = "github_pat_pasted"
# A second account of his, signed in to gh as well.
WORK_LOGIN = "oscar-work"
WORK_NAME = "Oscar at work"
WORK_USER_ID = 202
WORK_TOKEN = "gho_work"


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
    """GitHub's API as far as the app reads it: /user and /user/repos for
    each account a token signs in as, paged by per_page and followed
    through the Link header. `repos` are his first account's, `work_repos`
    his second's."""

    def __init__(self) -> None:
        me = {"id": USER_ID, "login": LOGIN, "name": NAME}
        self.users = {
            CLI_TOKEN: me, PASTED_TOKEN: me,
            WORK_TOKEN: {"id": WORK_USER_ID, "login": WORK_LOGIN, "name": WORK_NAME},
        }
        self.repos: list[dict[str, Any]] = [repo_payload(1, "everyday-app")]
        self.work_repos: list[dict[str, Any]] = []
        self.per_page: int | None = None  # GitHub's; None: as asked
        # Pull requests, by (owner/name, number): each GitHub's payload. One
        # is read by an account whose repositories hold its repository, or
        # by anyone when that repository is in `public`.
        self.pulls: dict[tuple[str, int], dict[str, Any]] = {}
        self.public: set[str] = set()
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
        user = self.users.get(token)
        if request.url.path.startswith("/repos/") and "/pulls/" in request.url.path:
            return self._pull(request, user if token else None)
        if user is None:
            return httpx.Response(401, json={"message": "Bad credentials"})
        if request.url.path == "/user":
            return httpx.Response(200, json=user)
        if request.url.path == "/user/repos":
            repos = self.repos if user["login"] == LOGIN else self.work_repos
            size = self.per_page or int(request.url.params.get("per_page", 30))
            page = int(request.url.params.get("page", 1))
            chunk = repos[(page - 1) * size: page * size]
            headers = {}
            if page * size < len(repos):
                url = request.url.copy_merge_params({"page": page + 1})
                headers["Link"] = f'<{url}>; rel="next"'
            return httpx.Response(200, json=chunk, headers=headers)
        return httpx.Response(404, json={"message": "Not Found"})

    def pull(self, repo: str, number: int, **fields: Any) -> dict[str, Any]:
        """A pull request on GitHub: open, not a draft, unless `fields` say."""
        payload = {"number": number, "title": f"Pull {number}", "state": "open",
                   "draft": False, "merged": False, "merged_at": None, **fields}
        self.pulls[(repo.lower(), number)] = payload
        return payload

    def _pull(self, request: httpx.Request, user: dict[str, Any] | None) -> httpx.Response:
        _, _, owner, name, _, number = request.url.path.split("/")
        repo = f"{owner}/{name}".lower()
        if user is None and request.headers.get("authorization"):
            return httpx.Response(401, json={"message": "Bad credentials"})
        reached = repo in self.public or (user is not None and any(
            r["full_name"].lower() == repo
            for r in (self.repos if user["login"] == LOGIN else self.work_repos)
        ))
        payload = self.pulls.get((repo, int(number)))
        if not reached or payload is None:
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json=payload)


class FakeCli:
    """gh's sign-ins on github.com: `gh auth status --json hosts` lists
    them, the first active, and `gh auth token --user` gives each one's
    token, exit 1 for an account it is not signed in to."""

    def __init__(self, accounts: dict[str, str] | None = None) -> None:
        self.accounts = {LOGIN: CLI_TOKEN} if accounts is None else accounts
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        command = args[1:3]
        if command == ["auth", "status"]:
            hosts = {"github.com": [
                {"state": "success", "active": i == 0, "host": "github.com", "login": login}
                for i, login in enumerate(self.accounts)
            ]} if self.accounts else {}
            return (0 if self.accounts else 1), json.dumps({"hosts": hosts})
        if command == ["auth", "token"]:
            token = self.accounts.get(args[args.index("--user") + 1])
            return (0, f"{token}\n") if token else (1, "")
        return 1, ""


def signed_out() -> FakeCli:
    return FakeCli({})


def fake_account(
    tmp_path: Path, github: FakeGitHub, cli: FakeCli | None, installed: bool = True
) -> GitHubAccount:
    """The app's GitHub sign-ins over the stand-ins; gh not installed when
    `installed` is false."""
    gh = GitHubCli("gh.exe" if installed else None, run=cli or signed_out())
    return GitHubAccount(
        tmp_path / "local" / "github-tokens", gh,
        legacy_token_file=tmp_path / "local" / "github-token.txt",
        transport=github.transport(),
    )
