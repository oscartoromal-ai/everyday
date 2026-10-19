"""Health > Garmin: reading Garmin's payloads, the sync's window, what is
kept, what Claude reads, and the page, with a stand-in for Garmin Connect
(garmin_fake.py). The real account's error handling is tested against a
stand-in for python-garminconnect's client, and signing in with a kept
token against the real library, its network a stand-in."""

from datetime import date, datetime, timedelta

import pytest
from fastmcp import Client
from garmin_fake import NAME, PASSWORD, FakeGarmin, activity_payload, at, day_payload
from garminconnect import GarminConnectAuthenticationError, GarminConnectConnectionError

from app.mcp.server import mcp
from app.services import garmin as garmin_svc
from app.services import health as health_svc
from app.services.nutrition_agent import AgentRequest, build_prompt
from app.sources import garmin as garmin_source
from app.sources.garmin import (
    GarminConnect,
    GarminSignedOut,
    GarminSignInFailed,
    GarminUnavailable,
)

TODAY = date(2026, 9, 30)
NOW = at(TODAY, 20, 41)


def connected(db, fake: FakeGarmin | None = None) -> FakeGarmin:  # noqa: ANN001
    fake = fake or FakeGarmin()
    fake.token = True
    garmin_svc.connect(db, NAME)
    return fake


# ---- Garmin's payloads ----


def test_a_day_reads_as_garmin_sums_it() -> None:
    figures = garmin_svc.day_figures(day_payload(TODAY))
    assert figures == {
        "steps": 8412, "step_goal": 10000, "distance_m": 6250.0, "total_kcal": 2640,
        "active_kcal": 612, "moderate_minutes": 22, "vigorous_minutes": 6, "resting_hr": 52,
        "stress_avg": 28, "body_battery_high": 88, "body_battery_low": 21,
        "sleep_seconds": 27120, "deep_seconds": 4800, "light_seconds": 15000,
        "rem_seconds": 6000, "awake_seconds": 720, "sleep_score": 81, "sleep_quality": "GOOD",
        "hrv_ms": 48, "hrv_week_ms": 50, "hrv_status": "BALANCED",
        "readiness": 72, "readiness_level": "MODERATE",
    }
    # Readiness as a day's snapshots: the first, the morning's.
    raw = {"readiness": [{"score": 64, "level": "MODERATE"}, {"score": 40, "level": "LOW"}]}
    assert garmin_svc.day_figures(raw) == {"readiness": 64, "readiness_level": "MODERATE"}
    # Garmin's "not enough data" stress is no figure.
    raw = {"summary": {"averageStressLevel": -1}}
    assert garmin_svc.day_figures(raw)["stress_avg"] is None


def test_a_part_that_failed_leaves_what_was_kept(db) -> None:
    garmin_svc.keep_day(db, TODAY, day_payload(TODAY), NOW)
    # This time the sleep request failed (missing), and the night had no HRV (None).
    raw = day_payload(TODAY, steps=9000)
    del raw["sleep"]
    raw["hrv"] = None
    row = garmin_svc.keep_day(db, TODAY, raw, NOW)
    assert (row.steps, row.sleep_seconds, row.hrv_ms) == (9000, 27120, None)


def test_an_activity_needs_an_id_and_a_start() -> None:
    fields = garmin_svc.activity_fields(activity_payload(1, at(TODAY, 7, 12)))
    assert fields == {
        "garmin_id": 1, "day": TODAY, "start": at(TODAY, 7, 12), "name": "Morning Run",
        "kind": "running", "duration_s": 2712, "distance_m": 8104.2, "kcal": 520,
        "avg_hr": 148, "max_hr": 171,
    }
    assert garmin_svc.activity_fields({"activityId": 2}) is None
    assert garmin_svc.activity_fields({"startTimeLocal": "2026-09-30 07:00:00"}) is None


# ---- syncing ----


