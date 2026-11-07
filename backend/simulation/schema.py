"""Canonical schemas (PRD §10). Field names are fixed; B mirrors them in frontend/src/types.ts."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

HomeId = Literal["A", "B", "C"]
HOME_IDS: tuple[str, ...] = ("A", "B", "C")
TariffMode = Literal["tou", "flat"]
EditableField = Literal["deadline_slot", "earliest_slot", "preferred_start_slot"]
EDITABLE_FIELDS: tuple[str, ...] = ("deadline_slot", "earliest_slot", "preferred_start_slot")
EventType = Literal[
    "request", "proposal", "review", "counteroffer", "tool_call",
    "tool_result", "validation", "commit", "error", "info",
]
JobStatus = Literal["queued", "running", "awaiting_confirmation", "completed", "failed"]


class Task(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    home_id: HomeId
    name: str
    power_kw: float
    duration_slots: int
    earliest_slot: int
    deadline_slot: int
    preferred_start_slot: int
    interruptible: bool = False


class ScheduleEntry(BaseModel):
    task_id: str
    home_id: HomeId
    start_slot: int
    duration_slots: int
    power_kw: float


class HomeMetrics(BaseModel):
    energy_kwh: float
    variable_cost_usd: float
    peak_kw: float


class Metrics(BaseModel):
    energy_kwh: float
    variable_cost_usd: float
    peak_kw: float
    missed_deadlines: int
    capacity_violations: int
    tasks_completed: int
    tasks_total: int
    per_home: dict[str, HomeMetrics]


class Home(BaseModel):
    id: HomeId
    name: str
    color: str
    preferences: dict[str, Any] = Field(default_factory=dict)


class Snapshot(BaseModel):
    """Everything the engine needs, built by the backend. JSON-serializable so C can pass it over MCP.

    Model arguments never replace these fields: the backend builds every snapshot.
    """
    scenario_id: str = "powersync-evening-v2"
    generation: int = 0
    requirements_version: int = 0
    revision: int = 0
    horizon_start: str = "2026-07-15T18:00:00-04:00"
    slot_minutes: int = 15
    slots: int = 96
    capacity_kw: float
    capacity_tolerance_kw: float = 0.001
    tariff_mode: TariffMode
    tariff_label: str
    tariff_usd_per_kwh: list[float]
    background_kw_by_home: dict[str, float]
    homes: list[Home]
    tasks: list[Task]

    def task_map(self) -> dict[str, Task]:
        return {t.id: t for t in self.tasks}


class ProposedEdit(BaseModel):
    task_id: str
    field: EditableField
    old_value: int
    new_value: int
    old_time: str
    new_time: str


class ProposedEdits(BaseModel):
    edits: list[ProposedEdit]


class PendingChange(BaseModel):
    id: str
    home_id: HomeId
    proposed_edits: ProposedEdits
    explanation: str
    prepared_revision: int
    request_id: str
    job_id: str
    feasible: bool
    infeasible_reasons: list[str] = Field(default_factory=list)
    status: Literal["pending", "confirmed", "rejected", "stale"] = "pending"
    created_at: str


class AgentEvent(BaseModel):
    id: str
    sequence: int
    job_id: Optional[str] = None
    sender: str
    recipient: str
    type: EventType
    text: str = Field(max_length=800)
    round: Optional[int] = None
    proposal_id: Optional[str] = None
    reply_to_event_id: Optional[str] = None
    source: Literal["model", "system_template"] = "system_template"
    home_views: Optional[dict[str, str]] = None  # never sent to clients as-is
    data: Optional[dict[str, Any]] = None
    timestamp: str
    revision: int


class Job(BaseModel):
    id: str
    kind: Literal["message", "action", "coordinate"]
    home_id: Optional[HomeId] = None
    request_id: Optional[str] = None
    status: JobStatus = "queued"
    stage: Optional[str] = None
    result: Optional[dict[str, Any]] = None  # always has outcome and message when set
    error: Optional[str] = None  # "CODE: message"
    created_at: str
    updated_at: str


# ---------- request bodies ----------

class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_id: str
    text: str = Field(min_length=1, max_length=1000)
    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: Optional[int] = None


class ActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_id: str
    action: Literal["confirm_change", "reject_change"]
    pending_change_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: Optional[int] = None


class TariffBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tariff_mode: TariffMode


class CoordinateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    request_id: Optional[str] = None
