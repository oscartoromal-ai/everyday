"""Garmin Connect, through python-garminconnect: signing in, and fetching a
day's figures and the activities of a span of days, as Garmin returns them.

Garmin has no API for individuals, so this signs in as Garmin's own mobile
app does. The password is used once, to sign in; what is kept is Garmin's
token, in `token_dir` (git-ignored local/), which the library refreshes on
its own for as long as Garmin honours it. When it stops (Garmin signed him
out), fetching raises GarminSignedOut and Oscar connects again.

Only I/O lives here: services/garmin.py reads what comes back, and tests
stand in a fake for this class.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from garminconnect.exceptions import GarminConnectNotFoundError

log = logging.getLogger(__name__)

TOKEN_FILE = "garmin_tokens.json"
# How long Garmin's emailed or texted code is waited for.
CODE_WAIT_SECONDS = 15 * 60
# An optional request that failed, unlike None: Garmin had nothing.
FAILED = object()


class GarminError(Exception):
    """Garmin could not do what was asked; the message says why, to Oscar."""


class GarminSignInFailed(GarminError):
    """Garmin refused the email and password, or the code."""


class GarminSignedOut(GarminError):
    """No token, or Garmin no longer accepts it: connect again."""


class GarminUnavailable(GarminError):
    """Garmin could not be reached, or is turning requests away: try later."""


def _unavailable(exc: Exception) -> GarminUnavailable:
    if isinstance(exc, GarminConnectTooManyRequestsError):
        return GarminUnavailable(
            "Garmin is turning requests away for now. Wait a few minutes and try again."
        )
    return GarminUnavailable("Could not reach Garmin Connect. Try again in a moment.")


class GarminConnect:
    """Oscar's Garmin Connect account, signed in through its token.

    One per process: it keeps the signed-in client between syncs, and a
    sign-in waiting on Garmin's code between the two requests that make it.
    """

    def __init__(self, token_dir: Path) -> None:
        self.token_dir = token_dir
        self._lock = threading.RLock()
        self._client: Garmin | None = None
        self._pending: Garmin | None = None
        self._pending_since = 0.0

    @property
    def token_file(self) -> Path:
        return self.token_dir / TOKEN_FILE

    def has_token(self) -> bool:
        return self.token_file.is_file()

    # ---- signing in ----

    def sign_in(self, email: str, password: str) -> str | None:
        """Sign in; returns his name on Garmin, or None when Garmin has sent
        a code to finish with (verify)."""
        client = Garmin(email.strip(), password, return_on_mfa=True)
        with self._lock:
            self._pending = None
            try:
                needs_code, _ = client.login()
            except GarminConnectAuthenticationError as exc:
                log.info("Garmin sign-in refused: %s", exc)
                raise GarminSignInFailed(
                    "Garmin did not accept that email and password."
                ) from exc
            except (GarminConnectTooManyRequestsError, GarminConnectConnectionError) as exc:
                log.warning("Garmin sign-in failed: %s", exc)
                raise _unavailable(exc) from exc
            if needs_code == "needs_mfa":
                self._pending, self._pending_since = client, time.monotonic()
                return None
            return self._keep(client)

    def waiting_for_code(self) -> bool:
        with self._lock:
            if self._pending and time.monotonic() - self._pending_since > CODE_WAIT_SECONDS:
                self._pending = None
            return self._pending is not None

    def verify(self, code: str) -> str:
        """Finish a sign-in with Garmin's code; returns his name on Garmin.
        A wrong code can be tried again."""
        with self._lock:
            if not self.waiting_for_code():
                raise GarminSignInFailed("That sign-in has expired. Start again.")
            client = self._pending
            try:
                client.resume_login(None, code.strip())
            except GarminConnectAuthenticationError as exc:
                log.info("Garmin code refused: %s", exc)
                raise GarminSignInFailed("Garmin did not accept that code.") from exc
            except (GarminConnectTooManyRequestsError, GarminConnectConnectionError) as exc:
                log.warning("Garmin code check failed: %s", exc)
                raise _unavailable(exc) from exc
            self._pending = None
            return self._keep(client)

    def cancel(self) -> None:
        with self._lock:
            self._pending = None

    def _keep(self, client: Garmin) -> str:
        """A signed-in client: its token saved (and kept fresh there as the
        library refreshes it), its profile read, it used from now on."""
        path = str(self.token_dir)
        client.client.dump(path)
        client.client._tokenstore_path = path
        try:
            if not getattr(client, "display_name", None):
                client._load_profile_and_settings()
        except GarminConnectAuthenticationError as exc:
            raise GarminSignInFailed("Garmin signed in, then refused the session.") from exc
        except GarminConnectConnectionError as exc:
            raise _unavailable(exc) from exc
        self._client = client
        return client.full_name or client.display_name or ""

    def forget(self) -> None:
        """Sign out here: the token deleted. Garmin keeps his data."""
        with self._lock:
            self._client = self._pending = None
            self.token_file.unlink(missing_ok=True)

    # ---- fetching ----

    def _signed_in(self) -> Garmin:
        if self._client is not None:
            return self._client
        if not self.has_token():
            raise GarminSignedOut("Not connected to Garmin.")
        client = Garmin()
        try:
            client.login(str(self.token_dir))
        except GarminConnectAuthenticationError as exc:
            log.warning("Garmin token refused: %s", exc)
            self.forget()  # it will not be honoured again
            raise GarminSignedOut("Garmin signed you out. Connect again.") from exc
        except (GarminConnectTooManyRequestsError, GarminConnectConnectionError) as exc:
            raise _unavailable(exc) from exc
        self._client = client
        return client

    def _call(self, what: str, fetch: Any, *args: Any, optional: bool = False) -> Any:
        """One request. An optional one that fails for any reason but auth or
        rate limiting comes back FAILED, so one missing figure never stops a
        day; everything else raises. Nothing there (404) is None."""
        client = self._signed_in()
        try:
            return fetch(client, *args)
        except GarminConnectAuthenticationError as exc:
            log.warning("Garmin refused the session: %s", exc)
            self.forget()
            raise GarminSignedOut("Garmin signed you out. Connect again.") from exc
        except GarminConnectTooManyRequestsError as exc:
            raise _unavailable(exc) from exc
        except GarminConnectNotFoundError:
            return None
        except GarminConnectConnectionError as exc:
            if optional:
                log.info("Garmin %s not fetched: %s", what, exc)
                return FAILED
            raise _unavailable(exc) from exc

    def fetch_day(self, day: date) -> dict[str, Any]:
        """The day's raw figures: its summary, the sleep that ended that
        morning, that night's HRV, and training readiness. A part Garmin
        could not give is missing, not empty, so what was synced before stays."""
        with self._lock:
            cdate = day.isoformat()
            parts = {
                # A day Garmin has nothing for fails as "No data received".
                "summary": Garmin.get_user_summary,
                "sleep": Garmin.get_sleep_data,
                "hrv": Garmin.get_hrv_data,
                "readiness": Garmin.get_morning_training_readiness,
            }
            raw: dict[str, Any] = {}
            for name, fetch in parts.items():
                value = self._call(name, fetch, cdate, optional=True)
                if value is not FAILED:
                    raw[name] = value
            return raw

    def fetch_activities(self, start: date, end: date) -> list[dict[str, Any]]:
        """The activities started from `start` to `end`, both included."""
        with self._lock:
            found = self._call(
                "activities", Garmin.get_activities_by_date, start.isoformat(), end.isoformat()
            )
            return list(found or [])


@lru_cache
def account() -> GarminConnect:
    """The process's Garmin Connect account, its token where config says."""
    from app.config import get_settings

    return GarminConnect(get_settings().garmin_token_dir)
