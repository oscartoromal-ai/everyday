"""Repositories: GitHub's API client (its headers, paging and errors), the
two ways to sign in (the GitHub CLI's, a pasted token), the sync, what
Claude reads, and the page, over a stand-in for GitHub (github_fake.py)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastmcp import Client
from github_fake import (
    CLI_TOKEN,
    LOGIN,
    NAME,
    PASTED_TOKEN,
    FakeCli,
    FakeGitHub,
    fake_account,
    repo_payload,
)

from app.mcp.server import mcp
from app.models import GitHubSource, Repository
from app.services import github as github_svc
from app.sources.github import (
    API_VERSION,
    NEW_TOKEN_URL,
    GitHub,
    GitHubCli,
    GitHubError,
    GitHubSignedOut,
    GitHubSignInFailed,
    GitHubUnavailable,
)
from app.ui.repositories_view import pushed

NOW = datetime(2026, 10, 4, 11, 0)


def utc(moment: datetime) -> str:
    """A local wall time as GitHub writes it: UTC, with a Z."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


# ---- the API ----


def test_every_page_is_read_as_github_links_them(github) -> None:
    github.repos = [repo_payload(i, f"repo-{i}") for i in range(1, 8)]
    github.per_page = 3
    with GitHub(CLI_TOKEN, transport=github.transport()) as api:
        found = api.repositories()
    assert [r["id"] for r in found] == list(range(1, 8))
    first = github.requests[0]
    assert first.headers["authorization"] == f"Bearer {CLI_TOKEN}"
    assert first.headers["x-github-api-version"] == API_VERSION
    assert first.headers["accept"] == "application/vnd.github+json"
    assert first.url.params["affiliation"] == "owner,collaborator,organization_member"
    assert first.url.params["per_page"] == "100"
    assert [r.url.params.get("page") for r in github.requests] == [None, "2", "3"]


@pytest.mark.parametrize(
    ("answer", "error", "words"),
    [
        (
            httpx.Response(401, json={"message": "Bad credentials"}),
            GitHubSignedOut, "Connect again",
        ),
        (
            httpx.Response(403, headers={
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": str(int(datetime(2026, 10, 4, 14, 5).timestamp())),
            }),
            GitHubUnavailable, "until 14:05",
        ),
        (httpx.Response(429, headers={"retry-after": "60"}), GitHubUnavailable, "in a minute"),
        (httpx.Response(502), GitHubUnavailable, "having trouble"),
        (httpx.Response(403, json={"message": "Resource not accessible"}), GitHubError,
         "Resource not accessible"),
        (httpx.ConnectError("offline"), GitHubUnavailable, "Could not reach GitHub"),
    ],
)
def test_github_refusing_says_why(github, answer, error, words) -> None:
    github.fail = answer
    with GitHub(CLI_TOKEN, transport=github.transport()) as api, pytest.raises(error) as raised:
        api.user()
    assert words in str(raised.value)
    assert raised.type is error  # a refusal is not mistaken for a sign-out, or the other way


def test_the_token_link_asks_for_reading_metadata_only() -> None:
    assert NEW_TOKEN_URL.startswith("https://github.com/settings/personal-access-tokens/new?")
    assert "metadata=read" in NEW_TOKEN_URL and "name=Personal+Calendar" in NEW_TOKEN_URL
    assert "contents" not in NEW_TOKEN_URL


# ---- signing in ----


def test_the_cli_lends_its_token_and_the_app_keeps_none(tmp_path, github) -> None:
    cli = FakeCli()
    account = fake_account(tmp_path, github, cli)
    assert account.cli_user() == {"login": LOGIN, "name": NAME}
    assert cli.calls[-1][1:] == ["auth", "token", "--hostname", "github.com"]
    with account.api(GitHubSource.cli) as api:
        assert api.user()["login"] == LOGIN
    assert not account.has_token() and not (tmp_path / "local").exists()

    cli.token = None  # gh auth logout
    assert account.cli_user() is None
    with pytest.raises(GitHubSignedOut, match="gh auth login"):
        account.api(GitHubSource.cli)
    # A token gh still has but GitHub no longer honours.
    cli.token = "gho_revoked"
    assert account.cli_user() is None


def test_no_cli_installed(tmp_path, github) -> None:
    account = fake_account(tmp_path, github, None, installed=False)
    assert not account.cli.installed and account.cli_user() is None


