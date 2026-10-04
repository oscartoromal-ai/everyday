"""A save waiting on SQLite's write lock (held by a sync, a job or Claude's
tools) waits alone: the server answers everything else meanwhile."""

import sqlite3
import threading
import time
from datetime import date

import httpx


def answer_time_while(post, live: str, db_file) -> float:  # noqa: ANN001
    """How long a page takes to answer while `post` waits on SQLite's write
    lock, held by another writer for a second and a half."""
    with httpx.Client(base_url=live, timeout=10) as client:
        client.get("/today")
        client.headers["X-CSRF"] = client.cookies["csrf"]
        other = sqlite3.connect(db_file, isolation_level=None, check_same_thread=False)
        other.execute("BEGIN IMMEDIATE")
        release = threading.Timer(1.5, other.rollback)
        release.start()
        failed: list[BaseException] = []
        waiting = threading.Thread(target=lambda: _record(failed, post, client))
        waiting.start()
        time.sleep(0.3)  # the save is in, waiting on the lock
        started = time.monotonic()
        assert client.get(f"/ui/notebook/{date.today()}/version").status_code == 200
        took = time.monotonic() - started
        waiting.join()
        release.join()
        other.close()
    assert failed == []  # and the save went through once the lock was let go
    return took


def _record(failed: list[BaseException], post, client: httpx.Client) -> None:  # noqa: ANN001
    try:
        post(client)
    except BaseException as exc:  # noqa: BLE001
        failed.append(exc)


def test_a_notebook_save_waits_alone(live, tmp_path) -> None:
    def save(client: httpx.Client) -> None:
        page = {"version": 0, "blocks": [{"kind": "text", "text": "Hello"}]}
        assert client.post(f"/ui/notebook/{date.today()}", json=page).status_code == 200

    assert answer_time_while(save, live, tmp_path / "app.db") < 1


def test_a_sheet_edit_waits_alone(live, tmp_path) -> None:
    def edit(client: httpx.Client) -> None:
        ops = {"ops": [{"op": "task", "day": str(date.today()), "title": "Call the bank"}]}
        assert client.post(f"/ui/day-sheet?start={date.today()}", json=ops).status_code == 200

    assert answer_time_while(edit, live, tmp_path / "app.db") < 1
