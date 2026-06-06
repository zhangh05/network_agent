# context/builder.py
"""Context builder — builds ContextBundle from workspace state and refs."""

from context.schemas import (ContextBundle, ExecutionContext, SafeLLMContext,
                              ContextRef, ContextItem, ContextBudget)
from context.resolver import resolve_context_ref


def build_context_bundle(workspace_id: str, user_input: str = "",
                         intent: str = "", capability_id: str = "",
                         payload: dict = None, context_ref: str = "",
                         ui_context: dict = None, budget: ContextBudget = None,
                         run_id: str = "", trace_id: str = "", job_id: str = "",
                         state_context: dict = None) -> ContextBundle:
    """Build a complete ContextBundle from all available sources."""

    budget = budget or ContextBudget()
    ctx = state_context or {}

    # 1. Resolve ref
    ref = resolve_context_ref(workspace_id, context_ref, payload, ui_context)

    # 2. Build ExecutionContext
    exec_ctx = ExecutionContext(
        workspace_id=workspace_id, run_id=run_id, job_id=job_id,
        trace_id=trace_id, capability_id=capability_id, intent=intent,
        payload_refs=list(payload.keys()) if payload else [],
        source_config_artifact_id=payload.get("artifact_id", "") if payload else "",
        selected_artifact_id=ref.ref_id if ref.ref_type == "artifact" else "",
    )

    # 3. Build SafeLLMContext
    safe = SafeLLMContext(
        workspace_id=workspace_id, intent=intent, user_input=user_input,
        context_ref=ref,
        artifact_refs=ctx.get("artifact_refs", [])[:budget.max_artifact_refs],
        citations=ctx.get("citations", []),
        warnings=list(ctx.get("warnings", [])),
    )

    # Load workspace state summary
    try:
        from workspace.manager import get_workspace_state
        ws = get_workspace_state(workspace_id)
        safe.last_result_summary = ws.get("last_result_summary", "")
        safe.run_summary = {"last_intent": ws.get("last_intent", ""),
                            "last_active_module": ws.get("last_active_module", "")}
        safe.job_summary = ws.get("job_stats", {})
        exec_ctx.workspace_state = {k: v for k, v in ws.items()
                                    if k not in ("source_config", "deployable_config")}
    except Exception:
        pass

    # Load memory hits
    try:
        from memory.retriever import retrieve_for_context
        safe.memory_hits = retrieve_for_context(user_input, workspace_id, limit=budget.max_memory_hits)
    except Exception:
        pass

    # Build budget
    budget.used_items = 5  # approximate
    budget.used_chars = sum(len(str(v)) for v in safe.artifact_refs) + len(user_input)

    # Build bundle
    bundle = ContextBundle(
        workspace_id=workspace_id, run_id=run_id, job_id=job_id,
        trace_id=trace_id, intent=intent, capability_id=capability_id,
        user_input=user_input, context_ref=ref,
        execution_context=exec_ctx, safe_llm_context=safe,
        budget=budget,
    )

    return bundle
