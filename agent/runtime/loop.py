"""Current runtime entrypoint.

The public runtime is SSOT Runtime. This module remains the runtime package's stable
entrypoint name; it delegates directly to ``run_ssot_turn`` and contains no
alternate execution path.
"""

from __future__ import annotations

from agent.runtime.result import AgentResult
from agent.runtime.ssot_runtime import run_ssot_turn


def run_turn(session, turn, services=None) -> AgentResult:
    """Run a turn through SSOT Runtime."""
    return run_ssot_turn(session, turn, services)
