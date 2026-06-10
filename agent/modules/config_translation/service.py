# agent/modules/config_translation/service.py
"""Config Translation service — wraps the canonical translate_config implementation.

Exposes translate_config() for the RuntimeLoop → ToolRouter → ToolRegistry path.
Does NOT bypass the config_translation module.
Does NOT generate deployable_config directly from LLM.
"""

from typing import Optional


def translate_config(
    source_config: str,
    source_vendor: str = "",
    target_vendor: str = "",
    options: Optional[dict] = None,
    workspace_id: str = "default",
    session_id: str = "",
) -> dict:
    """Execute config translation via the canonical module service.

    Args:
        source_config: Source device configuration text.
        source_vendor: Source vendor hint (e.g., "cisco", "auto").
        target_vendor: Target vendor (e.g., "huawei").
        options: Optional extra parameters.
        workspace_id: Workspace identifier.
        session_id: Session identifier.

    Returns:
        dict with keys: ok, summary, source_vendor, target_vendor,
        line_count, translated_config, manual_review_items, warnings,
        errors, artifacts, metadata.
    """
    warnings = []
    errors = []

    # Validate source_config
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

    # Resolve vendors
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

        # Build structured response
        manual_review_items = result_dict.get(
            "manual_review_items", result_dict.get("manual_review", [])
        )
        quality = result_dict.get("quality_summary", {})
        audit = result_dict.get("audit", {})

        has_quality_warnings = (
            quality.get("source_residue_count", 0) > 0 or
            quality.get("silent_drop_count", 0) > 0
        )

        if has_quality_warnings:
            warnings.append("quality_gate: source_residue or silent_drop detected, manual review required")

        line_count = len(source_config.strip().splitlines())

        return {
            "ok": True,
            "summary": (
                f"翻译完成: {audit.get('counts', {}).get('deployable_count', 0)} 条可部署, "
                f"{len(manual_review_items)} 条需人工复核, "
                f"{audit.get('counts', {}).get('unsupported_count', 0)} 条不支持自动翻译."
            ),
            "source_vendor": source_vendor,
            "target_vendor": target_vendor,
            "line_count": line_count,
            "translated_config": result_dict.get("deployable_config", ""),
            "manual_review_items": manual_review_items,
            "warnings": warnings + (result_dict.get("warnings", []) or []),
            "errors": errors,
            "artifacts": result_dict.get("artifacts", []),
            "metadata": {
                "elapsed_ms": result_dict.get("elapsed_ms", 0),
                "quality_summary": quality,
                "audit": audit,
                "build_commit": result_dict.get("build_commit", ""),
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
            "warnings": [],
            "errors": [f"translation_error: {str(e)[:200]}"],
            "artifacts": [],
            "metadata": {},
        }