def test_the_first_sync_reaches_back_and_later_ones_catch_up(db) -> None:
    fake = connected(db)
    fake.days = {TODAY - timedelta(days=i): day_payload(TODAY) for i in range(40)}
    assert garmin_svc.sync(db, fake, TODAY, backfill_days=30, now=NOW) == (
        TODAY - timedelta(days=29), TODAY,
    )
    assert len(fake.fetched) == 30 and len(garmin_svc.days(db, date.min, date.max)) == 30
    link = garmin_svc.link(db)
    assert (link.synced_at, link.sync_error) == (NOW, "")

    # Later the same day: yesterday (to settle) and today.
    fake.fetched.clear()
    garmin_svc.sync(db, fake, TODAY, backfill_days=30, now=NOW + timedelta(minutes=30))
    assert fake.fetched == [TODAY - timedelta(days=1), TODAY]

    # Three days on, the app off meanwhile: from the day before the last sync.
    fake.fetched.clear()
    later = TODAY + timedelta(days=3)
    garmin_svc.sync(db, fake, later, backfill_days=30, now=at(later, 9))
    assert fake.fetched == [TODAY - timedelta(days=1) + timedelta(days=i) for i in range(5)]

    # Months on, never further back than the backfill.
    start, _ = garmin_svc.window(db, TODAY + timedelta(days=90), 30)
    assert start == TODAY + timedelta(days=61)


def test_the_windows_activities_are_as_garmin_has_them(db) -> None:
    fake = connected(db)
    fake.found = [
        activity_payload(1, at(TODAY, 7, 12)),
        activity_payload(
            2, at(TODAY - timedelta(days=1), 18), name="Strength", kind="strength_training"
        ),
    ]
    garmin_svc.sync(db, fake, TODAY, backfill_days=2, now=NOW)
    assert [a.name for a in garmin_svc.activities(db, TODAY - timedelta(days=1), TODAY)] == [
        "Strength", "Morning Run",
    ]
    # Renamed on Garmin, one deleted there: so here too.
    fake.found = [activity_payload(1, at(TODAY, 7, 12), name="Easy run")]
    garmin_svc.sync(db, fake, TODAY, backfill_days=2, now=NOW)
    assert [a.name for a in garmin_svc.activities(db, date.min, date.max)] == ["Easy run"]


def test_a_failed_sync_says_why_and_keeps_what_it_got(db) -> None:
    fake = connected(db)
    fake.days = {TODAY - timedelta(days=1): day_payload(TODAY - timedelta(days=1))}
    fake.unavailable_on = TODAY
    with pytest.raises(GarminUnavailable):
        garmin_svc.sync(db, fake, TODAY, backfill_days=2, now=NOW)
    link = garmin_svc.link(db)
    assert link.synced_at is None and "Could not reach Garmin" in link.sync_error
    assert garmin_svc.day(db, TODAY - timedelta(days=1)).steps == 8412
    # The next one goes well, and says so.
    fake.unavailable_on = None
    garmin_svc.sync(db, fake, TODAY, backfill_days=2, now=NOW)
    assert (link.synced_at, link.sync_error) == (NOW, "")


def test_the_app_writes_on_while_garmin_is_asked(app_db, tmp_path) -> None:
    # A sync waits on Garmin day after day (a first one, 30 days), and the
    # app's other writers (a save, Claude's tools, a job) must not wait on it.
    import sqlite3

    with app_db() as db:
        fake = connected(db)
        db.commit()
    writes: list[bool] = []

    class Slow(FakeGarmin):
        def fetch_day(self, day: date):  # noqa: ANN201
            other = sqlite3.connect(tmp_path / "app.db", timeout=0.2)
            try:
                other.execute("INSERT INTO settings (key, value) VALUES (?, '1')", (str(day),))
                other.commit()
                writes.append(True)
            except sqlite3.OperationalError:  # database is locked
                writes.append(False)
            finally:
                other.close()
            return super().fetch_day(day)

    slow = Slow()
    slow.token, slow.days = True, fake.days
    garmin_svc.run_sync(app_db, slow, TODAY, backfill_days=3)
    assert writes == [True, True, True]
    with app_db() as db:
        assert garmin_svc.link(db).synced_at is not None


def test_one_sync_at_a_time(db) -> None:
    import threading

    release = threading.Event()
    ran: list[str] = []
    assert garmin_svc.syncing.start(lambda: (release.wait(5), ran.append("first")))
    assert garmin_svc.syncing.running
    assert not garmin_svc.syncing.start(lambda: ran.append("second"))
    assert not garmin_svc.syncing.run_here(lambda: ran.append("third"))
    release.set()
    garmin_svc.syncing.wait(5)
    assert ran == ["first"] and not garmin_svc.syncing.running


# ---- what follows ----


