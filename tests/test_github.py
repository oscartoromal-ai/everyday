"""Repositories: GitHub's API client (its headers, paging and errors), the
two ways to sign in (the GitHub CLI's, a pasted token), each account of
several, the sync, what Claude reads, and the page, over a stand-in for
GitHub (github_fake.py)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastmcp import Client
from github_fake import (
    CLI_TOKEN,
    LOGIN,
    NAME,
    PASTED_TOKEN,
    USER_ID,
    WORK_LOGIN,
    WORK_NAME,
    WORK_TOKEN,
    WORK_USER_ID,
    FakeCli,
    FakeGitHub,
    fake_account,
    repo_payload,
    signed_out,
)

from app.mcp.server import mcp
from app.models import GitHubLink, GitHubSource, Repository
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


def test_the_cli_lends_each_accounts_token_and_the_app_keeps_none(tmp_path, github) -> None:
    cli = FakeCli({WORK_LOGIN: WORK_TOKEN, LOGIN: CLI_TOKEN})
    account = fake_account(tmp_path, github, cli)
    assert account.cli.logins() == [WORK_LOGIN, LOGIN]  # gh's active one first
    assert cli.calls[-1][1:] == ["auth", "status", "--json", "hosts", "--hostname", "github.com"]
    assert account.cli_user(LOGIN) == {"id": USER_ID, "login": LOGIN, "name": NAME}
    assert cli.calls[-1][1:] == ["auth", "token", "--hostname", "github.com", "--user", LOGIN]
    assert account.cli_user(WORK_LOGIN)["id"] == WORK_USER_ID
    link = GitHubLink(id=1, source=GitHubSource.cli, login=WORK_LOGIN)
    with account.api(link) as api:
        assert api.user()["login"] == WORK_LOGIN
    assert not (tmp_path / "local").exists()

    del cli.accounts[WORK_LOGIN]  # gh auth logout --user oscar-work
    assert account.cli.logins() == [LOGIN]
    assert account.cli_user(WORK_LOGIN) is None
    with pytest.raises(GitHubSignedOut, match=f"not signed in as {WORK_LOGIN}"):
        account.api(link)
    # A token gh still has but GitHub no longer honours.
    cli.accounts[LOGIN] = "gho_revoked"
    assert account.cli_user(LOGIN) is None


def test_gh_reading_its_sign_ins(tmp_path, github) -> None:
    assert fake_account(tmp_path, github, None, installed=False).cli.logins() == []
    assert GitHubCli("gh.exe", run=signed_out()).logins() == []

    def answering(text: str):  # noqa: ANN202
        return lambda args: (1, text)

    lapsed = {"hosts": {"github.com": [
        {"state": "error", "active": True, "login": "old-account"},
        {"state": "success", "active": False, "login": LOGIN},
    ]}}
    assert GitHubCli("gh.exe", run=answering(json.dumps(lapsed))).logins() == [LOGIN]
    assert GitHubCli("gh.exe", run=answering("unknown flag: --json")).logins() == []
    offline = {"hosts": {"github.com": [{"state": "timeout", "active": True, "login": LOGIN}]}}
    with pytest.raises(GitHubUnavailable, match="could not reach GitHub"):
        GitHubCli("gh.exe", run=answering(json.dumps(offline))).logins()

    def broken(args):  # noqa: ANN001, ANN202
        raise OSError("gone")

    assert GitHubCli("gh.exe", run=broken).token(LOGIN) is None
    assert GitHubCli("gh.exe", run=broken).logins() == []


def test_a_pasted_token_is_checked_then_kept_for_its_account(tmp_path, github) -> None:
    account = fake_account(tmp_path, github, None)
    with pytest.raises(GitHubSignInFailed, match="did not accept"):
        account.check_token("ghp_wrong")
    with pytest.raises(GitHubSignInFailed, match="Paste"):
        account.check_token("   ")

    assert account.check_token(f"  {PASTED_TOKEN}\n")["login"] == LOGIN
    account.keep_token(7, f"  {PASTED_TOKEN}\n")
    assert account.token_file(7).read_text(encoding="utf-8") == PASTED_TOKEN
    link = GitHubLink(id=7, source=GitHubSource.token, login=LOGIN)
    with account.api(link) as api:
        assert api.user()["name"] == NAME
    account.forget(7)
    with pytest.raises(GitHubSignedOut, match=f"token for {LOGIN} is gone"):
        account.api(link)


def test_the_one_token_kept_before_moves_to_its_accounts_file(tmp_path, github) -> None:
    account = fake_account(tmp_path, github, None)
    account.legacy_token_file.parent.mkdir(parents=True)
    account.legacy_token_file.write_text(PASTED_TOKEN, encoding="utf-8")
    with account.api(GitHubLink(id=3, source=GitHubSource.token, login=LOGIN)) as api:
        assert api.user()["login"] == LOGIN
    assert not account.legacy_token_file.exists() and account.has_token(3)


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


ME = {"id": USER_ID, "login": LOGIN, "name": NAME}
WORK = {"id": WORK_USER_ID, "login": WORK_LOGIN, "name": WORK_NAME}


def connected(db, user=ME, source=GitHubSource.cli):  # noqa: ANN001, ANN201
    return github_svc.connect(db, user, source, now=NOW)


def test_the_list_follows_github(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    assert github_svc.sync(db, account) == 0  # not connected: nothing asked
    assert github.requests == []
    connected(db)
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
    (link,) = github_svc.links(db)
    assert (link.synced_at, link.sync_error, link.signed_out) == (
        NOW + timedelta(hours=1), "", False,
    )


def test_two_accounts_reach_one_list(db, tmp_path, github) -> None:
    cli = FakeCli({LOGIN: CLI_TOKEN, WORK_LOGIN: WORK_TOKEN})
    account = fake_account(tmp_path, github, cli)
    shared = repo_payload(5, "pylon-platform", owner="acme-labs")
    github.repos = [repo_payload(1, "everyday-app"), shared]
    github.work_repos = [repo_payload(9, "roadmaps", owner=WORK_LOGIN), shared]
    me, work = connected(db), connected(db, WORK)
    assert github_svc.sync(db, account, now=NOW) == 3  # the shared one once
    platform = db.query(Repository).filter_by(github_id=5).one()
    assert [link.login for link in platform.links] == [LOGIN, WORK_LOGIN]
    assert github_svc.repository_dict(platform)["accounts"] == [LOGIN, WORK_LOGIN]

    # The work account loses it: still his, through the other.
    github.work_repos = [repo_payload(9, "roadmaps", owner=WORK_LOGIN)]
    github_svc.sync(db, account, now=NOW)
    assert [link.login for link in platform.links] == [LOGIN]

    # Disconnecting one goes with what only it reached.
    github.work_repos = [repo_payload(9, "roadmaps", owner=WORK_LOGIN), shared]
    github_svc.sync(db, account, now=NOW)
    github_svc.disconnect(db, me)
    assert {r.name for r in github_svc.repositories(db)} == {"roadmaps", "pylon-platform"}
    assert github_svc.links(db) == [work]


def test_one_account_failing_leaves_the_others_syncing(db, tmp_path, github) -> None:
    cli = FakeCli({LOGIN: CLI_TOKEN, WORK_LOGIN: WORK_TOKEN})
    account = fake_account(tmp_path, github, cli)
    github.work_repos = [repo_payload(9, "roadmaps", owner=WORK_LOGIN)]
    me, work = connected(db), connected(db, WORK)
    github_svc.sync(db, account, now=NOW)

    del cli.accounts[LOGIN]  # gh signed out of the first
    github.repos = [repo_payload(1, "everyday-app", description="Renamed meanwhile")]
    github.work_repos.append(repo_payload(10, "booking-lambda", owner=WORK_LOGIN))
    later = NOW + timedelta(hours=1)
    assert github_svc.sync(db, account, now=later) == 3
    assert me.signed_out and "gh auth login" in me.sync_error and me.synced_at == NOW
    assert (work.signed_out, work.sync_error, work.synced_at) == (False, "", later)
    # What the signed-out one reached stays as it was, in sight.
    assert db.query(Repository).filter_by(github_id=1).one().description == "What everyday-app is"

    cli.accounts[LOGIN] = CLI_TOKEN  # signed in again: the next sync clears it
    github_svc.sync(db, account, now=later)
    assert (me.signed_out, me.sync_error, me.synced_at) == (False, "", later)


def test_a_failed_sync_says_why_and_keeps_the_list(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    link = connected(db)
    github_svc.sync(db, account, now=NOW)

    github.fail = httpx.Response(503)
    with pytest.raises(GitHubUnavailable):
        github_svc.sync_link(db, account, link, now=NOW + timedelta(hours=1))
    assert "having trouble" in link.sync_error and not link.signed_out
    assert link.synced_at == NOW and len(github_svc.repositories(db)) == 1


def test_a_sync_crashing_on_one_account_says_so_on_it(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli({LOGIN: CLI_TOKEN, WORK_LOGIN: WORK_TOKEN}))
    me, work = connected(db), connected(db, WORK)
    db.commit()

    class Crashing:
        def api(self, link):  # noqa: ANN001, ANN202
            if link.login == LOGIN:
                raise RuntimeError("a bug")
            return account.api(link)

    github_svc.sync(db, Crashing(), now=NOW)
    assert "stopped on an error" in me.sync_error and work.synced_at == NOW


def test_an_account_connected_while_syncing_is_synced_too(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli({LOGIN: CLI_TOKEN, WORK_LOGIN: WORK_TOKEN}))
    connected(db)
    db.commit()

    class ConnectingMeanwhile:
        def api(self, link):  # noqa: ANN001, ANN202
            if link.login == LOGIN and len(github_svc.links(db)) == 1:
                connected(db, WORK)
            return account.api(link)

    github_svc.sync(db, ConnectingMeanwhile(), now=NOW)
    assert [(link.login, link.synced_at) for link in github_svc.links(db)] == [
        (LOGIN, NOW), (WORK_LOGIN, NOW),
    ]


def test_signing_in_again_as_an_account_keeps_it(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    link = connected(db)
    github_svc.sync(db, account, now=NOW)
    link.signed_out, link.sync_error = True, "gone"
    # A rename on GitHub, then connecting it again with a token.
    again = connected(db, {**ME, "login": "oscar-renamed"}, GitHubSource.token)
    assert again is link and len(github_svc.links(db)) == 1
    assert (link.login, link.source, link.signed_out, link.sync_error) == (
        "oscar-renamed", GitHubSource.token, False, "",
    )
    assert len(link.repositories) == 1
    # One connected before its id was kept is found by its login, then learns it.
    link.user_id = None
    assert connected(db, {**ME, "login": "Oscar-Renamed"}) is link and link.user_id == USER_ID


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


@pytest.mark.parametrize(
    ("location", "full_name"),
    [
        ("https://github.com/Acme-Labs/pylon-engine", "acme-labs/pylon-engine"),
        ("https://github.com/me/app.git", "me/app"),
        ("https://github.com/me/app/", "me/app"),
        ("git@github.com:me/my.app.git", "me/my.app"),
        ("github.com/me/app", "me/app"),
        (r"C:\code\app", None),
        ("https://gitlab.com/me/app", None),
        ("https://github.com/me", None),
    ],
)
def test_a_repository_on_github_is_known_by_its_url(location, full_name) -> None:
    assert github_svc.full_name_of(location) == full_name


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
    assert empty == {"connected": False, "accounts": [], "repositories": []}
    github.repos = [
        repo_payload(1, "everyday-app", open_issues_count=3),
        repo_payload(2, "pylon-legacy", archived=True, language="Java"),
    ]
    account = fake_account(tmp_path, github, FakeCli())
    with app_db() as db:
        connected(db)
        github_svc.sync(db, account, now=NOW)
        db.commit()
    async with Client(mcp) as client:
        got = (await client.call_tool("list_repositories", {})).data
        every = (await client.call_tool("list_repositories", {"include_archived": True})).data
        java = (await client.call_tool(
            "list_repositories", {"query": "java", "include_archived": True}
        )).data
    assert got["connected"] is True
    assert got["accounts"] == [{"login": LOGIN, "connected": True, "synced_at": "2026-10-04T11:00"}]
    assert got["repositories"] == [{
        "full_name": f"{LOGIN}/everyday-app", "description": "What everyday-app is",
        "language": "Python", "private": True, "fork": False, "archived": False,
        "default_branch": "main", "url": f"https://github.com/{LOGIN}/everyday-app",
        "open_issues_and_pulls": 3, "pushed_at": got["repositories"][0]["pushed_at"],
        "accounts": [LOGIN],
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
    assert 'hx-trigger="load"' in page  # nothing connected: asked at once
    assert "Find a repository" not in page  # nothing to find yet

    offer = client.get("/ui/github/cli").text
    assert f"Signed in as {LOGIN}" in offer and 'hx-post="/ui/github/connect/cli"' in offer
    assert f'hx-vals=\'{{"login": "{LOGIN}"}}\'' in offer

    done = client.post("/ui/github/connect/cli", data={"login": LOGIN})
    assert done.status_code == 204 and done.headers["HX-Refresh"] == "true"
    github_svc.syncing.wait(5)
    db.expire_all()
    (link,) = github_svc.links(db)
    assert (link.login, link.user_id, link.source, link.sync_error) == (
        LOGIN, USER_ID, GitHubSource.cli, "",
    )
    assert not account.has_token(link.id)

    page = client.get("/repositories").text
    for words in ("Find a repository", "everyday-app", "What everyday-app is", "Public",
                  "acme-labs/", "Fork", "Archived", "pylon-legacy",
                  ">GitHub CLI</span>", "Sync now", "Disconnect", "Add another account"):
        assert words in page, words
    assert 'href="https://github.com/oscartoromal-ai/everyday-app" target="_blank"' in page
    assert "Connect GitHub" not in page
    # Adding another is folded away, gh asked only as it opens.
    assert "<details class=\"github-add\">" in page
    assert 'hx-trigger="toggle once from:closest details"' in page

    found = client.get("/ui/repositories/list", params={"q": "everyday"}).text
    assert "everyday-app" in found and "agent-conductor" not in found
    assert "No repository holds" in client.get("/ui/repositories/list", params={"q": "zz"}).text


def test_adding_a_second_account_from_the_cli(page_client, db, github) -> None:
    client, account, cli = page_client
    cli.accounts[WORK_LOGIN] = WORK_TOKEN
    github.work_repos = [repo_payload(9, "roadmaps", owner=WORK_LOGIN)]
    client.post("/ui/github/connect/cli", data={"login": LOGIN})
    github_svc.syncing.wait(5)

    # Only the one not connected yet is offered.
    offer = client.get("/ui/github/cli").text
    assert f"Signed in as {WORK_LOGIN}" in offer and f"Signed in as {LOGIN}" not in offer
    client.post("/ui/github/connect/cli", data={"login": WORK_LOGIN})
    github_svc.syncing.wait(5)

    page = client.get("/repositories").text
    assert ">Accounts</span>" in page and WORK_LOGIN in page and WORK_NAME in page
    # His first account's repositories go by their names, the other's by owner too.
    assert '<span class="repo-owner">oscar-work/</span>roadmaps' in page
    assert "Every account it is signed in to is connected" in client.get("/ui/github/cli").text

    db.expire_all()
    work = [link for link in github_svc.links(db) if link.login == WORK_LOGIN][0]
    gone = client.post(f"/ui/github/{work.id}/disconnect")
    assert gone.headers["HX-Refresh"] == "true"
    db.expire_all()
    assert [link.login for link in github_svc.links(db)] == [LOGIN]
    assert [r.name for r in github_svc.repositories(db)] == ["everyday-app"]
    assert client.post(f"/ui/github/{work.id}/disconnect").status_code == 404


def test_the_cli_signed_out_or_missing(page_client, tmp_path, github) -> None:
    client, account, cli = page_client
    cli.accounts.clear()
    offer = client.get("/ui/github/cli").text
    assert "Not signed in" in offer and "gh auth login" in offer and "Check again" in offer
    refused = client.post("/ui/github/connect/cli", data={"login": LOGIN})
    assert refused.status_code == 200 and f"not signed in as {LOGIN}" in refused.text

    from app.ui.repositories import get_github

    missing = fake_account(tmp_path, github, None, installed=False)
    client.app.dependency_overrides[get_github] = lambda: missing
    assert "winget install GitHub.cli" in client.get("/ui/github/cli").text

    github.fail = httpx.ConnectError("offline")
    client.app.dependency_overrides[get_github] = lambda: account
    cli.accounts[LOGIN] = CLI_TOKEN
    assert "Could not reach GitHub" in client.post(
        "/ui/github/connect/cli", data={"login": LOGIN}
    ).text


def test_connecting_with_a_token_then_disconnecting(page_client, db) -> None:
    client, account, _ = page_client
    wrong = client.post("/ui/github/connect/token", data={"token": "ghp_wrong"})
    assert "did not accept that token" in wrong.text and 'name="token"' in wrong.text

    done = client.post("/ui/github/connect/token", data={"token": PASTED_TOKEN})
    assert done.status_code == 204
    github_svc.syncing.wait(5)
    db.expire_all()
    (link,) = github_svc.links(db)
    assert account.token_file(link.id).read_text(encoding="utf-8") == PASTED_TOKEN
    page = client.get("/repositories").text
    assert ">Token</span>" in page and "everyday-app" in page

    gone = client.post(f"/ui/github/{link.id}/disconnect")
    assert gone.headers["HX-Refresh"] == "true" and not account.has_token(link.id)
    db.expire_all()
    assert github_svc.links(db) == [] and github_svc.repositories(db) == []
    assert "Connect GitHub" in client.get("/repositories").text


def test_signed_out_by_github_asks_to_connect_again(page_client, db) -> None:
    client, account, cli = page_client
    connected(db)
    github_svc.sync(db, account, now=NOW)
    cli.accounts.clear()
    github_svc.sync(db, account)
    page = client.get("/repositories").text
    assert "Signed out" in page and "gh auth login" in page
    assert "<details class=\"github-add\" open>" in page and 'hx-trigger="load"' in page
    assert "everyday-app" in page  # the list kept stays in sight


def test_syncing_from_the_page(page_client, db) -> None:
    client, account, _ = page_client
    connected(db)
    db.commit()
    synced = client.post("/ui/github/sync")
    assert "Syncing" in synced.text or "today" in synced.text
    github_svc.syncing.wait(5)
    polled = client.get("/ui/github/account", headers={"HX-Trigger": "github-account"})
    assert polled.headers["HX-Trigger"] == "github:synced"
    assert "Last sync failed" not in polled.text
