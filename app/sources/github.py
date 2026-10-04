"""GitHub: the accounts the app is signed in as, and its REST API.

Every request the app makes to GitHub goes through here, so the next thing
read from GitHub (issues, pull requests) is a method on GitHub, not a new
client. Oscar connects as many accounts as he has, each either of two ways,
his choice on Repositories:

- The GitHub CLI's own sign-in (`gh auth login`, done once on the machine
  for each account, as GitHub Desktop, VS Code and Claude Code each sign in
  their own way). The app asks gh for the account's token (`gh auth token
  --user`) at each sync and keeps no copy, so signing gh out of it is
  followed.
- A token pasted on the page, best a fine-grained one that reads metadata
  only, kept in a file of its own in `[github].tokens_dir` (git-ignored
  local/).

Only I/O lives here: services/github.py keeps what comes back. Tests stand
in GitHub's API with an httpx transport, and gh with a function.
"""

from __future__ import annotations

import json
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

from app.models import GitHubLink, GitHubSource

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
    """GitHub's REST API, signed in with one token, or with none (public
    repositories alone, at a lower rate). A context manager: its
    connections close at the end."""

    def __init__(
        self,
        token: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = API,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "personal-calendar",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=base_url,
            headers=headers,
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

    def pull_request(self, repo: str, number: int) -> dict[str, Any]:
        """A pull request (owner/name, its number): its title, state
        (open or closed), whether it is a draft, and whether it merged."""
        return self.get(f"/repos/{repo}/pulls/{number}")

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
        args, capture_output=True, text=True, encoding="utf-8", timeout=15,
        stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return done.returncode, done.stdout


class GitHubCli:
    """The GitHub CLI installed on this machine, for its sign-ins: gh holds
    one or more accounts on github.com (`gh auth login` again adds one)."""

    def __init__(self, path: str | None, run: Runner = _run) -> None:
        self.path = path
        self._run = run

    @property
    def installed(self) -> bool:
        return self.path is not None

    def _gh(self, *args: str) -> tuple[int, str] | None:
        if self.path is None:
            return None
        try:
            return self._run([self.path, *args])
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("gh %s failed: %s", " ".join(args[:2]), exc)
            return None

    def logins(self) -> list[str]:
        """The accounts gh is signed in to on github.com, its active one
        first; none when gh is missing or signed out. gh checks each with
        GitHub as it answers: one it can no longer sign in as is left out,
        and GitHubUnavailable says when it could check none."""
        done = self._gh("auth", "status", "--json", "hosts", "--hostname", HOST)
        if done is None:
            return []
        # gh exits 1 while any account's sign-in fails, and still answers.
        try:
            accounts = json.loads(done[1] or "{}").get("hosts", {}).get(HOST) or []
        except (ValueError, AttributeError):
            log.warning("gh auth status answered what the app cannot read")
            return []
        signed_in = [a for a in accounts if a.get("state") == "success" and a.get("login")]
        if not signed_in and any(a.get("state") == "timeout" for a in accounts):
            raise GitHubUnavailable("The GitHub CLI could not reach GitHub. Try again in a moment.")
        signed_in.sort(key=lambda a: not a.get("active"))
        return [a["login"] for a in signed_in]

    def token(self, login: str) -> str | None:
        """gh's token for this account on github.com, or None when gh is
        missing or not signed in to it."""
        done = self._gh("auth", "token", "--hostname", HOST, "--user", login)
        if done is None:
            return None
        code, out = done
        token = out.strip()
        return token if code == 0 and token else None


# ---- the accounts ----


class GitHubAccount:
    """The app's GitHub sign-ins, an account each: the CLI's, or a token
    kept in a file of its own."""

    def __init__(
        self,
        tokens_dir: Path,
        cli: GitHubCli,
        *,
        legacy_token_file: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.tokens_dir = tokens_dir
        self.cli = cli
        # Where the one token was kept while the app connected one account.
        self.legacy_token_file = legacy_token_file
        self._transport = transport

    def _api(self, token: str) -> GitHub:
        return GitHub(token, transport=self._transport)

    def anonymous(self) -> GitHub:
        """The API signed in as no one: public repositories alone."""
        return GitHub(None, transport=self._transport)

    def token_file(self, link_id: int) -> Path:
        return self.tokens_dir / f"{link_id}.txt"

    def has_token(self, link_id: int) -> bool:
        return self.token_file(link_id).is_file()

    def cli_user(self, login: str) -> dict[str, Any] | None:
        """The account gh is signed in to by this login, as GitHub has it
        (its id, login and name), or None when gh is not signed in to it or
        GitHub no longer honours its token."""
        token = self.cli.token(login)
        if token is None:
            return None
        with self._api(token) as api:
            try:
                user = api.user()
            except GitHubSignedOut:
                return None
        return user if str(user.get("login", "")).lower() == login.lower() else None

    def check_token(self, token: str) -> dict[str, Any]:
        """The account a pasted token signs in as, checked with GitHub."""
        token = token.strip()
        if not token:
            raise GitHubSignInFailed("Paste a token to connect with.")
        with self._api(token) as api:
            try:
                return api.user()
            except GitHubSignedOut as exc:
                raise GitHubSignInFailed("GitHub did not accept that token.") from exc

    def keep_token(self, link_id: int, token: str) -> None:
        path = self.token_file(link_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token.strip(), encoding="utf-8")

    def forget(self, link_id: int) -> None:
        """The account's kept token deleted. gh's sign-ins are gh's: they stay."""
        self.token_file(link_id).unlink(missing_ok=True)

    def _kept_token(self, link_id: int) -> str:
        path = self.token_file(link_id)
        legacy = self.legacy_token_file
        if not path.is_file() and legacy is not None and legacy.is_file():
            # The token of the one account connected before there could be
            # more, which can only be this one: moved to its own file.
            path.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(path)
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    def api(self, link: GitHubLink) -> GitHub:
        """The API, signed in as the account, the way it was connected."""
        if link.source == GitHubSource.cli:
            token = self.cli.token(link.login)
            if token is None:
                raise GitHubSignedOut(
                    f"The GitHub CLI on this computer is not signed in as {link.login}. "
                    "Sign it in again (gh auth login), or connect with a token."
                )
        else:
            token = self._kept_token(link.id)
            if not token:
                raise GitHubSignedOut(f"The app's token for {link.login} is gone. Connect again.")
        return self._api(token)


@lru_cache
def account() -> GitHubAccount:
    """The process's GitHub sign-ins, where config says."""
    from app.config import get_settings

    settings = get_settings()
    return GitHubAccount(
        settings.github_tokens_dir,
        GitHubCli(find_cli(settings.github.cli)),
        legacy_token_file=settings.resolve("local/github-token.txt"),
    )
