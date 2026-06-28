# agent/modules/config_translation/service.py
"""Config Translation service — wraps the canonical translate_config implementation.

Exposes translate_config() for the TurnRunner → ToolRouter → ToolRegistry path.
Does NOT bypass the config_translation module.
Does NOT generate deployable_config directly from LLM.
Saves translated_config as an artifact with authoritative=false, deployable_config=false.
"""

import uuid
from typing import Optional


def translate_config(
    source_config: str,
    source_vendor: str = "",
    target_vendor: str = "",
    options: Optional[dict] = None,
    workspace_id: str = "default",
    session_id: str = "",
) -> dict:
    """Execute config translation via the canonical module service."""
    warnings = []
    errors = []

    if not source_config or not source_config.strip():
        return {
            "ok": False,
            "summary": "需要提供源配置文本。请粘贴网络设备配置后重试。",
            "source_vendor": source_vendor or "unknown",
            "target_vendor": target_vendor or "unknown",
            "line_count": 0,
            "translated_config": "",
            "manual_review_items": [],
            "warnings": [],
            "errors": ["missing_source_config"],
            "artifacts": [],
            "metadata": {},
        }

    source_vendor = source_vendor or "auto"
    target_vendor = target_vendor or "huawei"

    if source_vendor == "auto":
        try:
            from modules.config_translation.backend.client import detect_vendor
            detected = detect_vendor(source_config)
            source_vendor = detected or "auto"
        except Exception:
            pass

    try:
        from modules.config_translation.backend.schemas import TranslateRequest
        from modules.config_translation.backend.service import translate_config as _translate

        req = TranslateRequest(
            source_config=source_config.strip(),
            source_vendor=source_vendor,
            target_vendor=target_vendor,
        )
        result = _translate(req)
        result_dict = result.as_dict()

        raw_items = result_dict.get("manual_review_items", result_dict.get("manual_review", []))
        manual_review_items = _normalize_review_items(raw_items)
        quality = result_dict.get("quality_summary", {})
        audit = result_dict.get("audit", {})
        translated_config = result_dict.get("deployable_config", "")
        line_count = len(source_config.strip().splitlines())
        mr_count = len(manual_review_items)

        if quality.get("source_residue_count", 0) > 0 or quality.get("silent_drop_count", 0) > 0:
            warnings.append("quality_gate: source_residue or silent_drop detected, manual review required")

        # Save translated_config as artifact
        artifacts = []
        if translated_config:
            artifacts = _save_translation_artifact(
                translated_config, source_vendor, target_vendor,
                workspace_id, session_id, line_count, mr_count,
                manual_review_items, quality, warnings,
            )

        return {
            "ok": True,
            "summary": (
                f"翻译完成: {audit.get('counts', {}).get('deployable_count', 0)} 条可部署, "
                f"{mr_count} 条需人工复核, "
                f"{audit.get('counts', {}).get('unsupported_count', 0)} 条不支持自动翻译."
            ),
            "source_vendor": source_vendor,
            "target_vendor": target_vendor,
            "line_count": line_count,
            "translated_config": translated_config,
            "manual_review_items": manual_review_items,
            "manual_review_count": mr_count,
            "warnings": warnings + (result_dict.get("warnings", []) or []),
            "errors": errors,
            "artifacts": artifacts,
            "metadata": {
                "elapsed_ms": result_dict.get("elapsed_ms", 0),
                "quality_summary": quality,
                "audit": audit,
                "build_commit": result_dict.get("build_commit", ""),
                "manual_review_count": mr_count,
                "line_count": line_count,
            },
        }

    except Exception as e:
        return {
            "ok": False,
            "summary": f"配置翻译失败: {str(e)[:200]}",
            "source_vendor": source_vendor,
            "target_vendor": target_vendor,
            "line_count": 0,
            "translated_config": "",
            "manual_review_items": [],
            "manual_review_count": 0,
            "warnings": [],
            "errors": [f"translation_error: {str(e)[:200]}"],
            "artifacts": [],
            "metadata": {},
        }


def _normalize_review_items(raw_items: list) -> list:
    """Normalize manual_review_items to structured format."""
    normalized = []
    for i, item in enumerate(raw_items):
        if isinstance(item, str):
            normalized.append({
                "item_id": str(uuid.uuid4())[:8],
                "severity": "medium",
                "category": "unknown",
                "line_no": None,
                "source_text": item[:200],
                "translated_text": "",
                "reason": item[:200],
                "recommendation": "请人工复核后确认",
                "requires_human_review": True,
            })
        elif isinstance(item, dict):
            normalized.append({
                "item_id": item.get("item_id", str(uuid.uuid4())[:8]),
                "severity": item.get("severity", item.get("risk_level", "medium")),
                "category": _map_category(item.get("category", item.get("reason", "unknown"))),
                "line_no": item.get("line_no"),
                "source_text": item.get("source_excerpt", item.get("source_text", "")),
                "translated_text": item.get("translated_text", item.get("suggested_lines", "")),
                "reason": item.get("reason", item.get("source_excerpt", ""))[:200],
                "recommendation": item.get("recommendation", item.get("suggested_action", "请人工复核后确认")),
                "requires_human_review": True,
            })
    return normalized


