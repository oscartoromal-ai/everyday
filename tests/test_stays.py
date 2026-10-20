"""Where Oscar stays, day by day: a stay's items (place and accommodation to
begin with), written on Today's stay pane or Calendar's sheet, not in the
day's notes."""

import json
from datetime import date, timedelta

import pytest

from app.services import DomainError, notebook
from app.services import stays as stays_svc

MONDAY = date(2026, 9, 28)


def read(db, day: date) -> list[tuple[str, str, bool]]:  # noqa: ANN001
    return [(i.name, i.value, i.done) for i in stays_svc.items_on(db, day)]


def test_an_item_written_on_a_day_with_none_starts_its_stay(db) -> None:
    # Nothing to write leaves a day with no stay without one.
    assert stays_svc.set_item(db, MONDAY, "place", value="  ") == []
    assert stays_svc.set_item(db, MONDAY, "accommodation", done=False) == []
    # A first stay starts with place and accommodation, written as given.
    stays_svc.set_item(db, MONDAY, "place", value=" Leiden,   Netherlands ")
    assert read(db, MONDAY) == [
        ("place", "Leiden, Netherlands", False),
        ("accommodation", "", False),
    ]
    # An item is found by its name, whatever its case; one the stay lacks joins its end.
    stays_svc.set_item(db, MONDAY, "Accommodation", value="Canal house")
    stays_svc.set_item(db, MONDAY, "accommodation", done=True)
    stays_svc.set_item(db, MONDAY, "ferry", value="F4")
    assert read(db, MONDAY) == [
        ("place", "Leiden, Netherlands", False),
        ("accommodation", "Canal house", True),
        ("ferry", "F4", False),
    ]
    # The next day's starts with the items this one has, empty.
    stays_svc.set_item(db, MONDAY + timedelta(days=1), "place", value="Delft")
    assert read(db, MONDAY + timedelta(days=1)) == [
        ("place", "Delft", False),
        ("accommodation", "", False),
        ("ferry", "", False),
    ]
    # It is not the day's notes'.
    assert notebook.get_page(db, MONDAY) is None
    with pytest.raises(DomainError):
        stays_svc.set_item(db, MONDAY, "  ", value="x")


def test_an_item_is_added_and_taken_away(db) -> None:
    # Added on a day with none: the items a stay starts with, then it.
    stays_svc.add_item(db, MONDAY, "parking ")
    assert read(db, MONDAY) == [
        ("place", "", False),
        ("accommodation", "", False),
        ("parking", "", False),
    ]
    stays_svc.add_item(db, MONDAY, "Parking")  # there already
    assert len(read(db, MONDAY)) == 3
    stays_svc.remove_item(db, MONDAY, "Accommodation")
    stays_svc.set_item(db, MONDAY, "accommodation", value="Hostel")  # back, at the end
    assert read(db, MONDAY) == [
        ("place", "", False),
        ("parking", "", False),
        ("accommodation", "Hostel", False),
    ]
    for name in ("place", "parking", "accommodation"):
        stays_svc.remove_item(db, MONDAY, name)
    assert read(db, MONDAY) == []


def test_the_last_stay_is_taken_again_and_carried_on(db) -> None:
    with pytest.raises(DomainError, match="No stay before"):
        stays_svc.same_as_before(db, MONDAY)
    stays_svc.set_item(db, MONDAY, "place", value="Leiden")
    stays_svc.set_item(db, MONDAY, "accommodation", value="Canal house", done=True)
    # Three days on, the last one before it again, item for item.
    later = MONDAY + timedelta(days=3)
    stays_svc.same_as_before(db, later)
    assert read(db, later) == read(db, MONDAY)
    # Carried on: each day after it up to the one given made the same,
    # whatever it had; what they had is answered, for Undo.
    stays_svc.set_item(db, MONDAY + timedelta(days=2), "place", value="Delft")
    was = stays_svc.fill(db, MONDAY, MONDAY + timedelta(days=2))
    assert {d: [i["value"] for i in items] for d, items in was.items()} == {
        MONDAY + timedelta(days=1): [],
        MONDAY + timedelta(days=2): ["Delft", ""],
    }
    for n in (1, 2, 3):
        assert read(db, MONDAY + timedelta(days=n)) == read(db, MONDAY)
    assert stays_svc.carried_to(db, MONDAY) == later
    # Put back as they were.
    stays_svc.put(db, was)
    assert read(db, MONDAY + timedelta(days=1)) == []
    assert read(db, MONDAY + timedelta(days=2)) == [
        ("place", "Delft", False),
        ("accommodation", "", False),
    ]
    assert stays_svc.carried_to(db, MONDAY) is None
    for until in (MONDAY, MONDAY + timedelta(days=stays_svc.MOST_DAYS + 1)):
        with pytest.raises(DomainError):
            stays_svc.fill(db, MONDAY, until)
    with pytest.raises(DomainError, match="no stay"):
        stays_svc.fill(db, MONDAY + timedelta(days=1), MONDAY + timedelta(days=4))