def test_gh_failing_to_run_is_no_sign_in() -> None:
    def broken(args):  # noqa: ANN001, ANN202
        raise OSError("gone")

    assert GitHubCli("gh.exe", run=broken).token() is None


def test_a_pasted_token_is_checked_then_kept(tmp_path, github) -> None:
    account = fake_account(tmp_path, github, None)
    with pytest.raises(GitHubSignInFailed, match="did not accept"):
        account.use_token("ghp_wrong")
    with pytest.raises(GitHubSignInFailed, match="Paste"):
        account.use_token("   ")
    assert not account.has_token()

    assert account.use_token(f"  {PASTED_TOKEN}\n")["login"] == LOGIN
    assert account.token_file.read_text(encoding="utf-8") == PASTED_TOKEN
    with account.api(GitHubSource.token) as api:
        assert api.user()["name"] == NAME
    account.forget()
    with pytest.raises(GitHubSignedOut, match="token is gone"):
        account.api(GitHubSource.token)


# ---- syncing ----


def test_a_repository_reads_as_github_has_it() -> None:
    pushed_at = datetime(2026, 10, 3, 22, 15)
    fields = github_svc.repository_fields(repo_payload(
        7, "pylon-engine", pushed_at=utc(pushed_at), language="Rust", open_issues_count=3,
        description="  Pylon's query engine  ", fork=True, owner="acme-labs",
    ))
    assert fields == {
        "github_id": 7, "full_name": "acme-labs/pylon-engine", "owner": "acme-labs",
        "name": "pylon-engine", "description": "Pylon's query engine", "private": True,
        "fork": True, "archived": False, "language": "Rust", "default_branch": "main",
        "html_url": "https://github.com/acme-labs/pylon-engine", "open_issues": 3,
        "pushed_at": pushed_at,  # in local time
    }
    # Never pushed to, and no language: kept as such.
    bare = github_svc.repository_fields(repo_payload(8, "empty", pushed_at=None, language=None))
    assert (bare["pushed_at"], bare["language"]) == (None, "")
    assert github_svc.repository_fields({"full_name": "a/b"}) is None


def connected(db, account, source=GitHubSource.cli):  # noqa: ANN001, ANN201
    return github_svc.connect(db, {"login": LOGIN, "name": NAME}, source, now=NOW)