def test_measured_energy_is_his_recent_full_days_worn(db) -> None:
    for i in range(1, 7):
        garmin_svc.keep_day(db, TODAY - timedelta(days=i), day_payload(TODAY, total_kcal=2600), NOW)
    # Six days worn: not enough yet. A day barely worn, and today, do not count.
    garmin_svc.keep_day(db, TODAY - timedelta(days=7), day_payload(TODAY, steps=300), NOW)
    garmin_svc.keep_day(db, TODAY, day_payload(TODAY, total_kcal=900), NOW)
    assert garmin_svc.measured_energy(db, TODAY) is None
    garmin_svc.keep_day(db, TODAY - timedelta(days=8), day_payload(TODAY, total_kcal=2740), NOW)
    assert garmin_svc.measured_energy(db, TODAY) == {"kcal": 2620, "days": 7}
    me = health_svc.context(db, TODAY)
    assert (me["measured_energy_kcal"], me["measured_energy_days"]) == (2620, 7)


def test_claude_reads_the_days_and_their_activities(db) -> None:
    garmin_svc.keep_day(db, TODAY, day_payload(TODAY), NOW)
    garmin_svc.keep_activities(db, TODAY, TODAY, [activity_payload(1, at(TODAY, 7, 12))])
    (report,) = garmin_svc.report(db, TODAY - timedelta(days=6), TODAY)
    assert report["day"] == "2026-09-30" and report["total_kcal"] == 2640
    assert report["activities"] == [{
        "start": "2026-09-30T07:12", "name": "Morning Run", "kind": "running",
        "duration_min": 45, "distance_km": 8.1, "kcal": 520, "avg_hr": 148, "max_hr": 171,
    }]
    prompt = build_prompt(AgentRequest(
        day=TODAY, now=NOW, message="What now?", folder=None, garmin=[report],  # type: ignore[arg-type]
    ))
    assert "What his Garmin watch measured" in prompt and '"total_kcal": 2640' in prompt
    assert "Garmin" not in build_prompt(AgentRequest(day=TODAY, now=NOW, message="Hi", folder=None))  # type: ignore[arg-type]


async def test_get_garmin_over_mcp(app_db, monkeypatch) -> None:
    fake = FakeGarmin()
    monkeypatch.setattr(garmin_source, "account", lambda: fake)
    today = date.today()
    async with Client(mcp) as client:
        empty = (await client.call_tool("get_garmin", {})).data
    assert empty == {"connected": False, "synced_at": None, "days": []}
    with app_db() as db:
        connected(db, fake)
        garmin_svc.sync(db, fake, today, backfill_days=3, now=at(today, 6))
        fake.days[today] = day_payload(today)
        garmin_svc.sync(db, fake, today, backfill_days=3, now=at(today, 7))
        db.commit()
    async with Client(mcp) as client:
        got = (await client.call_tool("get_garmin", {"days": 2})).data
    assert got["connected"] and got["synced_at"] == f"{today.isoformat()}T07:00"
    # Yesterday synced, with nothing in it: left out.
    assert [d["day"] for d in got["days"]] == [today.isoformat()]
    assert got["days"][0]["steps"] == 8412


# ---- the real account, over a stand-in for python-garminconnect ----


class StubClient:
    """python-garminconnect's Garmin, as far as GarminConnect uses it."""

    refuse = False
    needs_code = False
    fail: dict[str, Exception] = {}

    def __init__(self, email=None, password=None, return_on_mfa=False) -> None:  # noqa: ANN001
        self.password = password
        self.client = self
        self.dumped: str | None = None
        self.full_name = self.display_name = None

    def login(self, tokenstore=None):  # noqa: ANN001, ANN201
        if tokenstore is not None:
            if StubClient.refuse:
                raise GarminConnectAuthenticationError("401")
            return None, None
        if self.password != PASSWORD:
            raise GarminConnectAuthenticationError("401 Unauthorized")
        return ("needs_mfa", None) if StubClient.needs_code else (None, None)

    def resume_login(self, state, code):  # noqa: ANN001, ANN201
        if code != "123456":
            raise GarminConnectAuthenticationError("bad code")
        self.full_name = NAME
        return None, None

    def _load_profile_and_settings(self) -> None:
        self.full_name = NAME

    def dump(self, path: str) -> None:
        from pathlib import Path

        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "garmin_tokens.json").write_text("{}")

    def get_user_summary(self, cdate: str) -> dict:
        if "summary" in StubClient.fail:
            raise StubClient.fail["summary"]
        return {"totalSteps": 100}

    def get_sleep_data(self, cdate: str) -> dict:
        if "sleep" in StubClient.fail:
            raise StubClient.fail["sleep"]
        return {"dailySleepDTO": {"sleepTimeSeconds": 60}}

    def get_hrv_data(self, cdate: str) -> None:
        return None

    def get_morning_training_readiness(self, cdate: str) -> None:
        return None

    def get_activities_by_date(self, start: str, end: str) -> list:
        return []


