# agent/nodes/context_loader.py
"""Context loader — collects context fragments and injects into agent state.

Uses the composable ContextFragment system (inspired by Codex's
FragmentRegistration pattern). Each context source is a self-contained
fragment with its own token budget, error handling, and priority.
"""

import logging

from agent.state import NetworkAgentState
from context.fragments import collect_context

logger = logging.getLogger(__name__)


def load_context(state: NetworkAgentState) -> NetworkAgentState:
    """Load context using the composable fragment system.

    Delegates to context.fragments.collect_context() which runs all
    registered fragments in priority order, each independently handling
    its own data fetch, error recovery, and token budgeting.

    Replaces the previous 5 ad-hoc try/except blocks with a unified,
    extensible fragment pipeline.
    """
    # Collect all context fragments into state.context
    state = collect_context(state)

    # ── Trace: context_loaded ──
    frag_info = state.context.get("fragments", {})
    n_memory = len(state.context.get("memory_hits", []))
    has_last = state.context.get("last_result", {}).get("has_result", False)
    n_failed = len(frag_info.get("failed", []))
    tokens = frag_info.get("total_tokens_used", 0)

    status = "success" if n_failed == 0 else "degraded"
    state.trace_events.append({
        "event_id": "context_loaded",
        "trace_id": state.trace_id or "",
        "run_id": state.request_id,
        "workspace_id": state.workspace_id or "default",
        "event_type": "context_loaded",
        "name": "context_loaded",
        "status": status,
        "duration_ms": 0.0,
        "summary": (
            f"memory_hits={n_memory} last_result={has_last} "
            f"fragments_ok={len(frag_info.get('render_order', []))} "
            f"fragments_failed={n_failed} tokens={tokens}"
        ),
        "metadata": {"fragment_system": "v0.1", "total_tokens": tokens},
        "redaction_applied": False,
    })

    return state
