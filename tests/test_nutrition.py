"""Nutrition: a day's log read from its Markdown file against the plan's
targets, Claude kept inside the nutrition folder, and the day's chat, with
a stand-in for Claude."""

import json
import time
from datetime import date, datetime
from pathlib import Path

import pytest

from app.config import get_settings
from app.markdown import render_inline, render_markdown
from app.models import ChatRole, NutritionMessage
from app.services import nutrition as nutrition_svc
from app.services import nutrition_chat as chat_svc
from app.services.nutrition import NutritionFileError
from app.services.nutrition_agent import (
    AgentEvent,
    AgentFailed,
    AgentRequest,
    build_prompt,
    outside,
    resolve_cli,
)
from app.ui.nutrition_view import _sections, amount, log_ctx

DAY = date(2026, 9, 30)

PLAN = """\
---
targets:
  kcal: {aim: 2500}
  protein_g: {min: 130}
  sat_fat_g: {max: 20}
---

# Nutrition plan
"""

LOG = """\
---
date: 2026-09-30
meals:
  - name: Breakfast
    status: eaten
    items:
      - food: Rolled oats
        amount: 40 g
        assumed: true
        kcal: 150
        protein_g: 5
        fat_g: 3
        sat_fat_g: 0.5
        carbs_g: 24
        fibre_g: 4
  - name: Dinner
    status: planned
    items:
      - food: Salmon
        amount: 150 g
        kcal: 300
        protein_g: 30
        fat_g: 20
        sat_fat_g: 21
        carbs_g: 0
        fibre_g: 0
---

## Notes

Oats are the best soluble fibre for cholesterol.
- Check the granola label.
"""


@pytest.fixture
def folder(tmp_path, monkeypatch) -> Path:
    """A nutrition folder of its own, holding the plan, as the app's."""
    folder = tmp_path / "nutrition"
    (folder / "log").mkdir(parents=True)
    (folder / "plan.md").write_text(PLAN, encoding="utf-8")
    monkeypatch.setattr(get_settings().nutrition, "dir", str(folder))
    return folder


def write_log(folder: Path, text: str, day: date = DAY) -> None:
    (folder / "log" / f"{day.isoformat()}.md").write_text(text, encoding="utf-8")


VALID = LOG.replace("sat_fat_g: 21", "sat_fat_g: 4")


# ---- the file format ----


def test_a_day_sums_what_was_eaten_and_what_is_planned() -> None:
    log = nutrition_svc.parse_day(VALID, DAY)
    assert [m.name for m in log.meals] == ["Breakfast", "Dinner"]
    assert log.totals(planned=False)["kcal"] == 150
    assert log.totals(planned=True)["kcal"] == 450
    assert log.totals(planned=True)["protein_g"] == 35
    assert log.has_planned
    assert log.body.startswith("## Notes")


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("# no front matter", "no front matter"),
        ("---\ndate: 2026-09-30\n", "no closing"),
        ("---\ndate: [2026\n---\n", "not valid YAML"),
        ("---\ndate: 2026-09-29\n---\n", "not 2026-09-30"),
        (LOG, "sat_fat_g is part of fat_g"),
        (VALID.replace("        fibre_g: 4\n", ""), "meals.0.items.0.fibre_g: Field required"),
        (VALID.replace("status: eaten", "status: maybe"), "meals.0.status"),
        (VALID.replace("assumed: true", "assumed: true\n        brand: Uncle Tobys"), "brand"),
    ],
)
def test_a_file_that_does_not_follow_the_format_says_why(text: str, why: str) -> None:
    with pytest.raises(NutritionFileError, match=why):
        nutrition_svc.parse_day(text, DAY)


def test_the_plans_targets_are_one_kind_each(folder: Path) -> None:
    targets = nutrition_svc.read_targets(folder)
    assert (targets["kcal"].kind, targets["kcal"].value) == ("aim", 2500)
    assert targets["sat_fat_g"].kind == "max"
    both = "---\ntargets:\n  kcal: {aim: 1, max: 2}\n---\n"
    (folder / "plan.md").write_text(both, encoding="utf-8")
    with pytest.raises(NutritionFileError, match="exactly one of aim, min or max"):
        nutrition_svc.read_targets(folder)


def test_markdown_never_passes_raw_html_through() -> None:
    assert "<script>" not in render_markdown("<script>alert(1)</script>")


def test_a_link_to_the_folders_own_files_stays_words() -> None:
    line = "The [one-pan salmon](../meals/one-pan-salmon.md), see [HF](https://example.org)."
    assert render_inline(line) == (
        'The one-pan salmon, see <a href="https://example.org" target="_blank"'
        ' rel="noopener noreferrer">HF</a>.'
    )


# ---- what the page draws ----


