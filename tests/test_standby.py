"""The version started ahead of a restart, between the running app and it
(app/desktop/standby.py), with a stand-in for the version (standby_child.py)."""

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

from app.desktop import standby
from app.desktop.standby import Handover, Standby, Waiting

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def instance() -> str:
    return f"Local\\PersonalCalendarTest.{uuid.uuid4()}"


@pytest.fixture
def started(monkeypatch, tmp_path, instance) -> Path:
    """Standby starts the stand-in, not a program; what it is told lands in
    the file returned."""
    out = tmp_path / "told.json"
    real_popen = subprocess.Popen

    def popen(args, **kwargs):  # noqa: ANN001, ANN202
        assert args[1] == "--standby" and args[2] == str(os.getpid())
        kwargs["env"] = {**kwargs["env"], "PYTHONPATH": str(ROOT)}
        child = [sys.executable, str(ROOT / "tests" / "standby_child.py")]
        return real_popen([*child, instance, args[2], args[3], str(tmp_path), str(out)], **kwargs)

    monkeypatch.setattr(standby.subprocess, "Popen", popen)
    return out


def test_a_standby_takes_over_where_it_is_told(started, tmp_path, instance) -> None:
    waiting = Standby(Path("C:/staged/Personal Calendar.exe"), instance, tmp_path)
    assert waiting.wait_ready(60)
    assert not waiting.wait_up(0.05)

    waiting.go(Handover("/projects/3", background=True))

    assert waiting.wait_up(30)
    assert json.loads(started.read_text(encoding="utf-8")) == {
        "page": "/projects/3", "background": True,
    }
    # It read where to come up, and took it away.
    assert not list(tmp_path.glob("handover-*.json"))
    waiting.process.wait(10)


def test_a_standby_told_to_quit_ends(started, tmp_path, instance) -> None:
    waiting = Standby(Path("C:/staged/Personal Calendar.exe"), instance, tmp_path)
    assert waiting.wait_ready(60)

    waiting.stop()

    assert waiting.process.returncode == 0
    assert json.loads(started.read_text(encoding="utf-8")) is None


def test_a_standby_ends_with_the_app_it_stands_by_for(tmp_path, instance) -> None:
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    told: list = []
    waiting = threading.Thread(
        target=lambda: told.append(Waiting(instance, app.pid, "given", tmp_path).wait_for_go())
    )
    waiting.start()
    waiting.join(30)
    app.wait()
    assert told == [None]


def test_a_standby_whose_handover_is_lost_opens_today(tmp_path, instance) -> None:
    told: list = []
    waiting = Waiting(instance, os.getpid(), "given", tmp_path)
    thread = threading.Thread(target=lambda: told.append(waiting.wait_for_go()))
    thread.start()
    go = standby._signal(instance, "given", "Go")
    try:
        go.set()
        thread.join(30)
    finally:
        go.close()
    assert told == [Handover("/today", background=False)]
