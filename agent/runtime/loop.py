# agent/runtime/loop.py
"""TurnRunner — thin entry point delegating to TurnRunner.

The main function run_turn() orchestrates the agentic loop by delegating
to the stage-pipeline architecture in agent.runtime.runner.  Supporting
functions have been extracted to dedicated modules:
- runner.py — TurnRunner (agentic loop orchestration)
- turn_state.py — TurnRuntimeState dataclass
- result_builder.py — AgentResult construction helpers
- runtime_events.py — RuntimeEventBus
- stages/context.py — ContextStage
- stages/messages.py — MessageStage
- stages/model.py — ModelStage
- stages/persistence.py — PersistenceStage
- tool_execution/pipeline.py — ToolExecutionPipeline
- turn_persistence.py — run records, messages, trace events
- message_builder.py — initial message construction
- tool_result_utils.py — tool call standardization, payload formatting
- hook_runner.py — lifecycle hook execution
- token_manager.py — token tracking, limits, compaction
- tool_decision.py — decision transparency blocks
- permission_check.py — permission matrix, approval routing
"""

import os as _os

from agent.runtime.result import AgentResult

MAX_STEPS = 24  # v3.10: raised from 8 for long multi-step tasks

# ── approval timeout ──

# MAX_STEPS is configurable through three layers (highest wins):
#   1. env var AGENT_MAX_STEPS               — operator-level ops override
#   2. turn.metadata["max_steps"]            — per-turn override (e.g. agent.team spawns)
#   3. session.metadata["max_steps"]         — per-session override
#   4. MAX_STEPS module constant (24)        — default fallback
# Sub-agents get a stricter upper bound (32) regardless of override to keep
# recursion depth bounded.

MAX_STEPS_ENV = int(_os.getenv("AGENT_MAX_STEPS", "0") or 0)
MAX_STEPS_SUBAGENT_CEILING = int(_os.getenv("AGENT_MAX_STEPS_SUBAGENT_CEILING", "32") or 32)


def _coerce_int_steps(value, default: int) -> int:
    """Coerce arbitrary metadata / env value to a positive int with sane bounds.

    Returns default when value is None / unparseable / out of [1, 1024].
    """
    if value is None:
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 1 or n > 1024:
        return default
    return n


def _resolve_max_steps(session=None, turn=None, *, is_sub_agent: bool = False) -> int:
    """Resolve the effective MAX_STEPS for a turn.

    Precedence (highest wins): turn.metadata > session.metadata > env > module default.
    Sub-agent turns are additionally capped at MAX_STEPS_SUBAGENT_CEILING.
    """
    default = MAX_STEPS
    # 1. env override
    if MAX_STEPS_ENV > 0:
        default = MAX_STEPS_ENV
    # 2. per-session metadata
    sess_meta = getattr(session, 'metadata', None)
    if isinstance(sess_meta, dict):
        default = _coerce_int_steps(sess_meta.get('max_steps'), default)
    # 3. per-turn metadata (highest priority)
    turn_meta = getattr(turn, 'metadata', None)
    if isinstance(turn_meta, dict):
        default = _coerce_int_steps(turn_meta.get('max_steps'), default)
    # Sub-agent safety ceiling
    if is_sub_agent and default > MAX_STEPS_SUBAGENT_CEILING:
        default = MAX_STEPS_SUBAGENT_CEILING
    return default


# v3.2.0 (Guardian): approval wait timeout is configurable per-agent-class.
# Sub-agents get a shorter window so a slow parent agent doesn't accumulate
# approval waits across turns. Env vars override the defaults.

_APPROVAL_TIMEOUT_DEFAULT_S = float(_os.getenv("APPROVAL_TIMEOUT_DEFAULT_S", "120"))
_APPROVAL_TIMEOUT_SUBAGENT_S = float(_os.getenv("APPROVAL_TIMEOUT_SUBAGENT_S", "60"))


def _get_approval_timeout(is_sub_agent: bool = False) -> float:
    """Return the approval-wait timeout for this agent class."""
    return _APPROVAL_TIMEOUT_SUBAGENT_S if is_sub_agent else _APPROVAL_TIMEOUT_DEFAULT_S


def run_turn(session, turn, services=None, restricted_tool_router=None) -> AgentResult:
    """Execute a single turn: user message -> LLM -> tools -> LLM -> ... -> final answer.

    Phase 3: restricted_tool_router is used by sub-agents to limit tool access.
    
    v3.10: Supports runtime_mode switching via AGENT_RUNTIME env var:
      - "langgraph" → uses GraphRunner (StateGraph + checkpoint + streaming)
      - default → uses TurnRunner (while loop, stable)
    """
    runtime_mode = _os.getenv("AGENT_RUNTIME", "").lower()
    
    if runtime_mode == "langgraph":
        try:
            from agent.runtime.graph_runner import GraphRunner
            max_steps = _resolve_max_steps(
                session=session, turn=turn,
                is_sub_agent=bool(getattr(session, 'is_sub_agent', False))
            )
            runner = GraphRunner(max_steps=max_steps)
            # Build state from session/turn
            from agent.runtime.turn_state import TurnRuntimeState
            state = TurnRuntimeState(session=session, turn=turn, services=services)
            result = runner.run(state, thread_id=session.session_id if hasattr(session, 'session_id') else "default")
            # Convert dict result to AgentResult
            from agent.runtime.result import AgentResult
            return AgentResult(
                final_response=result.get("answer", ""),
                ok="error" not in result or result.get("error") is None,
                error=result.get("error"),
                turn_id=turn.turn_id if hasattr(turn, 'turn_id') else "",
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("GraphRunner failed, falling back to TurnRunner: %s", e)
    
    from agent.runtime.runner import TurnRunner
    return TurnRunner(
        session=session,
        turn=turn,
        services=services,
        restricted_tool_router=restricted_tool_router,
    ).run()
