# agent/runtime/tool_execution/retry_policy.py
"""Retry policy helpers for tool execution."""

import json


def detect_repeated_tool_failure(tool_results: list) -> dict | None:
    """Detect an identical failed tool result repeated back-to-back."""
    if len(tool_results) < 2:
        return None
    previous, current = tool_results[-2], tool_results[-1]
    if previous.get("ok") or current.get("ok"):
        return None
    if previous.get("tool_id") != current.get("tool_id"):
        return None
    previous_errors = tuple(previous.get("errors") or [])
    current_errors = tuple(current.get("errors") or [])
    if previous_errors != current_errors:
        return None
    if not current_errors and previous.get("summary") != current.get("summary"):
        return None
    return current


def should_retry_for_required_tools(context, all_tool_results: list, step: int) -> bool:
    if step != 1 or all_tool_results:
        return False
    if getattr(context, "metadata", {}).get("required_tool_retry_used"):
        return False
    scene = (getattr(context, "safe_context", {}) or {}).get("tool_scene") or {}
    if not isinstance(scene, dict) or scene.get("needs_clarification"):
        return False
    required_steps = [
        s for s in scene.get("tool_plan", []) or []
        if isinstance(s, dict) and s.get("required") and s.get("tool_candidates")
    ]
    visible = set(getattr(context, "visible_tool_ids", []) or getattr(context, "metadata", {}).get("visible_tools", []) or [])
    if not required_steps or not visible:
        return False
    return any(set(step_def.get("tool_candidates") or []) & visible for step_def in required_steps)


def required_tool_retry_prompt(context) -> str:
    scene = (getattr(context, "safe_context", {}) or {}).get("tool_scene") or {}
    required = []
    if isinstance(scene, dict):
        for step_def in scene.get("tool_plan", []) or []:
            if isinstance(step_def, dict) and step_def.get("required"):
                required.append({
                    "step": step_def.get("step"),
                    "goal": step_def.get("goal"),
                    "tool_candidates": step_def.get("tool_candidates"),
                })
    return (
        "The current user request requires tool execution before a final answer. "
        "Do not answer from memory or general knowledge. Call one of the exposed "
        "functions for the first required step now. Required plan: "
        + json.dumps(required[:4], ensure_ascii=False)
    )
