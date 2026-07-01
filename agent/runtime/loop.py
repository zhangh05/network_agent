"""Current runtime entrypoint.

The public runtime is SPEG. This module remains the runtime package's stable
entrypoint name; it delegates directly to ``run_speg_turn`` and contains no
alternate execution path.
"""

from __future__ import annotations

from agent.runtime.result import AgentResult
from agent.runtime.speg_adapter import run_speg_turn


def run_turn(session, turn, services=None) -> AgentResult:
    """Run a turn through SPEG."""
    return run_speg_turn(session, turn, services)
