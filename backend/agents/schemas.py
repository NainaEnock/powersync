"""Pydantic models for everything the model returns. Extra fields are ignored."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EditField = Literal["deadline_slot", "earliest_slot", "preferred_start_slot"]


class InterpretEdit(BaseModel):
    task_id: str
    field: EditField
    new_time: str = Field(description="24-hour HH:MM")


class InterpretOutput(BaseModel):
    understood: bool
    edits: list[InterpretEdit] = Field(default_factory=list, max_length=4)
    question: str | None = None


class ReviewOutput(BaseModel):
    home_id: str
    proposal_id: str
    accept: bool
    objections: list[str] = Field(default_factory=list, max_length=5)
    request_option_id: str | None = None
    public_message: str = Field(max_length=1200)


class NeighborReply(BaseModel):
    agree: bool
    public_message: str = Field(max_length=1200)
