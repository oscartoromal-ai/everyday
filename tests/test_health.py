from datetime import date, timedelta

import pytest

from app.services import DomainError
from app.services import health as health_svc

TODAY = date(2026, 9, 28)


def test_what_follows_from_me_waits_for_what_it_needs(db) -> None:
    me = health_svc.context(db, TODAY)
    assert (me["age"], me["bmi"], me["energy_kcal"], me["weight_kg"]) == (None, None, None, None)

    health_svc.update_profile(db, height_cm=180, birth_date=date(1996, 3, 1), today=TODAY)
    health_svc.log_weight(db, TODAY - timedelta(days=7), 82)
    health_svc.log_weight(db, TODAY, 80)
    me = health_svc.context(db, TODAY)
    # Age from the birth date; BMI from the latest weigh-in; no energy until sex and activity.
    assert (me["age"], me["weight_kg"], me["weighed_on"], me["bmi"]) == (30, 80, TODAY, 24.7)
    assert me["energy_kcal"] is None

    # Mifflin-St Jeor: 10 x 80 + 6.25 x 180 - 5 x 30 + 5 = 1780 at rest,
    # x 1.55 for moderate activity = 2759, to the nearest 10.
    health_svc.update_profile(db, sex="male", activity="moderate")
    assert health_svc.context(db, TODAY)["energy_kcal"] == 2760
    health_svc.update_profile(db, sex="female")  # 1780 - 166 = 1614 x 1.55
    assert health_svc.context(db, TODAY)["energy_kcal"] == 2500


def test_a_day_keeps_one_weigh_in_and_the_log_reads_newest_first(db) -> None:
    health_svc.log_weight(db, TODAY - timedelta(days=1), 80.2)
    health_svc.log_weight(db, TODAY, 79.9)
    health_svc.log_weight(db, TODAY, 79.64)  # the day's second replaces its first
    assert [(w.day, w.weight_kg) for w in health_svc.weights(db)] == [
        (TODAY, 79.6), (TODAY - timedelta(days=1), 80.2),
    ]
    health_svc.delete_weight(db, TODAY)
    assert health_svc.context(db, TODAY)["weight_kg"] == 80.2


def test_a_slip_of_the_keyboard_is_refused(db) -> None:
    for wrong in (
        {"height_cm": 1780},
        {"target_weight_kg": 5},
        {"birth_date": TODAY},
        {"sex": "other"},
        {"flavour": "sweet"},
    ):
        with pytest.raises((DomainError, ValueError)):
            health_svc.update_profile(db, today=TODAY, **wrong)
    with pytest.raises(DomainError):
        health_svc.log_weight(db, TODAY, 0.8)
    # Cleared with None; text kept trimmed.
    health_svc.update_profile(db, height_cm=180, diet="  vegetarian ")
    health_svc.update_profile(db, height_cm=None)
    me = health_svc.context(db, TODAY)
    assert (me["height_cm"], me["diet"]) == (None, "vegetarian")
