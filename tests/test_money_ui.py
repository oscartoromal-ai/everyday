"""Finances' pages: an export imported from Accounts, the month on Spending
with its budgets and transactions sorted on the line, bills and goals
written and saved as they change, and Spending's chat with a stand-in for
Claude that works through the same tools Claude has."""

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import ChatRole
from app.services import money as money_svc
from app.services import money_chat as chat_svc
from app.services.claude_sdk import AgentEvent
from app.services.money_agent import AgentRequest, build_prompt, run_tool, status

DATA = Path(__file__).parent / "data"
MONTH = "2026-09"


def upload(client, name: str, account_id: str = ""):  # noqa: ANN001, ANN201
    data = (DATA / name).read_bytes()
    return client.post(
        "/ui/money/import", files={"export": (name, data, "text/csv")},
        data={"account_id": account_id},
    )


def test_every_page_opens_before_anything_is_imported(client) -> None:
    for url, words in [
        ("/spending", "No accounts yet"), ("/accounts", "Revolut's or ING's"),
        ("/bills", "New bill"), ("/goals", "No goals yet"),
    ]:
        page = client.get(url)
        assert page.status_code == 200, url
        assert words in page.text, url
    this_month = date.today().strftime("%Y-%m")
    back = client.get(f"/spending/{this_month}", follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == "/spending"
    assert client.get("/spending/2026-13").status_code == 422


def test_an_import_lands_in_a_new_account_and_says_what_it_did(client, db) -> None:
    client.get("/accounts")  # the categories begin
    first = upload(client, "revolut-2026-09.csv")
    assert first.status_code == 200
    assert "Revolut: 6 added to Revolut; 2 left out (1 pending, 1 in USD)." in first.text
    assert "Balance $519.81 on 20 Sep." in first.text
    account = money_svc.accounts(db)[0]
    again = upload(client, "revolut-2026-09.csv", str(account.id))
    assert "0 added to Revolut; 6 already here" in again.text
    # Into its bank's account unless another is chosen.
    assert "0 added to Revolut; 6 already here" in upload(client, "revolut-2026-09.csv").text
    ing = upload(client, "ing-2026-09.csv")
    assert "ING: 3 added to ING" in ing.text
    page = client.get("/accounts").text
    assert "$10,523" in page  # net worth: both balances
    # A new one when asked for, named apart.
    assert "6 added to Revolut 2;" in upload(client, "revolut-2026-09.csv", "new").text
    bad = client.post("/ui/money/import",
                      files={"export": ("notes.csv", b"Name,Value\na,1\n", "text/csv")})
    assert "notes.csv cannot be imported: it is not a Revolut or ING export" in bad.text


def test_the_month_sorts_and_budgets_on_the_line(client, db) -> None:
    client.get("/accounts")
    upload(client, "revolut-2026-09.csv")
    page = client.get(f"/spending/{MONTH}")
    assert page.status_code == 200
    assert "Woolworths Metro" in page.text and "-$45.20" in page.text
    assert "5 transactions" in page.text  # not sorted: all but the top-up

    groceries = money_svc.category_named(db, "Groceries")
    [woolworths] = money_svc.transactions(db, text="Woolworths")
    sorted_row = client.post(f"/ui/money/transactions/{woolworths.id}/category",
                             data={"category_id": str(groceries.id)})
    assert sorted_row.headers["HX-Trigger"] == "money:sorted"
    assert f'value="{groceries.id}" selected' in sorted_row.text

    totals = client.post(f"/ui/money/{MONTH}/budgets/{groceries.id}", data={"budget": "40"})
    assert "Over" in totals.text  # $45 of $40
    assert 'id="budget-' in totals.text and 'value="40"' in totals.text
    cleared = client.post(f"/ui/money/{MONTH}/budgets/{groceries.id}", data={"budget": ""})
    assert "Over" not in cleared.text
    refused = client.post(f"/ui/money/{MONTH}/budgets/{groceries.id}", data={"budget": "lots"})
    assert refused.status_code == 422

    added = client.post(f"/ui/money/{MONTH}/categories",
                        data={"name": "Coffee", "kind": "spending"})
    assert added.status_code == 204 and added.headers["HX-Trigger"] == "money:changed"
    coffee = money_svc.category_named(db, "Coffee")
    assert ">Coffee</option>" in client.get(f"/ui/money/{MONTH}/sheet").text
    client.post(f"/ui/money/{MONTH}/categories/{coffee.id}/delete")
    assert ">Coffee</option>" not in client.get(f"/ui/money/{MONTH}/sheet").text


def test_accounts_balances_and_rules_are_kept_from_the_sheet(client, db) -> None:
    client.get("/accounts")
    sheet = client.post("/ui/money/accounts", data={"name": "Super", "kind": "super"})
    assert 'value="Super"' in sheet.text
    super_ = money_svc.accounts(db)[0]
    sheet = client.post("/ui/money/balances",
                        data={"account_id": super_.id, "amount": "25,000", "day": "2026-09-30"})
    assert "$25,000.00" in sheet.text and "Net worth" in sheet.text
    sheet = client.post(f"/ui/money/accounts/{super_.id}",
                        data={"name": "AustralianSuper", "kind": "super"})
    assert 'value="AustralianSuper"' in sheet.text

    upload(client, "revolut-2026-09.csv")
    eating = money_svc.category_named(db, "Eating out")
    sheet = client.post("/ui/money/rules",
                        data={"pattern": "coffee club", "category_id": eating.id})
    assert "It sorted 2 transactions already here." in sheet.text
    rule = money_svc.rules(db)[0]
    sheet = client.post(f"/ui/money/rules/{rule.id}/delete")
    assert "coffee club" not in sheet.text
    duplicate = client.post("/ui/money/accounts", data={"name": "revolut", "kind": "everyday"})
    assert duplicate.status_code == 422 and "already" in duplicate.json()["detail"]


def test_bills_are_written_saved_and_seen_paid(client, db) -> None:
    client.get("/accounts")
    upload(client, "revolut-2026-09.csv")
    sheet = client.post("/ui/money/bills", data={
        "name": "Netflix", "amount": "22.99", "cadence": "monthly", "due": "2026-08-15",
        "match": "netflix",
    })
    assert sheet.status_code == 200 and 'value="Netflix"' in sheet.text
    bill = money_svc.bills(db)[0]
    sheet = client.post(f"/ui/money/bills/{bill.id}", data={
        "name": "Netflix", "amount": "24.99", "cadence": "monthly", "due": "2026-09-15",
        "match": "netflix",
    })
    assert 'value="24.99"' in sheet.text
    assert client.post("/ui/money/bills", data={"name": "x", "amount": "", "due": "2026-09-01"}
                       ).status_code == 422
    client.post(f"/ui/money/bills/{bill.id}/delete")
    assert money_svc.bills(db) == []


def test_goals_count_an_account_or_what_is_written(client, db) -> None:
    sheet = client.post("/ui/money/goals", data={"name": "Buffer", "target": "1000", "saved": ""})
    assert 'value="Buffer"' in sheet.text
    goal = money_svc.goals(db)[0]
    sheet = client.post(f"/ui/money/goals/{goal.id}", data={
        "name": "Buffer", "target": "1000", "by": "", "account_id": "", "saved": "250",
    })
    assert "$250" in sheet.text and "$750 to go" in sheet.text


# ---- Claude's tools, and the chat with a stand-in ----


def test_claudes_tools_read_and_change_through_the_app(client, db) -> None:
    client.get("/accounts")
    upload(client, "revolut-2026-09.csv")
    factory = sessionmaker(bind=db.get_bind())
    month = json.loads(run_tool(factory, "get_month", {"month": MONTH})["content"][0]["text"])
    assert month["unsorted"]["transactions"] == 5
    found = json.loads(run_tool(factory, "find_transactions",
                                {"month": MONTH, "text": "coffee"})["content"][0]["text"])
    ids = [t["id"] for t in found["transactions"]]
    assert len(ids) == 2
    done = run_tool(factory, "sort_transactions",
                    {"transaction_ids": ids, "category": "eating out"})
    assert json.loads(done["content"][0]["text"]) == {"sorted": 2, "category": "eating out"}
    wrong = run_tool(factory, "set_budget", {"category": "Snacks", "amount": 50})
    assert wrong["is_error"] and "No category called Snacks" in wrong["content"][0]["text"]
    missing = run_tool(factory, "save_bill", {"name": "Gym"})
    assert missing["is_error"] and "Missing" in missing["content"][0]["text"]
    db.expire_all()
    assert all(t.category.name == "Eating out" for t in money_svc.transactions(db, text="coffee"))
    assert status("mcp__money__get_month", {"month": MONTH}) == "Reading September's spending"
    assert status("mcp__money__sort_transactions", {"transaction_ids": [1]}) == (
        "Sorting 1 transaction")


def test_the_prompt_carries_the_month_and_the_chat(db) -> None:
    from datetime import datetime

    request = AgentRequest(
        month=date(2026, 9, 1), now=datetime(2026, 9, 30, 19, 5), message="Sort the rest",
        factory=None, transcript=[("oscar", "How much on coffee?"), ("claude", "$11.")],
    )
    prompt = build_prompt(request)
    assert "Wednesday 30 September 2026, 19:05" in prompt
    assert "September 2026 (2026-09)" in prompt
    order = [prompt.index(w) for w in ("How much on coffee?", "$11.", "Sort the rest")]
    assert order == sorted(order)


@pytest.fixture
def chat_client(client):  # noqa: ANN001, ANN201
    from app.ui.money import get_agent

    def use(agent) -> None:  # noqa: ANN001
        client.app.dependency_overrides[get_agent] = lambda: agent

    client.use_agent = use
    return client


def sorting_agent():  # noqa: ANN201
    """A stand-in for Claude that sorts the coffees through its tools."""

    async def agent(request: AgentRequest):  # noqa: ANN202
        yield AgentEvent("status", status("mcp__money__find_transactions", {}))
        found = run_tool(request.factory, "find_transactions",
                         {"month": request.month.strftime("%Y-%m"), "text": "coffee"})
        ids = [t["id"] for t in json.loads(found["content"][0]["text"])["transactions"]]
        run_tool(request.factory, "add_rule", {"words": "Coffee Club", "category": "Eating out"})
        yield AgentEvent("text", f"Sorted **{len(ids)} coffees** into Eating out.")

    return agent


def test_a_message_streams_the_answer_and_changes_the_month(chat_client, db) -> None:
    chat_client.get("/accounts")
    upload(chat_client, "revolut-2026-09.csv")
    chat_client.use_agent(sorting_agent())
    response = chat_client.post(f"/ui/money/{MONTH}/chat", data={"message": "Sort my coffees"})
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[0] == {"type": "status", "text": "Looking through transactions"}
    assert events[-1] == {"type": "done", "failed": False}

    db.expire_all()
    said = chat_svc.messages(db, date(2026, 9, 1))
    assert [(m.role, m.text) for m in said] == [
        (ChatRole.oscar, "Sort my coffees"),
        (ChatRole.claude, "Sorted **2 coffees** into Eating out."),
    ]
    assert [r.pattern for r in money_svc.rules(db)] == ["Coffee Club"]
    page = chat_client.get(f"/spending/{MONTH}").text
    assert "<strong>2 coffees</strong>" in page
    assert "3 transactions" in page  # two fewer unsorted
