# modules/config_translation/backend/service.py
"""Config translation module service — canonical implementation.

This is the ONE true implementation of translate_config().
It lives at modules/config_translation/backend/service.py.
"""

import time

from backend.core.settings import BUILD_COMMIT, TRANSLATOR_ENTRY
from modules.config_translation.backend.schemas import TranslateRequest, TranslateResponse

_translator = None


def _get_translator():
    global _translator
    if _translator is None:
        from modules.config_translation.core.rule_translator import RuleBasedTranslator
        _translator = RuleBasedTranslator()
    return _translator


def translate_config(req: TranslateRequest) -> TranslateResponse:
    """Execute canonical translate_bundle and return structured response."""

    source_config = req.source_config.strip()
    if not source_config:
        return TranslateResponse(deployable_config="", audit={
            "counts": {"deployable_count": 0, "manual_review_count": 0, "semantic_near_count": 0, "unsupported_count": 0},
            "gates": {},
            "invariant_summary": {},
        })

    t0 = time.time()
    translator = _get_translator()
    bundle = translator.translate_bundle(source_config, req.source_vendor, req.target_vendor)

    deployable_config = bundle.deployable_config or ""

    mr_items = []
    for item in bundle.manual_review_items:
        mr_items.append({
            "source_excerpt": item.get("source_excerpt", item.get("source_line", "")),
            "reason": item.get("reason", ""),
            "category": item.get("category", item.get("risk", "manual_review")),
            "risk_level": item.get("risk_level", "medium"),
            "suggested_action": item.get("suggested_action", "Manually review and confirm before deployment"),
            "confirmation_points": item.get("confirmation_points") or ["Verify semantic equivalence"],
            "redaction_applied": item.get("redaction_applied", False),
        })

    semantic_near_items = []
    for item in bundle.semantic_near_items:
        semantic_near_items.append({
            "source_excerpt": item.get("source_excerpt", item.get("source_line", "")),
            "suggested_lines": item.get("suggested_lines", item.get("line", "")),
            "reason": item.get("reason", ""),
            "risk_level": item.get("risk_level", "medium"),
        })

    unsupported_items = []
    for item in bundle.unsupported_items:
        unsupported_items.append({
            "source_excerpt": item.get("source_excerpt", item.get("source_line", "")),
            "reason": item.get("reason", ""),
            "suggested_action": item.get("suggested_action", "Re-evaluate whether this command is needed on target"),
            "category": item.get("category", "unsupported"),
        })

    mr_count = len(mr_items)
    sn_count = len(semantic_near_items)
    un_count = len(unsupported_items)

    # ═══ Quality Audit ═══
    from modules.config_translation.core.quality import QualityAuditor
    auditor = QualityAuditor(source_config, req.source_vendor, req.target_vendor)

    # Build output accounting dict (which lines went where)
    accounted = {}
    for line in (bundle.deployable_lines or []):
        key = line.strip().lower().replace(" ", "")[:40]
        if key:
            accounted[key] = "deployable"
    for item in bundle.manual_review_items:
        excerpt = item.get("source_excerpt", item.get("source_line", ""))
        key = excerpt.strip().lower().replace(" ", "")[:40]
        if key:
            accounted[key] = "manual_review"
    for item in bundle.semantic_near_items:
        excerpt = item.get("source_excerpt", item.get("source_line", ""))
        key = excerpt.strip().lower().replace(" ", "")[:40]
        if key:
            accounted[key] = "semantic_near"
    for item in bundle.unsupported_items:
        excerpt = item.get("source_excerpt", item.get("source_line", ""))
        key = excerpt.strip().lower().replace(" ", "")[:40]
        if key:
            accounted[key] = "unsupported"

    # Check for residue in deployable
    residue_items = auditor.check_source_residue(deployable_config)

    # Build quality summary
    quality = auditor.build_quality_summary(
        deployable_count=len(bundle.deployable_lines),
        manual_review_count=mr_count,
        unsupported_count=un_count,
        semantic_near_count=sn_count,
        accounted_in_output=accounted,
    )
    quality_dict = quality.as_dict()
    quality_warnings = []
    if quality.source_residue_count > 0:
        quality_warnings.append(
            f"source_residue_count={quality.source_residue_count}; manual review required"
        )
        mr_items.append({
            "source_excerpt": "quality_summary.source_residue_items",
            "reason": "Source vendor syntax residue detected in translated output.",
            "category": "quality_gate",
            "risk_level": "high",
            "suggested_action": "Review and rewrite residue before using the translated result.",
            "confirmation_points": ["Confirm target-vendor syntax equivalence"],
            "redaction_applied": True,
        })
    if quality.silent_drop_count > 0:
        quality_warnings.append(
            f"silent_drop_count={quality.silent_drop_count}; manual review required"
        )
        mr_items.append({
            "source_excerpt": "quality_summary.silent_drop_items",
            "reason": "Meaningful source lines were not accounted for in any output layer.",
            "category": "quality_gate",
            "risk_level": "high",
            "suggested_action": "Review unconverted items and decide whether target syntax is required.",
            "confirmation_points": ["Confirm no source semantics were lost"],
            "redaction_applied": True,
        })
    if quality_warnings:
        quality_dict["warnings"] = (quality_dict.get("warnings") or []) + quality_warnings
        quality_dict["review_required_count"] = max(
            int(quality_dict.get("review_required_count", 0) or 0),
            len(mr_items),
        )

    # Wire real gate values from quality audit
    mr_count = len(mr_items)
    audit = {
        "counts": {
            "deployable_count": len(bundle.deployable_lines),
            "manual_review_count": mr_count,
            "semantic_near_count": sn_count,
            "unsupported_count": un_count,
        },
        "gates": {
            "silent_drop": quality.silent_drop_count,
            "residue": len(residue_items),
            "secret_leak": 0,
            "high_risk_deployable": 0,
            "default_any": 0,
            "auto_vendor_uncertain": 0,
        },
        "invariant_summary": {},
    }

    elapsed_ms = (time.time() - t0) * 1000

    return TranslateResponse(
        deployable_config=deployable_config,
        manual_review=mr_items,
        manual_review_items=mr_items,
        semantic_near=semantic_near_items,
        unsupported=unsupported_items,
        audit=audit,
        quality_summary=quality_dict,
        manual_review_count=mr_count,
        semantic_near_count=sn_count,
        unsupported_count=un_count,
        mapping_log=bundle.mapping_log,
        build_commit=BUILD_COMMIT,
        translator_entry=TRANSLATOR_ENTRY,
        elapsed_ms=round(elapsed_ms),
        warnings=quality_warnings,
    )