@pytest.fixture
def stub(monkeypatch):  # noqa: ANN201
    monkeypatch.setattr(garmin_source, "Garmin", StubClient)
    StubClient.refuse = StubClient.needs_code = False
    StubClient.fail = {}
    return StubClient


def test_signing_in_keeps_only_the_token(tmp_path, stub) -> None:
    account = GarminConnect(tmp_path / "garmin")
    assert not account.has_token()
    with pytest.raises(GarminSignedOut):
        account.fetch_day(TODAY)
    with pytest.raises(GarminSignInFailed, match="email and password"):
        account.sign_in("oscar@example.com", "wrong")
    assert account.sign_in("oscar@example.com", PASSWORD) == NAME
    assert account.has_token()
    assert [p.name for p in (tmp_path / "garmin").iterdir()] == ["garmin_tokens.json"]
    assert PASSWORD not in (tmp_path / "garmin" / "garmin_tokens.json").read_text()


def test_a_code_finishes_signing_in(tmp_path, stub) -> None:
    stub.needs_code = True
    account = GarminConnect(tmp_path / "garmin")
    assert account.sign_in("oscar@example.com", PASSWORD) is None
    assert account.waiting_for_code() and not account.has_token()
    with pytest.raises(GarminSignInFailed, match="code"):
        account.verify("000000")
    assert account.waiting_for_code()  # a wrong code can be tried again
    assert account.verify(" 123456 ") == NAME
    assert account.has_token() and not account.waiting_for_code()


def test_a_missing_figure_never_stops_a_day(tmp_path, stub) -> None:
    account = GarminConnect(tmp_path / "garmin")
    account.sign_in("oscar@example.com", PASSWORD)
    stub.fail = {"sleep": GarminConnectConnectionError("500")}
    raw = account.fetch_day(TODAY)
    # The sleep that failed is missing; the night with no HRV says None.
    assert raw == {"summary": {"totalSteps": 100}, "hrv": None, "readiness": None}


def test_a_refused_token_signs_out(tmp_path, stub) -> None:
    account = GarminConnect(tmp_path / "garmin")
    account.sign_in("oscar@example.com", PASSWORD)
    # A new process: the token read from its file, and Garmin refuses it.
    account = GarminConnect(tmp_path / "garmin")
    stub.refuse = True
    with pytest.raises(GarminSignedOut):
        account.fetch_day(TODAY)
    assert not account.has_token()


def test_garmin_turning_requests_away_is_said_so(tmp_path, stub) -> None:
    from garminconnect import GarminConnectTooManyRequestsError

    account = GarminConnect(tmp_path / "garmin")
    account.sign_in("oscar@example.com", PASSWORD)
    stub.fail = {"summary": GarminConnectTooManyRequestsError("429")}
    with pytest.raises(GarminUnavailable, match="Wait a few minutes"):
        account.fetch_day(TODAY)
    assert account.has_token()  # busy, not signed out


# ---- the real python-garminconnect, its network a stand-in ----


@pytest.fixture
def kept_token(tmp_path, monkeypatch):  # noqa: ANN201
    """A token kept from an earlier sign-in, read by the real library in a
    new process; its retries' pauses skipped."""
    import json

    folder = tmp_path / "garmin"
    folder.mkdir()
    (folder / "garmin_tokens.json").write_text(
        json.dumps({"di_token": "access", "di_refresh_token": "refresh", "di_client_id": "app"})
    )
    monkeypatch.setattr("garminconnect.time.sleep", lambda seconds: None)
    return GarminConnect(folder)


