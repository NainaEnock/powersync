"""C3: time one real OpenRouter call with a tool definition and a structured reply.

Run on purpose (it uses the event quota), from the repo root with .venv active:

    python -m backend.agents.timing_check            # 1 call
    python -m backend.agents.timing_check --review   # + 1 household review call

Checks OPENROUTER_MODEL against the catalog (exact ID, tool support) first.
Never prints the key.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import httpx
from dotenv import load_dotenv

from .config import load_settings
from .openrouter import Budget, OpenRouterClient, extract_json, run_turn
from .prompts import household_system, review_user

TOOL = [{
    "type": "function",
    "function": {
        "name": "get_my_home_context",
        "description": "Your home's appliances and deadlines.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}]


async def check_catalog(model: str) -> None:
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.get("https://openrouter.ai/api/v1/models")
    ids = {m["id"]: m for m in r.json().get("data", [])}
    if model not in ids:
        close = [i for i in ids if model.split("/")[-1][:8] in i][:5]
        sys.exit(f"Model {model!r} is not in the catalog. Close matches: {close}")
    params = ids[model].get("supported_parameters") or []
    print(f"catalog: {model} found; tools supported: {'tools' in params}")


async def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", action="store_true", help="also time one household review prompt")
    args = ap.parse_args()
    s = load_settings()
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key or not s.model:
        sys.exit("Set OPENROUTER_API_KEY and OPENROUTER_MODEL in .env first.")
    await check_catalog(s.model)
    client = OpenRouterClient(key, s.model, max_retries=0)

    async def fake_context(_):
        return {"tasks": [{"label": "dryer", "deadline": "11:00 PM"}]}

    budget = Budget(4, 4, 120)
    t0 = time.monotonic()
    text = await run_turn(
        client,
        [{"role": "system", "content": "Call get_my_home_context once, then reply with JSON only: "
                                       '{"ok": true, "deadline": "<the dryer deadline>"}'},
         {"role": "user", "content": "What is my dryer deadline?"}],
        budget, tool_schemas=TOOL, tool_impls={"get_my_home_context": fake_context},
        max_tool_rounds=1, call_timeout_s=s.call_timeout_s,
    )
    total = time.monotonic() - t0
    try:
        parsed = extract_json(text)
    except ValueError:
        parsed = None
    print(f"tool round trip: {total:.1f} s total over {budget.model_calls} model calls; "
          f"tokens in/out {budget.prompt_tokens}/{budget.completion_tokens}; structured reply ok: {parsed is not None}")

    if args.review:
        meta = {
            "kind": "review", "home_id": "B", "proposal_id": "P-1", "proposal_name": "Plan 1",
            "context": "The neighborhood asked to coordinate tonight's appliances.", "flat": False,
            "prices": "Electricity costs $0.59 per kWh until 9:00 PM and $0.33 per kWh after that.",
            "own_tasks": [{"label": "dryer", "runs": "6:30–7:15 PM", "deadline": "11:00 PM", "share_in_expensive_hours": 1.0}],
            "own_cost": "$13.67", "street_peak_kw": 13.2, "capacity_kw": 15,
            "options": [{"option_id": "P-1-B-1", "description": "If Home A's car charging started at 9:45 PM instead of 9:00 PM, your dryer could run 9:00–9:45 PM and your charge would drop by $0.97.", "ask_text": ""}],
        }
        b2 = Budget(2, 0, 120)
        t0 = time.monotonic()
        text = await run_turn(client, [{"role": "system", "content": household_system("Home B")},
                                       {"role": "user", "content": review_user(meta)}],
                              b2, max_tool_rounds=0, call_timeout_s=s.call_timeout_s)
        print(f"household review: {time.monotonic() - t0:.1f} s; reply: {text[:300]!r}")
    print("Rule of thumb (PRD §13.1): over ~15 s per review means pick a faster model.")


if __name__ == "__main__":
    from .openrouter import ModelUnavailable

    try:
        asyncio.run(main())
    except ModelUnavailable as exc:
        hint = " (the key was rejected: check it in .env)" if "401" in str(exc) else ""
        sys.exit(f"OpenRouter call failed: {exc}{hint}")
