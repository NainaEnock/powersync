"""Thin wrapper over the backend's `emit` callback.

D's emit(event_dict) stores the event immediately and returns its stable ID
(sync or async both work). `emit({"stage": "..."})` sets state.activity.
D fills id, sequence, job_id, timestamp, revision; C fills the rest.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger("powersync.agents.events")

EmitFn = Callable[[dict[str, Any]], "str | None | Awaitable[str | None]"]


class Emitter:
    def __init__(self, emit: EmitFn, *, job_id: str, impl: str = "live"):
        self._emit = emit
        self.job_id = job_id
        self.impl = impl  # "live" or "stub": stub agent text is code-written
        self.ids: list[str] = []

    async def _call(self, payload: dict[str, Any]) -> str | None:
        out = self._emit(payload)
        if inspect.isawaitable(out):
            out = await out
        return out

    async def stage(self, text: str | None) -> None:
        await self._call({"stage": text})

    async def send(
        self,
        *,
        sender: str,
        recipient: str,
        type: str,
        text: str,
        round: int | None = None,
        proposal_id: str | None = None,
        reply_to_event_id: str | None = None,
        model_written: bool = False,
        home_views: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> str | None:
        source = "model" if (model_written and self.impl == "live") else "system_template"
        data = dict(data or {})
        if model_written and self.impl != "live":
            data["agent_impl"] = self.impl
        event = {
            "job_id": self.job_id,
            "sender": sender,
            "recipient": recipient,
            "type": type,
            "text": text,
            "round": round,
            "proposal_id": proposal_id,
            "reply_to_event_id": reply_to_event_id,
            "source": source,
            "home_views": home_views,
            "data": data,
        }
        eid = await self._call(event)
        if eid:
            self.ids.append(eid)
        return eid