def test_the_day_against_its_targets(folder: Path) -> None:
    write_log(folder, VALID.replace("sat_fat_g: 4", "sat_fat_g: 19.6"))
    ctx = log_ctx(folder, DAY)
    rows = {row["key"]: row for row in ctx["totals"]}
    assert rows["kcal"]["eaten"] == "150" and rows["kcal"]["target"] == "of 2,500 kcal"
    assert rows["kcal"]["planned"] == "300"
    assert rows["protein_g"]["target"] == "of at least 130 g"
    # Over the ceiling only with what is planned: a warning, not yet an error.
    assert rows["sat_fat_g"]["badge"] == ("warn", "Over, with planned")
    assert rows["fat_g"]["target"] is None
    assert ctx["meals"][0]["entries"][0]["assumed"]
    assert [s["title"] for s in ctx["sections"]] == ["Notes"]
    assert [r["kind"] for r in ctx["sections"][0]["rows"]] == ["text", "bullet"]


def test_a_log_that_cannot_be_read_says_so(folder: Path) -> None:
    write_log(folder, LOG)
    ctx = log_ctx(folder, DAY)
    assert ctx["log"] is None and "sat_fat_g is part of fat_g" in ctx["error"]


def test_sections_keep_a_table_whole() -> None:
    sections = _sections("Intro line.\n\n## Next\n| a | b |\n| --- | --- |\n| 1 | 2 |\nAfter.")
    assert [s["title"] for s in sections] == ["Notes", "Next"]
    assert [r["kind"] for r in sections[1]["rows"]] == ["block", "text"]
    assert "<table>" in sections[1]["rows"][0]["html"]


def test_amounts_read_as_figures() -> None:
    assert amount(2440, "kcal") == "2,440"
    assert amount(0.5, "g") == "0.5"
    assert amount(12.4, "g") == "12"
    assert amount(4.0, "g") == "4"


# ---- Claude: kept in its folder, told what it needs ----


def test_file_tools_stay_inside_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "nutrition"
    folder.mkdir()
    assert outside(folder, "Read", {"file_path": "plan.md"}) is None
    assert outside(folder, "Write", {"file_path": str(folder / "log" / "x.md")}) is None
    assert outside(folder, "Grep", {"pattern": "oats"}) is None
    assert outside(folder, "Edit", {"file_path": "../app/main.py"})
    assert outside(folder, "Read", {"file_path": str(tmp_path / "secret.txt")})
    assert outside(folder, "Glob", {"pattern": str(tmp_path / "**")})
    assert outside(folder, "WebSearch", {"query": "anything"}) is None


def test_the_cli_is_found_as_a_native_executable(tmp_path: Path, monkeypatch) -> None:
    npm = tmp_path / "npm"
    exe = npm / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    (npm / "claude.cmd").write_text("")
    monkeypatch.setattr("shutil.which", lambda name: str(npm / "claude.cmd"))
    assert resolve_cli() == exe
    with pytest.raises(AgentFailed, match="not installed at .*nowhere.exe"):
        resolve_cli(str(tmp_path / "nowhere.exe"))
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(AgentFailed, match="not installed"):
        resolve_cli()


def test_the_prompt_carries_the_day_the_chat_and_the_profile(tmp_path: Path) -> None:
    request = AgentRequest(
        day=DAY, now=datetime(2026, 9, 30, 19, 5), message="Dinner was the bean pan",
        folder=tmp_path, profile={"weight_kg": 70, "birth_date": date(1990, 1, 1)},
        transcript=[("oscar", "Breakfast was oats"), ("claude", "Logged it.")],
    )
    prompt = build_prompt(request)
    assert "Wednesday 30 September 2026, 19:05" in prompt
    assert "log/2026-09-30.md" in prompt
    assert '"birth_date": "1990-01-01"' in prompt
    order = [prompt.index(words) for words in ("Breakfast was oats", "Logged it.", "bean pan")]
    assert order == sorted(order)
    repair = build_prompt(AgentRequest(day=DAY, now=request.now, message="bad date",
                                       folder=tmp_path, repair=True))
    assert "does not follow the format" in repair and "bad date" in repair


# ---- the chat, with a stand-in for Claude ----


def logging_agent(text: str = VALID, reply: str = "Logged your oats."):  # noqa: ANN201
    """A stand-in for Claude that writes the day's log and says so."""
    calls: list[AgentRequest] = []

    async def agent(request: AgentRequest):  # noqa: ANN202
        calls.append(request)
        yield AgentEvent("status", "Reading the plan")
        write_log(request.folder, text, request.day)
        yield AgentEvent("status", "Writing the day's log")
        for word in reply.split(" "):
            yield AgentEvent("text", word + " ")

    agent.calls = calls
    return agent


@pytest.fixture
def chat_client(client, folder):  # noqa: ANN001, ANN201
    from app.ui.nutrition import get_agent

    def use(agent) -> None:  # noqa: ANN001
        client.app.dependency_overrides[get_agent] = lambda: agent

    client.use_agent = use
    return client


