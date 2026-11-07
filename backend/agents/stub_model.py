"""Model stand-ins that never touch the network.

`ScriptedModel` lets tests decide each reply. `RuleStubModel` is the labeled
`stub` agent D can run with no OpenRouter key: it reads the same prompts and
answers with simple rules, and every event it produces is marked as
code-written (`source: system_template`, `data.agent_impl: stub`).
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .openrouter import ChatResult, ModelUnavailable

Responder = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], "str | dict | ChatResult"]


class ScriptedModel:
    impl = "stub"

    def __init__(self, responder: Responder, model: str = "scripted-stub"):
        self.responder = responder
        self.model = model
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(self, messages, *, tools=None, timeout_s: float) -> ChatResult:
        self.calls.append(messages)
        out = self.responder(messages, tools)
        if isinstance(out, Exception):
            raise out
        if isinstance(out, ChatResult):
            return out
        content = out if isinstance(out, str) else json.dumps(out)
        return ChatResult(content, [], {"prompt_tokens": 0, "completion_tokens": 0}, 0.0, self.model, {})


def _meta(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Prompts embed a machine-readable block between <meta> tags."""
    for m in reversed(messages):
        found = re.search(r"<meta>(.*?)</meta>", str(m.get("content", "")), re.S)
        if found:
            return json.loads(found.group(1))
    raise ModelUnavailable("stub: no meta block in prompt")


def rule_responder(messages, tools):
    meta = _meta(messages)
    kind = meta.get("kind")
    if kind == "interpret":
        return _rule_interpret(meta)
    if kind == "review":
        opts = meta.get("options") or []
        if opts and not meta.get("flat"):
            best = opts[0]
            return {
                "home_id": meta["home_id"],
                "proposal_id": meta["proposal_id"],
                "accept": False,
                "objections": ["Part of my use runs during expensive hours."],
                "request_option_id": best["option_id"],
                "public_message": best["ask_text"],
            }
        return {
            "home_id": meta["home_id"],
            "proposal_id": meta["proposal_id"],
            "accept": True,
            "objections": [],
            "request_option_id": None,
            "public_message": f"{meta['proposal_name']} works for my home.",
        }
    if kind == "neighbor_ask":
        ok = meta.get("on_time") and meta.get("cost_delta", 0) <= 0.005
        return {
            "agree": bool(ok),
            "public_message": "Yes, that still works for my home." if ok else "Sorry, that doesn't work for my home.",
        }
    raise ModelUnavailable(f"stub: unknown prompt kind {kind!r}")


_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", re.I)


def _rule_interpret(meta: dict[str, Any]) -> dict[str, Any]:
    text = meta["text"].lower()
    m = _TIME.search(text)
    if not m:
        return {"understood": False, "edits": [], "question": "What time do you need it done by?"}
    h = int(m.group(1)) % 12 + (12 if m.group(3).startswith("p") else 0)
    hhmm = f"{h:02d}:{int(m.group(2) or 0):02d}"
    words = {
        "car": ("ev", "car", "charg"), "dryer": ("dryer",), "dishwasher": ("dish",),
        "washing machine": ("washing machine", "washer"),
        "water heater": ("water heater", "hot water", "heater"),
        "air conditioning": ("air conditioning", "air con", "a/c", " ac ", "cooling"),
        "pool pump": ("pool", "pump"),
    }
    padded = f" {text} "
    for task in meta["tasks"]:
        label = task["label"]
        keys = next((v for k, v in words.items() if k in label), (label,))
        # "dishwasher" contains "washer": only the dishwasher may claim it.
        hay = padded if "dish" in label else padded.replace("dishwasher", "")
        if any(k in hay for k in keys):
            return {
                "understood": True,
                "edits": [{"task_id": task["id"], "field": "deadline_slot", "new_time": hhmm}],
                "question": None,
            }
    return {"understood": False, "edits": [], "question": "Which appliance is this about?"}


class RuleStubModel(ScriptedModel):
    def __init__(self):
        super().__init__(rule_responder, model="rule-stub")