def _network(monkeypatch, answer) -> None:  # noqa: ANN001
    """Every request the library makes: raises `answer`, or answers its status."""
    import requests

    def request(self, method, url, **kwargs):  # noqa: ANN001, ANN202
        if isinstance(answer, Exception):
            raise answer
        response = requests.Response()
        response.status_code, response.url, response._content = answer, url, b"{}"
        return response

    monkeypatch.setattr(requests.Session, "request", request)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("ConnectionError", id="no connection"),
        pytest.param("Timeout", id="timed out"),
        pytest.param(503, id="garmin down"),
    ],
)
def test_garmin_out_of_reach_keeps_the_token(kept_token, monkeypatch, answer) -> None:
    import requests

    _network(monkeypatch, getattr(requests, answer)("blip") if isinstance(answer, str) else answer)
    with pytest.raises(GarminUnavailable, match="Could not reach"):
        kept_token.fetch_day(TODAY)
    assert kept_token.has_token()  # the next sync signs in with it


def test_a_token_garmin_refuses_still_signs_out(kept_token, monkeypatch) -> None:
    _network(monkeypatch, 401)
    with pytest.raises(GarminSignedOut):
        kept_token.fetch_day(TODAY)
    assert not kept_token.has_token()


# ---- the page ----


@pytest.fixture
def garmin_client(client):  # noqa: ANN201
    from app.ui.garmin import get_garmin

    fake = FakeGarmin(code="123456")
    client.app.dependency_overrides[get_garmin] = lambda: fake
    yield client, fake
    garmin_svc.syncing.wait(5)


def test_connecting_with_a_code_then_syncing(garmin_client, db) -> None:
    client, fake = garmin_client
    today = date.today()
    fake.days[today] = day_payload(today)
    fake.found = [activity_payload(1, datetime.combine(today, datetime.min.time()).replace(hour=7))]

    page = client.get("/garmin").text
    assert "Connect Garmin" in page and 'name="password"' in page and 'id="garmin-day"' not in page

    email = "oscar@example.com"
    refused = client.post("/ui/garmin/connect", data={"email": email, "password": "no"})
    assert "did not accept that email and password" in refused.text
    assert 'value="oscar@example.com"' in refused.text  # kept to try again

    asked = client.post("/ui/garmin/connect", data={"email": email, "password": PASSWORD})
    assert 'name="code"' in asked.text and "sent you a code" in asked.text
    wrong = client.post("/ui/garmin/verify", data={"code": "1"})
    assert "did not accept that code" in wrong.text and 'name="code"' in wrong.text

    done = client.post("/ui/garmin/verify", data={"code": "123456"})
    assert done.status_code == 204 and done.headers["HX-Refresh"] == "true"
    garmin_svc.syncing.wait(5)
    db.expire_all()
    assert garmin_svc.link(db).full_name == NAME and garmin_svc.link(db).synced_at

    page = client.get("/garmin").text
    for words in ("8,412", "of 10,000", "2,640 kcal", "612 active", "52 bpm", "7 h 32 min",
                  "score 81 · Good", "Deep 1 h 20 min", "48 ms", "Balanced", "Morning Run",
                  "45 min · 8.1 km · 520 kcal · average 148 bpm", "Last 14 days", NAME):
        assert words in page, words


def test_a_day_with_nothing_and_disconnecting(garmin_client, db) -> None:
    client, fake = garmin_client
    fake.token = True
    garmin_svc.connect(db, NAME)
    db.commit()
    yesterday = date.today() - timedelta(days=1)
    assert "Nothing synced for this day" in client.get(f"/garmin/{yesterday.isoformat()}").text
    assert client.get(f"/garmin/{date.today().isoformat()}").status_code == 200

    synced = client.post("/ui/garmin/sync")
    assert "Syncing" in synced.text or "Synced" in synced.text
    garmin_svc.syncing.wait(5)

    gone = client.post("/ui/garmin/disconnect")
    assert gone.headers["HX-Refresh"] == "true" and not fake.token
    db.expire_all()
    assert garmin_svc.link(db) is None
    assert "Connect Garmin" in client.get("/garmin").text


def test_signed_out_by_garmin_asks_to_sign_in_again(garmin_client, db) -> None:
    client, fake = garmin_client
    garmin_svc.connect(db, NAME)  # linked, but the token is gone
    garmin_svc.keep_day(db, date.today(), day_payload(date.today()), NOW)
    db.commit()
    page = client.get("/garmin").text
    assert "Garmin signed you out" in page and 'name="password"' in page
    assert "8,412" in page  # what was synced stays