def test_the_pane_has_the_days_stay_and_what_it_offers(db) -> None:
    # The first ever: no items, those it would start with (accommodation a
    # checkbox), nothing before.
    assert stays_svc.standing(db, MONDAY) == {
        "day": "2026-09-28",
        "items": [],
        "names": ["place", "accommodation"],
        "checks": ["accommodation"],
        "before": None,
        "through": None,
        "values": {"place": [], "accommodation": []},
    }
    stays_svc.set_item(db, MONDAY, "place", value="Leiden")
    stays_svc.set_item(db, MONDAY + timedelta(days=1), "place", value="Delft")
    stays_svc.set_item(db, MONDAY + timedelta(days=2), "place", value="Leiden")
    stays_svc.fill(db, MONDAY + timedelta(days=2), MONDAY + timedelta(days=4))
    pane = stays_svc.standing(db, MONDAY + timedelta(days=6))
    assert pane["items"] == []
    assert pane["before"] == {
        "day": "2026-10-02",
        "items": [
            {"name": "place", "value": "Leiden", "done": False},
            {"name": "accommodation", "value": "", "done": False},
        ],
    }
    # Each item's values written before, the last first, once each.
    assert pane["values"] == {"place": ["Leiden", "Delft"], "accommodation": []}
    assert stays_svc.standing(db, MONDAY + timedelta(days=2))["through"] == "2026-10-02"


def test_the_stay_pane_writes_the_days_stay(client, db) -> None:
    url = f"/ui/stays/{MONDAY.isoformat()}"
    answer = client.post(f"{url}/item", data={"name": "place", "value": "Leiden"})
    assert answer.status_code == 200
    assert answer.json()["stay"]["items"][0] == {"name": "place", "value": "Leiden", "done": False}
    ticked = client.post(f"{url}/item", data={"name": "accommodation", "done": "true"}).json()
    assert ticked["stay"]["items"][1]["done"] is True
    filled = client.post(f"{url}/fill", data={"until": "2026-09-30"}).json()
    assert (filled["days"], filled["was"]) == (2, {"2026-09-29": [], "2026-09-30": []})
    assert filled["stay"]["through"] == "2026-09-30"
    # Undo: the days put back as they were.
    put = client.post(f"{url}/put", data={"stays": json.dumps(filled["was"])})
    assert put.status_code == 200 and put.json()["stay"]["through"] is None
    assert read(db, MONDAY + timedelta(days=1)) == []
    # The next day takes it again; an item is added and taken away.
    tuesday = f"/ui/stays/{(MONDAY + timedelta(days=1)).isoformat()}"
    same = client.post(f"{tuesday}/same").json()["stay"]
    assert [i["value"] for i in same["items"]] == ["Leiden", ""]
    added = client.post(f"{tuesday}/add", data={"name": "parking"}).json()["stay"]
    assert [i["name"] for i in added["items"]] == ["place", "accommodation", "parking"]
    gone = client.post(f"{tuesday}/remove", data={"name": "parking"}).json()["stay"]
    assert [i["name"] for i in gone["items"]] == ["place", "accommodation"]
    # What cannot be written says why.
    assert client.post(f"{url}/fill", data={"until": MONDAY.isoformat()}).status_code == 422
    assert client.post(f"{url}/put", data={"stays": "[1]"}).status_code == 422
    bad = json.dumps({MONDAY.isoformat(): [{"name": "place"}, {"name": "Place"}]})
    assert client.post(f"{url}/put", data={"stays": bad}).status_code == 422


def test_todays_page_has_the_stay_pane(client, db) -> None:
    stays_svc.set_item(db, MONDAY, "place", value="Leiden")
    db.commit()
    page = client.get(f"/day/{MONDAY.isoformat()}").text
    assert 'id="pad-stay" data-pane="stay"' in page
    assert '"value": "Leiden"' in page
    # Not offered in the notes any more.
    assert "[/stay]" not in page and "data-stay-items" not in page
