# skills/config_translation/adapter.py
"""Adapter for config_translation skill — calls module service directly.

No HTTP. No retired translate API. No external dependency.
translate(payload) — accepts payload dict, calls module service.
review(payload)  — accepts payload dict, reads workspace state.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any
from modules.config_translation.backend.schemas import TranslateRequest
from modules.config_translation.backend.service import translate_config

ROOT = Path(__file__).resolve().parent.parent.parent


def translate(payload: Dict[str, Any]) -> dict:
    """Translate using the embedded config_translation module.

    Args:
        payload: dict with keys:
            source_config (str): source device config text
            filepath (str, optional): workspace-relative file path to read config from.
                Used when source_config is empty. Preferred for large configs.
            workspace_id (str, optional): workspace ID for filepath resolution, default "default"
            source_vendor (str, optional): vendor hint, default "auto"
            target_vendor (str, optional): target vendor, default "huawei"

    Returns:
        dict with keys: ok, deployable_config, manual_review, audit, etc.
    """
    source_config = payload.get("source_config", payload.get("user_input", ""))
    filepath = payload.get("filepath", "")
    workspace_id = payload.get("workspace_id", "default")

    # If filepath is provided and source_config is empty, read from file
    if filepath and not source_config:
        try:
            from tool_runtime.path_security import safe_workspace_path
            target = safe_workspace_path(workspace_id, filepath)
            if not target.is_file():
                return {"ok": False, "error": f"file not found: {filepath}"}
            if target.stat().st_size > 1024 * 1024:
                return {"ok": False, "error": "file too large (>1MB)"}
            with target.open("rb") as stream:
                if b"\x00" in stream.read(1024):
                    return {"ok": False, "error": "binary file cannot be translated"}
            source_config = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "error": f"read error: {str(e)}"}

    source_vendor = payload.get("source_vendor", "auto")
    target_vendor = payload.get("target_vendor", "huawei")

    req = TranslateRequest(
        source_config=source_config,
        source_vendor=source_vendor,
        target_vendor=target_vendor,
    )
    try:
        result = translate_config(req)
        return {"ok": True, **result.as_dict()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def review(payload: Dict[str, Any]) -> dict:
    """Context QA: answer questions about the last translation result.

    Args:
        payload: dict with optional workspace_id (default: "default")

    Returns:
        dict with last translation summary, review count, unsupported count.
    """
    workspace_id = payload.get("workspace_id", "default")
    ws_dir = ROOT / "workspaces" / workspace_id
    state_path = ws_dir / "sys" / "state.json"

    if not state_path.is_file():
        return {
            "ok": False,
            "status": "no_context",
            "message": "当前没有可解释的翻译结果，请先执行一次配置翻译。",
            "manual_review_count": 0,
            "unsupported_count": 0,
        }

    try:
        state = json.loads(state_path.read_text())
    except Exception:
        return {"ok": False, "status": "no_context", "message": "无法读取工作区状态。"}

    last_intent = state.get("last_intent", "")
    if not last_intent and not state.get("last_result_summary"):
        return {
            "ok": False,
            "status": "no_context",
            "message": "当前没有可解释的翻译结果，请先执行一次配置翻译。",
            "manual_review_count": 0,
            "unsupported_count": 0,
        }

    counts = state.get("last_result_counts", {})
    mr_samples = state.get("last_manual_review_samples", [])
    us_samples = state.get("last_unsupported_samples", [])

    return {
        "ok": True,
        "status": "context_available",
        "message": (
            f"最近一次翻译 (intent={last_intent}): "
            f"{counts.get('deployable_lines', 0)} 条可部署, "
            f"{counts.get('manual_review_count', 0)} 条需人工复核, "
            f"{counts.get('unsupported_count', 0)} 条不支持自动翻译。"
        ),
        "manual_review_count": counts.get("manual_review_count", 0),
        "unsupported_count": counts.get("unsupported_count", 0),
        "manual_review_samples": mr_samples[:5],
        "unsupported_samples": us_samples[:5],
        "last_intent": last_intent,
        "deployable_lines": counts.get("deployable_lines", 0),
    }
