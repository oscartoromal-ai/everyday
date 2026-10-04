"""A stand-in for `codex app-server`: its JSON-RPC, a JSON object a line on
stdin and stdout, as far as the app speaks it (initialize, account/read,
model/list in two pages). How it behaves is its first argument:

- ready: signed in with ChatGPT, two pages of models, one hidden;
- signed_out: no account, sign-in required;
- refuses: model/list answered with an error;
- silent: reads, never answers.

Before answering each request it says something the app must pass over:
a notification, and a line that is no JSON.
"""

import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "ready"

PAGES = {
    None: {"data": [
        {"id": "gpt-6-astra", "model": "gpt-6-astra", "displayName": "GPT-6 Astra",
         "description": "Frontier agentic coding", "hidden": False, "isDefault": True,
         "defaultReasoningEffort": "medium",
         "supportedReasoningEfforts": [
             {"reasoningEffort": "low", "description": ""},
             {"reasoningEffort": "medium", "description": ""},
             {"reasoningEffort": "high", "description": ""}]},
        {"id": "gpt-internal", "model": "gpt-internal", "displayName": "Internal",
         "description": "", "hidden": True, "isDefault": False,
         "defaultReasoningEffort": "low", "supportedReasoningEfforts": []},
    ], "nextCursor": "page-2"},
    "page-2": {"data": [
        {"id": "gpt-6-luna", "model": "gpt-6-luna", "displayName": "GPT-6 Luna",
         "description": "Fast and light", "hidden": False, "isDefault": False,
         "defaultReasoningEffort": "low",
         "supportedReasoningEfforts": [{"reasoningEffort": "low", "description": ""}]},
    ], "nextCursor": None},
}


def say(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:  # a notification: initialized
        continue
    if MODE == "silent":
        continue
    say({"method": "thread/started", "params": {}})
    sys.stdout.write("not json\n")
    method, asked = message["method"], message["id"]
    if method == "initialize":
        say({"id": asked, "result": {"userAgent": "codex_cli_rs/0.156.1 (Windows)"}})
    elif method == "account/read":
        if MODE == "signed_out":
            say({"id": asked, "result": {"account": None, "requiresOpenaiAuth": True}})
        else:
            say({"id": asked, "result": {"account": {
                "type": "chatgpt", "email": "oscar@example.com", "planType": "pro",
            }, "requiresOpenaiAuth": True}})
    elif method == "model/list":
        if MODE == "refuses":
            say({"id": asked, "error": {"code": -32600, "message": "models unavailable"}})
        else:
            say({"id": asked, "result": PAGES[message["params"].get("cursor")]})
    else:
        say({"id": asked, "error": {"code": -32601, "message": f"no method {method}"}})
