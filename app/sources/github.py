"""GitHub: who the app is signed in as, and its REST API.

Every request the app makes to GitHub goes through here, so the next thing
read from GitHub (issues, pull requests) is a method on GitHub, not a new
client. Signing in is either of two ways, Oscar's choice on Repositories:

- The GitHub CLI's own sign-in (`gh auth login`, done once on the machine,
  as GitHub Desktop, VS Code and Claude Code each sign in their own way).
  The app asks gh for its token (`gh auth token`) at each sync and keeps
  no copy, so signing gh out, or into another account, is followed.
- A token pasted on the page, best a fine-grained one that reads metadata
  only, kept in `[github].token_file` (git-ignored local/).

Only I/O lives here: services/github.py keeps what comes back. Tests stand
in GitHub's API with an httpx transport, and gh with a function.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.models import GitHubSource

log = logging.getLogger(__name__)

API = "https://api.github.com"
HOST = "github.com"
# GitHub's REST API version the app is written against (X-GitHub-Api-Version).
API_VERSION = "2026-03-10"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
PER_PAGE = 100
# A token made for the app: read-only, repositories' metadata (their names,
# descriptions and pushes) and nothing else. GitHub fills the form from
# these; Repository access, "All repositories", is the one choice left.
NEW_TOKEN_URL = "https://github.com/settings/personal-access-tokens/new?" + urlencode({
    "name": "Personal Calendar",
    "description": "Lists my repositories in Personal Calendar (Repositories).",
    "expires_in": "none",
    "metadata": "read",
})


class GitHubError(Exception):
    """GitHub could not do what was asked; the message says why, to Oscar."""


class GitHubSignInFailed(GitHubError):
    """GitHub refused the token offered to connect."""


class GitHubSignedOut(GitHubError):
    """No token, or GitHub no longer accepts it: connect again."""


class GitHubUnavailable(GitHubError):
    """GitHub could not be reached, or is limiting requests: try later."""


# ---- the API ----


def _limited(response: httpx.Response) -> GitHubUnavailable | None:
    """GitHub's rate limit, as a GitHubUnavailable saying until when, or
    None when this refusal is not one."""
    if response.headers.get("retry-after"):
        return GitHubUnavailable("GitHub is limiting requests. Try again in a minute.")
    if response.headers.get("x-ratelimit-remaining") != "0":
        return None
    try:
        reset = datetime.fromtimestamp(int(response.headers["x-ratelimit-reset"]))
    except (KeyError, ValueError):
        return GitHubUnavailable("GitHub is limiting requests. Try again later.")
    return GitHubUnavailable(f"GitHub is limiting requests until {reset:%H:%M}.")


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message") or "").strip()
    except ValueError:
        return ""


class GitHub:
    """GitHub's REST API, signed in with one token. A context manager: its
    connections close at the end."""

    def __init__(
        self, token: str, *, transport: httpx.BaseTransport | None = None, base_url: str = API
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "personal-calendar",
            },
            timeout=TIMEOUT,
            transport=transport,
            follow_redirects=True,
        )

    def __enter__(self) -> GitHub:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        try:
            response = self._http.get(url, params=params)
        except httpx.TransportError as exc:
            log.warning("GitHub not reached: %s", exc)
            raise GitHubUnavailable("Could not reach GitHub. Try again in a moment.") from exc
        if response.is_success:
            return response
        status = response.status_code
        if status == 401:
            raise GitHubSignedOut("GitHub no longer accepts the app's sign-in. Connect again.")
        if status in (403, 429) and (limited := _limited(response)):
            raise limited
        if status >= 500:
            raise GitHubUnavailable("GitHub is having trouble. Try again in a moment.")
        message = _message(response)
        log.warning("GitHub answered %s to %s: %s", status, url, message)
        raise GitHubError(f"GitHub refused: {message or status}.")

    def get(self, path: str, **params: Any) -> Any:
        """One request's JSON."""
        return self._get(path, params or None).json()

    def pages(self, path: str, **params: Any) -> list[Any]:
        """A list GitHub splits into pages, every page of it, followed by
        the Link header as GitHub asks."""
        response = self._get(path, {"per_page": PER_PAGE, **params})
        found = list(response.json())
        while url := response.links.get("next", {}).get("url"):
            response = self._get(url)
            found.extend(response.json())
        return found

    def user(self) -> dict[str, Any]:
        """The account signed in: its login, name and page."""
        return self.get("/user")

    def repositories(self) -> list[dict[str, Any]]:
        """Every repository the account can reach: its own, those it
        collaborates on, and its organizations'; last pushed first."""
        return self.pages(
            "/user/repos", affiliation="owner,collaborator,organization_member", sort="pushed"
        )