def _map_category(raw: str) -> str:
    raw_lower = (raw or "").lower()
    if "syntax" in raw_lower or "residue" in raw_lower:
        return "syntax"
    if "semantic" in raw_lower or "near" in raw_lower:
        return "semantic"
    if "unsupported" in raw_lower or "not supported" in raw_lower:
        return "unsupported_feature"
    if "vendor" in raw_lower or "difference" in raw_lower:
        return "vendor_difference"
    if "security" in raw_lower or "secret" in raw_lower or "redact" in raw_lower:
        return "security"
    return "unknown"


def _save_translation_artifact(
    translated_config: str,
    source_vendor: str,
    target_vendor: str,
    workspace_id: str,
    session_id: str,
    line_count: int,
    mr_count: int,
    manual_review_items: list,
    quality: dict,
    warnings: list,
) -> list:
    """Save translated_config as an artifact. Never blocks translation.

    v0.9.1: Stores manual_review_items in artifact metadata so
    system.manage(action=review_list) can find them. Without this the LLM
    would see manual_review_count > 0 but review_list returns 0.
    """
    try:
        from artifacts.store import save_artifact
        rec = save_artifact(
            workspace_id=workspace_id,
            content=translated_config,
            artifact_type="translated_config",
            title=f"Translated config: {source_vendor} to {target_vendor}",
            scope="workspace",
            sensitivity="internal",
            module="config_translation",
            skill="config_translation",
            source="module_output",
            metadata={
                "source_vendor": source_vendor,
                "target_vendor": target_vendor,
                "line_count": line_count,
                "manual_review_count": mr_count,
                "manual_review_items": manual_review_items,
                "authoritative": False,
                "deployable_config": False,
                "quality_gate_passed": not bool(
                    quality.get("source_residue_count", 0) or
                    quality.get("silent_drop_count", 0)
                ),
            },
        )
        if rec:
            # v0.9.1: initialize review sidecar so system.manage(action=review_list)
            # works immediately — no need to wait for deferred creation.
            try:
                from agent.modules.review.service import init_review_sidecar
                init_review_sidecar(workspace_id, rec.artifact_id, manual_review_items)
            except Exception:
                pass
            return [{
                "artifact_id": rec.artifact_id,
                "artifact_type": "translated_config",
                "title": f"Translated config: {source_vendor} to {target_vendor}",
                "scope": "workspace",
                "sensitivity": "internal",
                "source": "module_output",
                "metadata": {
                    "authoritative": False,
                    "deployable_config": False,
                    "source_vendor": source_vendor,
                    "target_vendor": target_vendor,
                },
            }]
        # save_artifact returned None (blocked or failed silently)
        warnings.append("artifact_save_failed")
        return []
    except Exception as e:
        warnings.append("artifact_save_failed")
        return []


# ── v0.8.2 — ModuleResult projection ──

def to_module_result(result: dict) -> "ModuleResult":
    """Project a v0.7.1 result dict into a standard ModuleResult.

    The result dict's keys (translated_config, manual_review_items,
    manual_review_count, source_vendor, target_vendor, line_count,
    artifacts, warnings, errors, metadata, ok, summary) all become
    first-class ModuleResult fields:
      - data: {translated_config, manual_review_items,
               manual_review_count, source_vendor, target_vendor,
               line_count}
      - artifacts: result["artifacts"]  (verbatim)
      - errors / warnings / metadata: verbatim
      - ok / summary: verbatim
    """
    from agent.protocol.module_result import ModuleResult
    if not isinstance(result, dict):
        return ModuleResult.failure(
            summary="translate_config returned non-dict result",
            errors=["invalid_result_shape"],
        )
    ok = bool(result.get("ok", False))
    data = {
        "translated_config": result.get("translated_config", ""),
        "manual_review_items": list(result.get("manual_review_items") or []),
        "manual_review_count": int(result.get("manual_review_count", 0)),
        "source_vendor": result.get("source_vendor", ""),
        "target_vendor": result.get("target_vendor", ""),
        "line_count": int(result.get("line_count", 0)),
    }
    if ok:
        return ModuleResult.success(
            summary=str(result.get("summary", "")),
            data=data,
            artifacts=list(result.get("artifacts") or []),
            warnings=list(result.get("warnings") or []),
            metadata=dict(result.get("metadata") or {}),
        )
    return ModuleResult.failure(
        summary=str(result.get("summary", "")),
        errors=list(result.get("errors") or ["unknown_error"]),
        warnings=list(result.get("warnings") or []),
        data=data,
        metadata=dict(result.get("metadata") or {}),
    )