def test_the_list_follows_github(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    assert github_svc.sync(db, account) == 0  # not connected: nothing asked
    assert github.requests == []
    connected(db, account)
    github.repos = [repo_payload(1, "everyday-app"), repo_payload(2, "pylon-web")]
    assert github_svc.sync(db, account, now=NOW) == 2
    assert [r.name for r in github_svc.repositories(db)] == ["everyday-app", "pylon-web"]

    # Renamed, archived, one deleted and one new.
    github.repos = [
        repo_payload(1, "personal-calendar", archived=True),
        repo_payload(3, "pylon-docs"),
    ]
    github_svc.sync(db, account, now=NOW + timedelta(hours=1))
    kept = {r.github_id: r for r in db.query(Repository)}
    assert set(kept) == {1, 3}
    assert (kept[1].name, kept[1].archived) == ("personal-calendar", True)
    link = github_svc.link(db)
    assert (link.synced_at, link.sync_error, link.signed_out) == (
        NOW + timedelta(hours=1), "", False,
    )


def test_a_failed_sync_says_why_and_keeps_the_list(db, tmp_path, github) -> None:
    cli = FakeCli()
    account = fake_account(tmp_path, github, cli)
    connected(db, account)
    github_svc.sync(db, account, now=NOW)

    github.fail = httpx.Response(503)
    with pytest.raises(GitHubUnavailable):
        github_svc.sync(db, account, now=NOW + timedelta(hours=1))
    link = github_svc.link(db)
    assert "having trouble" in link.sync_error and not link.signed_out
    assert link.synced_at == NOW and len(github_svc.repositories(db)) == 1

    github.fail, cli.token = None, None  # gh signed out
    with pytest.raises(GitHubSignedOut):
        github_svc.sync(db, account)
    assert link.signed_out and "gh auth login" in link.sync_error

    cli.token = CLI_TOKEN  # signed in again: the next sync clears it
    github_svc.sync(db, account, now=NOW + timedelta(hours=2))
    later = NOW + timedelta(hours=2)
    assert (link.signed_out, link.sync_error, link.synced_at) == (False, "", later)


def test_disconnecting_forgets_the_list(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    connected(db, account)
    github_svc.sync(db, account)
    github_svc.disconnect(db)
    assert github_svc.link(db) is None and github_svc.repositories(db) == []


def test_found_by_their_words_last_pushed_first(db) -> None:
    for i, (name, pushed_at, extra) in enumerate([
        ("booking-dev", NOW - timedelta(days=60), {"language": "Vue"}),
        ("pylon-engine", NOW - timedelta(days=1), {"language": "Rust"}),
        ("pylon-legacy", NOW - timedelta(hours=1), {"archived": True, "language": "Java"}),
        ("empty", None, {}),
        ("everyday-app", NOW, {"description": "Help me manage my life"}),
    ]):
        db.add(Repository(**github_svc.repository_fields(
            repo_payload(i + 1, name, pushed_at=utc(pushed_at) if pushed_at else None, **extra)
        )))
    db.flush()

    def names(query: str = "", **kw) -> list[str]:  # noqa: ANN003
        return [r.name for r in github_svc.repositories(db, query, **kw)]

    assert names() == ["everyday-app", "pylon-legacy", "pylon-engine", "booking-dev", "empty"]
    assert names(archived=False) == ["everyday-app", "pylon-engine", "booking-dev", "empty"]
    assert names(archived=True) == ["pylon-legacy"]
    assert names("PYLON rust") == ["pylon-engine"]
    assert names("manage") == ["everyday-app"]
    assert names("nothing here") == []


def test_pushed_reads_as_a_column() -> None:
    assert pushed(None, NOW) == ""
    assert pushed(NOW - timedelta(seconds=20), NOW) == "Just now"
    assert pushed(NOW - timedelta(minutes=12), NOW) == "12 min ago"
    assert pushed(NOW - timedelta(hours=3, minutes=40), NOW) == "3 h ago"
    assert pushed(datetime(2026, 10, 3, 23, 0), NOW) == "Yesterday"
    assert pushed(datetime(2026, 9, 30, 9, 0), NOW) == "Wed"
    assert pushed(datetime(2026, 9, 23, 9, 0), NOW) == "23 Sep"
    assert pushed(datetime(2025, 8, 25, 9, 0), NOW) == "Aug 2025"


async def test_list_repositories_over_mcp(app_db, tmp_path, github) -> None:
    async with Client(mcp) as client:
        empty = (await client.call_tool("list_repositories", {})).data
    assert empty == {"connected": False, "account": None, "synced_at": None, "repositories": []}
    github.repos = [
        repo_payload(1, "everyday-app", open_issues_count=3),
        repo_payload(2, "pylon-legacy", archived=True, language="Java"),
    ]
    account = fake_account(tmp_path, github, FakeCli())
    with app_db() as db:
        connected(db, account)
        github_svc.sync(db, account, now=NOW)
        db.commit()
    async with Client(mcp) as client:
        got = (await client.call_tool("list_repositories", {})).data
        every = (await client.call_tool("list_repositories", {"include_archived": True})).data
        java = (await client.call_tool(
            "list_repositories", {"query": "java", "include_archived": True}
        )).data
    assert (got["connected"], got["account"], got["synced_at"]) == (True, LOGIN, "2026-10-04T11:00")
    assert got["repositories"] == [{
        "full_name": f"{LOGIN}/everyday-app", "description": "What everyday-app is",
        "language": "Python", "private": True, "fork": False, "archived": False,
        "default_branch": "main", "url": f"https://github.com/{LOGIN}/everyday-app",
        "open_issues_and_pulls": 3, "pushed_at": got["repositories"][0]["pushed_at"],
    }]
    assert len(every["repositories"]) == 2
    assert [r["full_name"] for r in java["repositories"]] == [f"{LOGIN}/pylon-legacy"]


# ---- the page ----


@pytest.fixture
def page_client(client, tmp_path, github):  # noqa: ANN201
    from app.ui.repositories import get_github

    cli = FakeCli()
    account = fake_account(tmp_path, github, cli)
    client.app.dependency_overrides[get_github] = lambda: account
    yield client, account, cli
    github_svc.syncing.wait(5)


def test_connecting_in_one_click_through_the_cli(page_client, db, github) -> None:
    client, account, cli = page_client
    github.repos = [
        repo_payload(1, "everyday-app", open_issues_count=1),
        repo_payload(2, "agent-conductor", private=False),
        repo_payload(3, "lib-fork", owner="acme-labs", fork=True),
        repo_payload(4, "pylon-legacy", archived=True),
    ]
    page = client.get("/repositories").text
    assert "Connect GitHub" in page and 'hx-get="/ui/github/cli"' in page
    assert "Find a repository" not in page  # nothing to find yet

    offer = client.get("/ui/github/cli").text
    assert f"Signed in as {LOGIN}" in offer and 'hx-post="/ui/github/connect/cli"' in offer

    done = client.post("/ui/github/connect/cli")
    assert done.status_code == 204 and done.headers["HX-Refresh"] == "true"
    github_svc.syncing.wait(5)
    db.expire_all()
    link = github_svc.link(db)
    assert (link.login, link.source, link.sync_error) == (LOGIN, GitHubSource.cli, "")
    assert not account.has_token()

    page = client.get("/repositories").text
    for words in ("Find a repository", "everyday-app", "What everyday-app is", "Public",
                  "acme-labs/", "Fork", "Archived", "pylon-legacy",
                  "Through the GitHub CLI on this computer", "Sync now", "Disconnect"):
        assert words in page, words
    assert 'href="https://github.com/oscartoromal-ai/everyday-app" target="_blank"' in page
    assert "Connect GitHub" not in page

    found = client.get("/ui/repositories/list", params={"q": "everyday"}).text
    assert "everyday-app" in found and "agent-conductor" not in found
    assert "No repository holds" in client.get("/ui/repositories/list", params={"q": "zz"}).text


def test_the_cli_signed_out_or_missing(page_client, tmp_path, github) -> None:
    client, account, cli = page_client
    cli.token = None
    offer = client.get("/ui/github/cli").text
    assert "Not signed in" in offer and "gh auth login" in offer and "Check again" in offer
    refused = client.post("/ui/github/connect/cli")
    assert refused.status_code == 200 and "not signed in" in refused.text

    from app.ui.repositories import get_github

    missing = fake_account(tmp_path, github, None, installed=False)
    client.app.dependency_overrides[get_github] = lambda: missing
    assert "winget install GitHub.cli" in client.get("/ui/github/cli").text

    github.fail = httpx.ConnectError("offline")
    client.app.dependency_overrides[get_github] = lambda: account
    cli.token = CLI_TOKEN
    assert "Could not reach GitHub" in client.get("/ui/github/cli").text


def test_connecting_with_a_token_then_disconnecting(page_client, db) -> None:
    client, account, _ = page_client
    wrong = client.post("/ui/github/connect/token", data={"token": "ghp_wrong"})
    assert "did not accept that token" in wrong.text and 'name="token"' in wrong.text

    done = client.post("/ui/github/connect/token", data={"token": PASTED_TOKEN})
    assert done.status_code == 204
    github_svc.syncing.wait(5)
    assert account.has_token()
    page = client.get("/repositories").text
    assert "With a token kept on this computer" in page and "everyday-app" in page

    gone = client.post("/ui/github/disconnect")
    assert gone.headers["HX-Refresh"] == "true" and not account.has_token()
    db.expire_all()
    assert github_svc.link(db) is None and github_svc.repositories(db) == []
    assert "Connect GitHub" in client.get("/repositories").text


def test_signed_out_by_github_asks_to_connect_again(page_client, db) -> None:
    client, account, cli = page_client
    connected(db, account)
    github_svc.sync(db, account, now=NOW)
    cli.token = None
    with pytest.raises(GitHubSignedOut):
        github_svc.sync(db, account)
    db.commit()
    page = client.get("/repositories").text
    assert "Connect GitHub" in page and "Syncing stopped" in page and "gh auth login" in page
    assert "everyday-app" in page  # the list kept stays in sight


def test_syncing_from_the_page(page_client, db) -> None:
    client, account, _ = page_client
    connected(db, account)
    db.commit()
    synced = client.post("/ui/github/sync")
    assert "Syncing" in synced.text or "today" in synced.text
    github_svc.syncing.wait(5)
    polled = client.get("/ui/github/account", headers={"HX-Trigger": "github-account"})
    assert polled.headers["HX-Trigger"] == "github:synced"
    assert "Last sync failed" not in polled.text
