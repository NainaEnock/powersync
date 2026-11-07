"""PowerSync agents. The backend uses these entry points:

    from backend.agents import interpret_request, coordinate_neighborhood

See backend/agents/README.md for signatures, the snapshot shape, emit, and results.
"""

from .interpreter import apply_edits, interpret_request
from .mcp_client import get_energy_tools
from .orchestrator import coordinate_neighborhood
from .stub_model import RuleStubModel, ScriptedModel

__all__ = [
    "interpret_request",
    "coordinate_neighborhood",
    "apply_edits",
    "get_energy_tools",
    "RuleStubModel",
    "ScriptedModel",
]
