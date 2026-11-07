"""Shared fixtures for the agent tests: the real engine and scenario.json, stub models only."""

from __future__ import annotations

import os

import pytest

os.environ.pop("OPENROUTER_API_KEY", None)  # tests never call the real model
os.environ.pop("POWERSYNC_ENGINE_MODULE", None)  # backend.simulation.engine_api

from backend.simulation.engine_api import scenario_snapshot  # noqa: E402


@pytest.fixture
def snapshot() -> dict:
    return scenario_snapshot("tou")


@pytest.fixture
def flat_snapshot() -> dict:
    return scenario_snapshot("flat")
