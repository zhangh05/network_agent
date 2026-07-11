# agent/runtime/decision_report/builder.py
"""Decision Report builder — assembles a report from turn execution data."""

from __future__ import annotations

from agent.runtime.utils import now_iso


def build_decision_report(
    *,
    run_id: str,
    session_id: str,
    workspace_id: str,
    context,
    result,
    result_dict: dict = None,
) -> dict:
    """Build a complete DecisionReport from turn execution artefacts.

    Pulls from:
      - context.metadata (scene, routing, tool planning decision, violations)
      - result (tool calls, errors, warnings)
      - trace (real/synthetic/missing counts — filled later by writer)

    Returns a dict ready for redaction and writing.
    """
    from agent.runtime.decision_report.models import REPORT_SCHEMA_VERSION

    ctx_meta = getattr(context, "metadata", None) or {}

    # ── Scene decision ──
    scene_decision = _safe_structure(ctx_meta.get("scene_decision", {}))

    # ── Business capability guidance ──
    planning_caps = {}
    if isinstance(ctx_meta.get("tool_planning_decision"), dict):
        planning_caps = ctx_meta["tool_planning_decision"].get("business_capabilities") or {}
    business_capabilities = _safe_structure(
        planning_caps or ctx_meta.get("business_capabilities", []),
    )

    # ── Tool planning decision ──
    tpd = ctx_meta.get("tool_planning_decision", {})
    if isinstance(tpd, dict):
        from agent.runtime.tool_planning.decision import redact_decision_for_report
        tool_planning_decision = redact_decision_for_report(tpd)
    else:
        tool_planning_decision = {}

    # ── Visibility violations ──
    visibility_violations = [
        dict(v) if isinstance(v, dict) else {"raw": str(v)[:200]}
        for v in (ctx_meta.get("visibility_violations") or [])
    ]

    # ── Tool execution summary ──
    rd = result_dict or _result_to_dict(result)
    tool_calls = _safe_tool_calls(rd.get("tool_calls") or [])
    exec_summary = _build_execution_summary(tool_calls)

    # ── Warnings / errors ──
    turn_warnings = list(rd.get("warnings") or [])
    errors = list(rd.get("errors") or [])

    # ── Retrieval decision (P1-B: populated by RetrievalTriggerPolicy) ──
    retrieval_decision = ctx_meta.get("retrieval_decision", {})
    if isinstance(retrieval_decision, dict):
        rd_copy = dict(retrieval_decision)
        # Remove _pre_decisions (internal audit only, not for external report)
        rd_copy.pop("_pre_decisions", None)
        retrieval_decision = rd_copy
    else:
        retrieval_decision = {
            "memory": {"status": "not_evaluated"},
            "knowledge": {"status": "not_evaluated"},
        }

    decision_status = "complete" if all((
        scene_decision,
        tool_planning_decision,
        retrieval_decision,
    )) else "degraded"

    # Check for provider errors in metadata
    model_responses = ctx_meta.get("model_responses", [])
    if isinstance(model_responses, list):
        for mr in model_responses:
            if isinstance(mr, dict) and mr.get("provider_error"):
                errors.append(f"provider_error: {str(mr.get('provider_error'))[:300]}")

    # ── Trace summary (filled with real/synthetic/missing) ──
    # The writer will replace/fill this when the trace is available.
    trace_summary = {
        "real_event_count": 0,
        "synthetic_event_count": 0,
        "missing_event_count": 0,
    }

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": str(run_id),
        "session_id": str(session_id),
        "workspace_id": str(workspace_id),
        "created_at": now_iso(),
        "scene_decision": scene_decision,
        "business_capabilities": business_capabilities,
        "tool_planning_decision": tool_planning_decision,
        "visibility_violations": visibility_violations,
        "retrieval_decision": retrieval_decision,
        "decision_status": decision_status,
        "tool_execution_summary": exec_summary,
        "trace_summary": trace_summary,
        "warnings": [
            str(w)[:500] for w in turn_warnings
        ],
        "errors": [
            str(e)[:500] for e in errors
        ],
        "redaction_applied": True,
    }

    return report


# ── Helpers ────────────────────────────────────────────────────────────

def _result_to_dict(result) -> dict:
    """Safely convert AgentResult to dict."""
    if result is None:
        return {}
    try:
        return result.to_dict() if hasattr(result, "to_dict") else {}
    except Exception:
        return {}


def _safe_dict(obj, max_items: int = 30) -> dict:
    """Return a safe shallow copy of a dict-like object."""
    if not isinstance(obj, dict):
        return {}
    out = {}
    for k, v in list(obj.items())[:max_items]:
        if isinstance(v, (dict, list)):
            out[str(k)] = str(type(v).__name__)
        elif isinstance(v, str):
            out[str(k)] = v[:200]
        elif isinstance(v, (int, float, bool)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v)[:200]
    return out


def _safe_structure(value, *, depth: int = 0):
    """Preserve nested decision structure while bounding size and depth."""
    if depth >= 5:
        return "[max_depth]"
    if isinstance(value, dict):
        return {
            str(key): _safe_structure(item, depth=depth + 1)
            for key, item in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple)):
        return [
            _safe_structure(item, depth=depth + 1)
            for item in list(value)[:50]
        ]
    if isinstance(value, str):
        return value[:500] + ("...[truncated]" if len(value) > 500 else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


def _safe_tool_calls(tool_calls: list) -> list[dict]:
    """Extract safe fields from tool call records."""
    safe: list[dict] = []
    for call in list(tool_calls or [])[:50]:
        if not isinstance(call, dict):
            continue
        safe.append({
            "tool_id": str(call.get("tool_id", call.get("tool_name", ""))),
            "ok": bool(call.get("ok", True)),
            "summary": str(call.get("summary", ""))[:200],
            "errors": [
                str(e)[:200] for e in (call.get("errors") or [])
            ][:5],
        })
    return safe


def _build_execution_summary(tool_calls: list[dict]) -> dict:
    """Classify tool calls into called/blocked/failed/succeeded."""
    called = []
    blocked = []
    failed = []
    succeeded = []

    for tc in tool_calls:
        tid = tc.get("tool_id", "unknown")
        called.append(tid)
        if tc.get("ok"):
            succeeded.append(tid)
        else:
            errors = tc.get("errors") or []
            if any("visibility_violation" in str(e) for e in errors):
                blocked.append(tid)
            else:
                failed.append(tid)

    return {
        "called": called,
        "blocked": blocked,
        "failed": failed,
        "succeeded": succeeded,
    }
