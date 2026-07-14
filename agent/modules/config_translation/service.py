# agent/modules/config_translation/service.py
"""Config Translation service — wraps the canonical translate_config implementation.

Exposes translate_config() for the SSOT Runtime → ToolRuntimeClient → config.manage path.
Does NOT bypass the config_translation module.
Does NOT generate deployable_config directly from LLM.
Saves translated_config as an artifact with authoritative=false, deployable_config=false.
"""

import hashlib
import uuid


def translate_config(
    source_config: str,
    source_vendor: str = "",
    target_vendor: str = "",
    workspace_id: str = "",
    session_id: str = "",
    run_id: str = "",
    source_file_id: str = "",
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
            "manual_review_count": 0,
            "warnings": [],
            "errors": ["missing_source_config"],
            "artifacts": [],
            "metadata": {},
        }

    try:
        from workspace.ids import validate_workspace_id
        workspace_id = validate_workspace_id(workspace_id)
    except ValueError:
        return {
            "ok": False,
            "summary": "配置翻译需要有效的 workspace_id。",
            "source_vendor": source_vendor or "unknown",
            "target_vendor": target_vendor or "unknown",
            "line_count": 0,
            "translated_config": "",
            "manual_review_items": [],
            "manual_review_count": 0,
            "warnings": [],
            "errors": ["invalid_workspace_id"],
            "artifacts": [],
            "metadata": {},
        }

    from modules.config_translation.backend.service import detect_vendor, normalize_vendor

    source_vendor = normalize_vendor(source_vendor or "auto")
    target_vendor = normalize_vendor(target_vendor)
    if not target_vendor or target_vendor in {"auto", "unknown"}:
        return {
            "ok": False,
            "summary": "需要明确目标厂商，例如 huawei、h3c、cisco 或 ruijie。",
            "source_vendor": source_vendor or "unknown",
            "target_vendor": "unknown",
            "line_count": len(source_config.strip().splitlines()),
            "translated_config": "",
            "manual_review_items": [],
            "manual_review_count": 0,
            "warnings": [],
            "errors": ["missing_target_vendor"],
            "artifacts": [],
            "metadata": {},
        }

    if source_vendor == "auto":
        source_vendor = detect_vendor(source_config)
    if source_vendor == "unknown":
        return {
            "ok": False,
            "summary": "无法可靠识别源配置厂商，请明确 source_vendor 后重试。",
            "source_vendor": "unknown",
            "target_vendor": target_vendor,
            "line_count": len(source_config.strip().splitlines()),
            "translated_config": "",
            "manual_review_items": [],
            "manual_review_count": 0,
            "warnings": [],
            "errors": ["source_vendor_detection_failed"],
            "artifacts": [],
            "metadata": {},
        }

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
                run_id=run_id,
                source_file_id=source_file_id,
                translation_fingerprint=_translation_fingerprint(
                    source_config, source_vendor, target_vendor,
                ),
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
    *,
    run_id: str = "",
    source_file_id: str = "",
    translation_fingerprint: str = "",
) -> list:
    """Save translated_config as an artifact. Never blocks translation.

    Stores manual_review_items in artifact metadata so
    system.manage(action=review_list) can expose them immediately.
    """
    try:
        from artifacts.store import list_artifacts, save_artifact
        if run_id and translation_fingerprint:
            for existing in reversed(list_artifacts(
                workspace_id,
                run_id=run_id,
                artifact_type="translated_config",
            )):
                metadata = existing.get("metadata") or {}
                if metadata.get("translation_fingerprint") == translation_fingerprint:
                    return [_artifact_descriptor(existing)]

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
            run_id=run_id,
            session_id=session_id,
            capability_id="config_translation",
            metadata={
                "source_vendor": source_vendor,
                "target_vendor": target_vendor,
                "source_file_id": source_file_id,
                "translation_fingerprint": translation_fingerprint,
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
            # Initialize the review projection at artifact creation time.
            try:
                from agent.modules.review.service import init_review_sidecar
                init_review_sidecar(workspace_id, rec.artifact_id, manual_review_items)
            except Exception:
                pass
            return [_artifact_descriptor(rec)]
        # save_artifact returned None (blocked or failed silently)
        warnings.append("artifact_save_failed")
        return []
    except Exception:
        warnings.append("artifact_save_failed")
        return []


def _translation_fingerprint(source_config: str, source_vendor: str, target_vendor: str) -> str:
    payload = "\0".join((source_vendor, target_vendor, source_config.strip()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _artifact_descriptor(record) -> dict:
    get = record.get if isinstance(record, dict) else lambda key, default=None: getattr(record, key, default)
    metadata = get("metadata", {}) or {}
    return {
        "artifact_id": get("artifact_id", ""),
        "artifact_type": "translated_config",
        "title": get("title", "Translated config"),
        "scope": get("scope", "workspace"),
        "sensitivity": get("sensitivity", "internal"),
        "source": get("source", "module_output"),
        "metadata": {
            "authoritative": False,
            "deployable_config": False,
            "source_vendor": metadata.get("source_vendor", ""),
            "target_vendor": metadata.get("target_vendor", ""),
        },
    }
