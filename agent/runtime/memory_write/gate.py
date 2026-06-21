# agent/runtime/memory_write/gate.py
"""MemoryGate — selects the memory gating strategy based on workspace config.

Two modes:
  - "rule_only":  prefix dedupe + confidence threshold + count cap (deterministic)
  - "llm_first":  LLM quality scoring + summary generation, with rule fallback
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.runtime.memory_write.models import MemoryCandidate


class MemoryGateMode(str, Enum):
    RULE_ONLY = "rule_only"
    LLM_FIRST = "llm_first"


# Confidence floor: candidates below this are dropped BEFORE dedupe
CONFIDENCE_FLOOR: dict[str, float] = {
    "rule_only": 0.0,      # rule_only keeps everything (dedupe handles pruning)
    "llm_first": 0.0,       # LLM gate has its own scoring, so let everything through
}


def get_gate_mode(workspace_id: str = "default") -> MemoryGateMode:
    """Read memory_gating setting from workspace state.

    Falls back to RULE_ONLY if the setting is absent or invalid.
    """
    try:
        from workspace.manager import get_workspace_state
        state = get_workspace_state(workspace_id)
        raw = state.get("memory_gating", "").strip().lower()
        if raw in ("llm_first", "llm", "llm-first", "llm_first"):
            return MemoryGateMode.LLM_FIRST
    except Exception:
        pass
    return MemoryGateMode.RULE_ONLY


def set_gate_mode(workspace_id: str, mode: str) -> bool:
    """Update memory_gating setting in workspace state.

    Args:
        workspace_id: target workspace
        mode: "rule_only" or "llm_first"

    Returns:
        True on success, False on failure
    """
    try:
        valid = mode.strip().lower()
        if valid not in ("rule_only", "llm_first"):
            return False
        from workspace.manager import update_workspace_state
        update_workspace_state(workspace_id, {"memory_gating": valid})
        return True
    except Exception:
        return False


def apply_confidence_floor(
    candidates: list[MemoryCandidate],
    mode: MemoryGateMode,
) -> list[MemoryCandidate]:
    """Drop candidates below the confidence floor for the given mode.

    For rule_only: floor is 0.0, so everything passes.
    For llm_first: floor is 0.0, LLM gate handles scoring.

    This is a pre-filter that runs before dedupe to reduce downstream work.
    """
    floor = CONFIDENCE_FLOOR.get(mode.value, 0.0)
    if floor <= 0:
        return candidates
    return [c for c in candidates if c.confidence >= floor]