def stream(client, day: date, message: str) -> list[dict]:  # noqa: ANN001
    response = client.post(f"/ui/nutrition/{day.isoformat()}/chat", data={"message": message})
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_a_message_streams_claudes_answer_and_logs_the_day(chat_client, db, folder) -> None:
    agent = logging_agent()
    chat_client.use_agent(agent)
    events = stream(chat_client, DAY, "Breakfast was oats")
    assert [e["type"] for e in events][:2] == ["status", "status"]
    assert "".join(e["text"] for e in events if e["type"] == "text").strip() == "Logged your oats."
    assert events[-1] == {"type": "done", "failed": False}

    db.expire_all()
    said = chat_svc.messages(db, DAY)
    assert [(m.role, m.text, m.failed) for m in said] == [
        (ChatRole.oscar, "Breakfast was oats", False),
        (ChatRole.claude, "Logged your oats.", False),
    ]
    # The next message carries the chat so far.
    stream(chat_client, DAY, "And a coffee")
    earlier = [("oscar", "Breakfast was oats"), ("claude", "Logged your oats.")]
    assert agent.calls[1].transcript == earlier

    page = chat_client.get(f"/nutrition/{DAY.isoformat()}")
    assert page.status_code == 200
    assert "Rolled oats" in page.text and "of 2,500 kcal" in page.text
    assert "Logged your oats." in page.text


def test_a_log_claude_leaves_unreadable_gets_one_turn_to_fix(chat_client, db, folder) -> None:
    fixed = logging_agent(VALID)
    broken = logging_agent(LOG)

    async def agent(request: AgentRequest):  # noqa: ANN202
        async for event in (fixed if request.repair else broken)(request):
            yield event

    chat_client.use_agent(agent)
    events = stream(chat_client, DAY, "Oats, and salmon tonight")
    assert {"type": "status", "text": "Fixing the day's log"} in events
    assert fixed.calls and "sat_fat_g is part of fat_g" in fixed.calls[0].message
    # The fix is unseen: its words are not the answer.
    assert "".join(e["text"] for e in events if e["type"] == "text").strip() == "Logged your oats."
    assert nutrition_svc.read_day(folder, DAY) is not None


def test_an_answer_that_fails_is_saved_with_why(chat_client, db) -> None:
    async def agent(request: AgentRequest):  # noqa: ANN202
        yield AgentEvent("text", "Let me look.")
        raise AgentFailed("Claude Code is not installed here")

    chat_client.use_agent(agent)
    events = stream(chat_client, DAY, "Hello")
    assert events[-1] == {"type": "done", "failed": True}
    db.expire_all()
    answer = chat_svc.messages(db, DAY)[-1]
    assert answer.failed and answer.text == "Let me look.\n\nClaude Code is not installed here"
    # A failed answer is not carried into the next prompt.
    chat_client.use_agent(logging_agent())
    stream(chat_client, DAY, "Again")
    assert "Did not finish" in chat_client.get(f"/ui/nutrition/{DAY.isoformat()}/chat").text


def test_one_answer_at_a_time_per_day(chat_client, db) -> None:
    release = __import__("threading").Event()

    async def slow(request: AgentRequest):  # noqa: ANN202
        import asyncio

        while not release.is_set():
            await asyncio.sleep(0.01)
        yield AgentEvent("text", "Done.")

    run = chat_svc.start(db, DAY, "First", agent=slow, profile={})
    try:
        chat_client.use_agent(slow)
        url = f"/ui/nutrition/{DAY.isoformat()}/chat"
        second = chat_client.post(url, data={"message": "Second"})
        assert second.status_code == 422 and "still answering" in second.json()["detail"]
        # The test's session stands in for each request's, which would end
        # here (the refused request began the profile), freeing the database.
        db.commit()
        # A page opened meanwhile shows the answer on its way, and asks after it.
        pending = chat_client.get(f"/ui/nutrition/{DAY.isoformat()}/chat")
        assert 'id="chat-pending"' in pending.text
    finally:
        release.set()
    end = time.monotonic() + 5
    while not run.finished:
        assert time.monotonic() < end
        time.sleep(0.01)
    after = chat_client.get(
        f"/ui/nutrition/{DAY.isoformat()}/chat", headers={"HX-Trigger": "chat-pending"}
    )
    assert after.headers.get("HX-Trigger") == "nutrition:answered"
    assert "chat-pending" not in after.text


def test_an_empty_message_is_refused(chat_client) -> None:
    chat_client.use_agent(logging_agent())
    response = chat_client.post(f"/ui/nutrition/{DAY.isoformat()}/chat", data={"message": "   "})
    assert response.status_code == 422


def test_the_page_before_anything_is_logged(chat_client, folder) -> None:
    page = chat_client.get("/nutrition/2026-09-01")
    assert page.status_code == 200
    assert "Nothing logged yet" in page.text and "Nothing said yet" in page.text
    today = chat_client.get(f"/nutrition/{date.today().isoformat()}", follow_redirects=False)
    assert today.status_code == 303 and today.headers["location"] == "/nutrition"


def test_messages_are_stored_by_day(db) -> None:
    db.add(NutritionMessage(day=DAY, role=ChatRole.oscar, text="Oats"))
    db.add(NutritionMessage(day=date(2026, 10, 1), role=ChatRole.oscar, text="Eggs"))
    db.flush()
    assert [m.text for m in chat_svc.messages(db, DAY)] == ["Oats"]