# ---- the GitHub CLI ----


def _cli_locations() -> list[Path]:
    """Where gh's Windows installers put it, for an app started without it
    on PATH."""
    places = []
    for root, folder in (("ProgramFiles", "GitHub CLI"), ("LOCALAPPDATA", r"Programs\GitHub CLI")):
        if os.environ.get(root):
            places.append(Path(os.environ[root]) / folder / "gh.exe")
    return places


def find_cli(configured: str = "") -> str | None:
    """gh's path: as configured, else on PATH, else where it installs."""
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("gh")
    if found:
        return found
    return next((str(p) for p in _cli_locations() if p.is_file()), None)


# Runs gh with these arguments; returns its exit code and what it printed.
Runner = Callable[[list[str]], tuple[int, str]]


def _run(args: list[str]) -> tuple[int, str]:
    done = subprocess.run(
        args, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return done.returncode, done.stdout


class GitHubCli:
    """The GitHub CLI installed on this machine, for its sign-in."""

    def __init__(self, path: str | None, run: Runner = _run) -> None:
        self.path = path
        self._run = run

    @property
    def installed(self) -> bool:
        return self.path is not None

    def token(self) -> str | None:
        """gh's token for github.com, or None when gh is missing or signed
        out there."""
        if self.path is None:
            return None
        try:
            code, out = self._run([self.path, "auth", "token", "--hostname", HOST])
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("gh auth token failed: %s", exc)
            return None
        token = out.strip()
        return token if code == 0 and token else None


# ---- the account ----


class GitHubAccount:
    """The app's GitHub sign-in: the CLI's, or a token kept in a file."""

    def __init__(
        self, token_file: Path, cli: GitHubCli, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.token_file = token_file
        self.cli = cli
        self._transport = transport

    def _api(self, token: str) -> GitHub:
        return GitHub(token, transport=self._transport)

    def has_token(self) -> bool:
        return self.token_file.is_file()

    def cli_user(self) -> dict[str, Any] | None:
        """Who the GitHub CLI is signed in as, or None when it is not
        installed, signed out, or its token is no longer honoured."""
        token = self.cli.token()
        if token is None:
            return None
        with self._api(token) as api:
            try:
                return api.user()
            except GitHubSignedOut:
                return None

    def use_token(self, token: str) -> dict[str, Any]:
        """Connect with a pasted token: checked with GitHub, then kept.
        Returns the account it signs in as."""
        token = token.strip()
        if not token:
            raise GitHubSignInFailed("Paste a token to connect with.")
        with self._api(token) as api:
            try:
                user = api.user()
            except GitHubSignedOut as exc:
                raise GitHubSignInFailed("GitHub did not accept that token.") from exc
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(token, encoding="utf-8")
        return user

    def forget(self) -> None:
        """The kept token deleted. gh's sign-in is gh's: it stays."""
        self.token_file.unlink(missing_ok=True)

    def api(self, source: GitHubSource) -> GitHub:
        """The API, signed in the way it was connected."""
        if source == GitHubSource.cli:
            token = self.cli.token()
            if token is None:
                raise GitHubSignedOut(
                    "The GitHub CLI is signed out on this computer. "
                    "Sign it in again (gh auth login), or connect with a token."
                )
        else:
            token = self.token_file.read_text(encoding="utf-8").strip() if self.has_token() else ""
            if not token:
                raise GitHubSignedOut("The app's GitHub token is gone. Connect again.")
        return self._api(token)


@lru_cache
def account() -> GitHubAccount:
    """The process's GitHub sign-in, where config says."""
    from app.config import get_settings

    settings = get_settings()
    return GitHubAccount(settings.github_token_file, GitHubCli(find_cli(settings.github.cli)))
