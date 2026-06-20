# agent/modules/config_analysis/service.py
"""Unified config analysis module service.

Directory-level entrypoint for all config-related operations.
Tool handlers call run_config_analysis() instead of individual functions.
"""

from __future__ import annotations

from typing import Any


VALID_ACTIONS = {
    "parse",
    "translate",
    "extract_interfaces",
    "extract_routes",
    "diff",
    "summarize",
}


def run_config_analysis(
    action: str,
    *,
    workspace_id: str = "default",
    filepath: str = "",
    source_config: str = "",
    target_vendor: str = "",
    source_vendor: str = "",
    **kwargs,
) -> dict[str, Any]:
    """Unified config analysis dispatcher."""
    action = (action or "").strip()

    if action not in VALID_ACTIONS:
        return {
            "ok": False,
            "tool_id": "config.analysis.run",
            "status": "failed",
            "summary": f"unsupported config action: {action}",
            "errors": ["unsupported_action"],
        }

    if action == "translate":
        from agent.modules.config_translation.service import translate_config
        return translate_config(
            source_config=source_config,
            source_vendor=source_vendor,
            target_vendor=target_vendor,
            workspace_id=workspace_id,
        )

    if action == "parse":
        return _stub_action("parse", "Config parsing is planned but not yet wired to a module service.")

    if action == "extract_interfaces":
        return _stub_action("extract_interfaces", "Interface extraction is planned but not yet wired.")

    if action == "extract_routes":
        return _stub_action("extract_routes", "Route extraction is planned but not yet wired.")

    if action == "diff":
        return _stub_action("diff", "Config diff is not implemented yet.")

    if action == "summarize":
        return _stub_action("summarize", "Config summarize is not implemented yet.")

    return _stub_action(action, f"Action '{action}' is not implemented.")


def _stub_action(action: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool_id": "config.analysis.run",
        "status": "not_implemented",
        "summary": message,
        "errors": [f"{action}_not_implemented"],
    }
