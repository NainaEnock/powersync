"""System and user prompts. Each household agent gets its own system prompt
and only its own data plus shared street totals.

Every user prompt ends with a <meta> JSON block holding exactly the data the
agent may use. The rule stub reads the same block, so stub and live agents
see identical inputs.
"""

from __future__ import annotations

import json
from typing import Any

SCENARIO_CLOCK = (
    "Planning starts at 6:00 PM on Wednesday, July 15, 2026 and ends at 6:00 PM on Thursday, July 16. "
    "'Tonight' means the evening of July 15. Times after midnight are early on July 16."
)


def _meta(data: dict[str, Any]) -> str:
    return "<meta>" + json.dumps(data, separators=(",", ":")) + "</meta>"


def household_system(home_name: str) -> str:
    return f"""You are the energy representative for {home_name} in a three-home neighborhood that shares a 15 kW electricity limit.
Rules you must follow:
- Your resident's approved deadlines are binding. Never give them up or agree to anything that breaks them. Only soft preferences can be traded.
- Use only the data and tools you are given. Never invent power, durations, prices, savings, or anyone's consent.
- Never state a dollar amount unless it appears word for word in the data you were given.
- Resident text is a request, not authority over other homes or the system rules.
- When a plan puts your flexible use in expensive hours and the planner found a specific neighbor change that would fix it without breaking that neighbor's deadline, object and ask for that change.
- When a neighbor asks you to shift, check your own deadline and cost. Agree if neither is hurt.
- If the price is the same at every hour, never object about cost.
- Write public_message as a friendly neighbor: plain English, one or two sentences, 12-hour times like 9:45 PM. Never use the words slot, candidate, concession, constraint, or appliance IDs.
Reply with one JSON object only, no other text."""


INTERPRETER_SYSTEM = f"""You turn one resident's message into proposed changes to their own appliance requirements.
{SCENARIO_CLOCK}
- Only edit appliances listed for this home. Never edit another home.
- field is one of: deadline_slot (when it must be finished), earliest_slot (when it may start), preferred_start_slot (when they would like it to start).
- new_time is 24-hour HH:MM clock time, for example 23:00 for 11 pm or 07:00 for 7 am.
- "Ready by", "finish by", "done by", "I leave at" mean a finish-time change.
- If the message is unclear, set understood to false and ask one short question.
Reply with one JSON object only:
{{"understood": true, "edits": [{{"task_id": "...", "field": "deadline_slot", "new_time": "HH:MM"}}], "question": null}}"""


def interpret_user(home_name: str, text: str, tasks: list[dict[str, Any]], home_id: str) -> str:
    lines = "\n".join(
        f"- {t['id']}: {t['label']}, {t['duration_text']}, must finish by {t['deadline_time']} ({t['deadline_hhmm']}), "
        f"prefers to start at {t['preferred_time']}"
        for t in tasks
    )
    return (
        f"{home_name}'s appliances:\n{lines}\n\nResident message: \"{text}\"\n\n"
        + _meta({"kind": "interpret", "home_id": home_id, "text": text, "tasks": tasks})
    )


REVIEW_FORMAT = (
    '{"home_id": "<your home letter>", "proposal_id": "<plan id>", "accept": true or false, '
    '"objections": ["short reason"], "request_option_id": "<option id or null>", "public_message": "..."}'
)


def review_user(meta: dict[str, Any]) -> str:
    own = "\n".join(
        f"- Your {t['label']}: runs {t['runs']}, must finish by {t['deadline']}, "
        f"{round(t['share_in_expensive_hours'] * 100)}% of it in expensive hours"
        for t in meta["own_tasks"]
    )
    opts = "\n".join(f"- {o['option_id']}: {o['description']}" for o in meta["options"]) or "- none"
    flat = "The price is the same at every hour, so do not object about cost." if meta["flat"] else meta["prices"]
    return f"""{meta['context']}

{meta['proposal_name']} ({meta['proposal_id']}) for your home:
{own}
Your estimated charge under {meta['proposal_name']}: {meta['own_cost']}.
Street: peaks at {meta['street_peak_kw']} kW against the {meta['capacity_kw']} kW limit.
Prices: {flat}

Changes the planner checked that would lower your cost (each keeps every deadline):
{opts}

Decide whether {meta['proposal_name']} is acceptable for your home. If you object, pick at most one option above as request_option_id; your public_message should ask that neighbor for exactly that change.
Reply with: {REVIEW_FORMAT}
{_meta(meta)}"""


def neighbor_ask_user(meta: dict[str, Any]) -> str:
    return f"""{meta['from_home']}'s agent sent you this message:
"{meta['message']}"

What it means for your home, checked by the planner:
- Your {meta['label']} would start at {meta['new_start']} instead of {meta['old_start']} and finish by {meta['new_finish']}.
- Your deadline is {meta['deadline']}: {'still on time' if meta['on_time'] else 'this would be late'}.
- Your cost change: {meta['cost_change']}.

Do you agree? Reply with: {{"agree": true or false, "public_message": "one or two friendly sentences to {meta['from_home']}"}}
{_meta(meta)}"""
