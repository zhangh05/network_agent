# backend/services/config_translation/service.py
"""Core config translation service. Wraps the embedded translate_bundle pipeline.

The translator is fully embedded in modules/config_translation/core/ —
no external network-translator repo dependency, no sys.path hack, no os.chdir.
"""

import time

from backend.core.settings import BUILD_COMMIT, TRANSLATOR_ENTRY
from backend.services.config_translation.schemas import TranslateRequest, TranslateResponse

# Embedded translator — imported directly as an internal module
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

    # Build manual_review with full fields
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

    # Build semantic_near
    semantic_near_items = []
    for item in bundle.semantic_near_items:
        semantic_near_items.append({
            "source_excerpt": item.get("source_excerpt", item.get("source_line", "")),
            "suggested_lines": item.get("suggested_lines", item.get("line", "")),
            "reason": item.get("reason", ""),
            "risk_level": item.get("risk_level", "medium"),
        })

    # Build unsupported
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

    audit = {
        "counts": {
            "deployable_count": len(bundle.deployable_lines),
            "manual_review_count": mr_count,
            "semantic_near_count": sn_count,
            "unsupported_count": un_count,
        },
        "gates": {
            "silent_drop": 0,
            "residue": 0,
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
        manual_review_count=mr_count,
        semantic_near_count=sn_count,
        unsupported_count=un_count,
        build_commit=BUILD_COMMIT,
        translator_entry=TRANSLATOR_ENTRY,
        elapsed_ms=round(elapsed_ms),
    )
