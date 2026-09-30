"""Health: Oscar himself, as the context health advice needs (Health > Me).

His profile is one row: height, birth date, sex, how active he is, his goal
and target weight, his dietary pattern, allergies and intolerances, foods he
avoids, and notes. His weight is a log, one entry a day, so its trend is
there too. `context` reads it all with what follows from it: his age, BMI,
and an estimate of the energy he needs a day to keep his weight; and, with
Garmin connected, the energy his watch measured him burning.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityLevel, HealthProfile, Sex, WeightEntry, WeightGoal
from app.services import DomainError
from app.services import garmin as garmin_svc

# Physiological bounds, to catch a slip of the keyboard (178 typed as 1780).
HEIGHT_CM = (50.0, 272.0)
WEIGHT_KG = (20.0, 400.0)

# Mifflin-St Jeor's activity factors, from resting to daily energy.
ACTIVITY_FACTORS = {
    ActivityLevel.sedentary: 1.2,
    ActivityLevel.light: 1.375,
    ActivityLevel.moderate: 1.55,
    ActivityLevel.active: 1.725,
    ActivityLevel.very_active: 1.9,
}
TEXT_FIELDS = ("diet", "allergies", "avoids", "notes")
UNSET = object()


def get_profile(db: Session) -> HealthProfile:
    """The profile, begun empty the first time it is asked for."""
    profile = db.scalars(select(HealthProfile).order_by(HealthProfile.id)).first()
    if profile is None:
        profile = HealthProfile()
        db.add(profile)
        db.flush()
    return profile


def _measure(value: float | None, bounds: tuple[float, float], what: str) -> float | None:
    if value is None:
        return None
    low, high = bounds
    if not low <= value <= high:
        raise DomainError(f"{what} should be between {low:g} and {high:g}")
    return round(value, 1)


def update_profile(
    db: Session,
    *,
    height_cm: Any = UNSET,
    birth_date: Any = UNSET,
    sex: Any = UNSET,
    activity: Any = UNSET,
    goal: Any = UNSET,
    target_weight_kg: Any = UNSET,
    today: date | None = None,
    **text: str,
) -> HealthProfile:
    """Set the fields given (None clears one); text fields by name (diet,
    allergies, avoids, notes)."""
    profile = get_profile(db)
    if height_cm is not UNSET:
        profile.height_cm = _measure(height_cm, HEIGHT_CM, "Height (cm)")
    if birth_date is not UNSET:
        if birth_date is not None and birth_date >= (today or date.today()):
            raise DomainError("A birth date is in the past")
        profile.birth_date = birth_date
    if sex is not UNSET:
        profile.sex = Sex(sex) if sex else None
    if activity is not UNSET:
        profile.activity = ActivityLevel(activity) if activity else None
    if goal is not UNSET:
        profile.goal = WeightGoal(goal) if goal else None
    if target_weight_kg is not UNSET:
        profile.target_weight_kg = _measure(target_weight_kg, WEIGHT_KG, "Target weight (kg)")
    for name, value in text.items():
        if name not in TEXT_FIELDS:
            raise DomainError(f"Unknown field: {name}")
        setattr(profile, name, (value or "").strip())
    db.flush()
    return profile


def log_weight(db: Session, day: date, weight_kg: float) -> WeightEntry:
    """His weight on a day; a second entry that day replaces the first."""
    weight = _measure(weight_kg, WEIGHT_KG, "Weight (kg)")
    entry = db.scalars(select(WeightEntry).where(WeightEntry.day == day)).first()
    if entry is None:
        entry = WeightEntry(day=day, weight_kg=weight)
        db.add(entry)
    else:
        entry.weight_kg = weight
    db.flush()
    return entry


def delete_weight(db: Session, day: date) -> None:
    entry = db.scalars(select(WeightEntry).where(WeightEntry.day == day)).first()
    if entry is not None:
        db.delete(entry)
        db.flush()


def weights(db: Session, limit: int = 30) -> list[WeightEntry]:
    """His latest weigh-ins, newest first."""
    return list(db.scalars(select(WeightEntry).order_by(WeightEntry.day.desc()).limit(limit)))


def age_on(birth_date: date, today: date) -> int:
    before_birthday = (today.month, today.day) < (birth_date.month, birth_date.day)
    return today.year - birth_date.year - before_birthday


def context(db: Session, today: date | None = None) -> dict[str, Any]:
    """Everything Me holds, with what follows from it: age, BMI (from his
    latest weight) and his estimated daily energy to keep his weight
    (Mifflin-St Jeor resting energy times his activity's factor), each None
    until what it needs is there; and the energy his Garmin measured him
    burning a day (the average of his recent full days worn, and how many),
    None without enough of them."""
    today = today or date.today()
    profile = get_profile(db)
    recent = weights(db)
    latest = recent[0] if recent else None
    age = age_on(profile.birth_date, today) if profile.birth_date else None
    weight = latest.weight_kg if latest else None
    bmi = None
    if weight and profile.height_cm:
        bmi = round(weight / (profile.height_cm / 100) ** 2, 1)
    energy = None
    if weight and profile.height_cm and age is not None and profile.sex and profile.activity:
        resting = 10 * weight + 6.25 * profile.height_cm - 5 * age
        resting += 5 if profile.sex == Sex.male else -161
        energy = int(round(resting * ACTIVITY_FACTORS[profile.activity], -1))
    measured = garmin_svc.measured_energy(db, today)
    return {
        "height_cm": profile.height_cm,
        "birth_date": profile.birth_date,
        "age": age,
        "sex": profile.sex.value if profile.sex else None,
        "activity": profile.activity.value if profile.activity else None,
        "goal": profile.goal.value if profile.goal else None,
        "target_weight_kg": profile.target_weight_kg,
        "weight_kg": weight,
        "weighed_on": latest.day if latest else None,
        "weights": [{"day": w.day, "weight_kg": w.weight_kg} for w in recent],
        "bmi": bmi,
        "energy_kcal": energy,
        "measured_energy_kcal": measured["kcal"] if measured else None,
        "measured_energy_days": measured["days"] if measured else None,
        **{name: getattr(profile, name) for name in TEXT_FIELDS},
    }
