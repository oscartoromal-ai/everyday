"""A stand-in for Garmin Connect (sources/garmin.py's GarminConnect), and
payloads shaped as Garmin's own, for the Garmin tests."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from app.sources.garmin import GarminSignInFailed, GarminUnavailable

PASSWORD = "right"
NAME = "Oscar Toro"


def day_payload(
    day: date, *, steps: int = 8412, total_kcal: int = 2640, active_kcal: int = 612,
    sleep_seconds: int = 27120, hrv: int | None = 48, readiness: int | None = 72,
) -> dict[str, Any]:
    """A day's raw parts, as GarminConnect.fetch_day returns them."""
    return {
        "summary": {
            "calendarDate": day.isoformat(),
            "totalSteps": steps,
            "dailyStepGoal": 10000,
            "totalDistanceMeters": 6250.0,
            "totalKilocalories": float(total_kcal),
            "activeKilocalories": float(active_kcal),
            "bmrKilocalories": float(total_kcal - active_kcal),
            "moderateIntensityMinutes": 22,
            "vigorousIntensityMinutes": 6,
            "restingHeartRate": 52,
            "averageStressLevel": 28,
            "bodyBatteryHighestValue": 88,
            "bodyBatteryLowestValue": 21,
        },
        "sleep": {
            "dailySleepDTO": {
                "calendarDate": day.isoformat(),
                "sleepTimeSeconds": sleep_seconds,
                "deepSleepSeconds": 4800,
                "lightSleepSeconds": 15000,
                "remSleepSeconds": 6000,
                "awakeSleepSeconds": 720,
                "sleepScores": {"overall": {"value": 81, "qualifierKey": "GOOD"}},
            },
        },
        "hrv": {
            "hrvSummary": {
                "calendarDate": day.isoformat(), "lastNightAvg": hrv, "weeklyAvg": 50,
                "status": "BALANCED",
            },
        } if hrv is not None else None,
        "readiness": {"score": readiness, "level": "MODERATE"} if readiness is not None else None,
    }


def activity_payload(
    garmin_id: int, start: datetime, *, name: str = "Morning Run", kind: str = "running",
) -> dict[str, Any]:
    return {
        "activityId": garmin_id,
        "activityName": name,
        "startTimeLocal": start.strftime("%Y-%m-%d %H:%M:%S"),
        "activityType": {"typeId": 1, "typeKey": kind},
        "duration": 2712.4,
        "distance": 8104.2,
        "calories": 520.0,
        "averageHR": 148.0,
        "maxHR": 171.0,
    }


class FakeGarmin:
    """An account that signs in with PASSWORD (then `code`, when set), whose
    days are what `days` and `found` hold."""

    def __init__(self, code: str | None = None) -> None:
        self.code = code
        self.token = False
        self.pending = False
        self.days: dict[date, dict[str, Any]] = {}
        self.found: list[dict[str, Any]] = []
        self.fetched: list[date] = []
        self.unavailable_on: date | None = None

    def has_token(self) -> bool:
        return self.token

    def sign_in(self, email: str, password: str) -> str | None:
        if password != PASSWORD:
            raise GarminSignInFailed("Garmin did not accept that email and password.")
        if self.code:
            self.pending = True
            return None
        self.token = True
        return NAME

    def waiting_for_code(self) -> bool:
        return self.pending

    def verify(self, code: str) -> str:
        if code != self.code:
            raise GarminSignInFailed("Garmin did not accept that code.")
        self.pending, self.token = False, True
        return NAME

    def cancel(self) -> None:
        self.pending = False

    def forget(self) -> None:
        self.token = self.pending = False

    def fetch_day(self, day: date) -> dict[str, Any]:
        self.fetched.append(day)
        if day == self.unavailable_on:
            raise GarminUnavailable("Could not reach Garmin Connect. Try again in a moment.")
        return self.days.get(day, {"summary": None, "sleep": None, "hrv": None, "readiness": None})

    def fetch_activities(self, start: date, end: date) -> list[dict[str, Any]]:
        return [
            a for a in self.found
            if start <= datetime.fromisoformat(a["startTimeLocal"]).date() <= end
        ]


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute))
