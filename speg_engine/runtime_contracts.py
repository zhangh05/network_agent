"""
SPEG v4 runtime contracts — system-level invariants that the
runtime MUST uphold.

These are not policies and not configuration. They are the
non-negotiable rules that the runtime asserts on every turn.

Three contracts:

  * ``TOOL_TRUTH_SINGLE_SOURCE`` — there is exactly one resolver
    for tool outcome (``speg_engine.tool_runtime.resolve_tool_outcome``)
    and no path may construct a ``ToolResult(success=True, ...)``
    without going through it. The previous v3.10 helper
    (``_resolve_success_flag``) is now a thin internal alias.

  * ``CONTEXT_EVENT_STREAM_ONLY`` — conversation context flows
    through a single builder (``agent.runtime.speg_adapter.build_context_events``)
    that merges the in-memory session history with the
    on-disk ``SessionMessageStore``, sorts by ``created_at``, and
    deduplicates. No other code path may read either source
    directly for context injection.

  * ``EXECUTION_OBLIGATION_ENFORCED`` — for any user intent that
    requires tool execution, the planner MUST return a non-empty
    graph; an empty plan for a task-intent request raises
    ``ExecutionObligationViolation`` from the planner. The
    engine's empty-plan guard is now a defensive layer, not the
    primary enforcement.

The constants are class-level booleans so they can be referenced
as ``ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE`` from anywhere.
They are checked in ``SPEGEngine.run()`` at the top of every
turn — flipping any of them to ``False`` is a deliberate
"contract OFF" escape hatch for debugging only.

Background: v3.10 closed three classes of bug (handler success
flag, prompt silent fallback, JSON truncation) but left
system-level contracts implicit. v4 makes them explicit,
asserts them, and routes the corresponding code through
single sources of truth.
"""


class ExecutionObligationViolation(Exception):
    """Raised when the planner returns an empty plan for an intent
    that requires tool execution.

    This is a *fail-fast* signal: the planner MUST NOT silently
    return an empty graph for a task-intent request. The engine
    catches the exception and produces a structured error result
    (matching the v3.14 empty-plan task-intent guard), but the
    planner itself never coerces an obligation-required request
    into a no-op.
    """


class ExecutionContract:
    """v4.1 system-level runtime contracts.

    v4.1 additions:
      * ``CONTEXT_CAUSAL_ORDER_ONLY`` — conversation context is
        ordered by causal_index, not created_at.
      * ``PLAN_STRICT_SCHEMA_ENFORCED`` — every planner output
        passes through PlanSchema.validate_raw before compilation.
      * ``DIAGNOSTIC_PRESERVATION_REQUIRED`` — ToolResult always
        carries error_code_raw and error_code_norm；no error
        signal is dropped mid-pipeline.
    """

    # [1] Tool truth closure — exactly one resolver, no silent
    #     success=True default outside the resolver.
    TOOL_TRUTH_SINGLE_SOURCE: bool = True

    # [2] Context closure — exactly one builder for the merged
    #     in-memory + on-disk conversation event stream.
    CONTEXT_EVENT_STREAM_ONLY: bool = True

    # [3] Execution obligation — empty plan for task intent is
    #     forbidden; planner raises ExecutionObligationViolation.
    EXECUTION_OBLIGATION_ENFORCED: bool = True

    # ── v4.1 ──────────────────────────────────────────────────────

    # [4] Causal ordering — context is sorted by causal_index,
    #     not created_at. No timestamp-based sort anywhere.
    CONTEXT_CAUSAL_ORDER_ONLY: bool = True

    # [5] Plan strict schema — every planner output is validated
    #     by PlanSchema.validate_raw(). Malformed plans raise
    #     SchemaValidationError, empty-task plans raise
    #     ExecutionObligationViolation.
    PLAN_STRICT_SCHEMA_ENFORCED: bool = True

    # [6] Diagnostic preservation — ToolResult.error_code_raw
    #     and .error_code_norm are always populated for failures.
    #     No error_code disappears mid-pipeline.
    DIAGNOSTIC_PRESERVATION_REQUIRED: bool = True


__all__ = [
    "ExecutionContract",
    "ExecutionObligationViolation",
]
