# context/fragments/context_bundle.py
"""ContextBundle fragment — the primary LLM-safe context payload."""

import logging
from .base import ContextFragment, FragmentPriority

logger = logging.getLogger(__name__)


class ContextBundleFragment(ContextFragment):
    """Builds the safe_llm_context and execution_context from the full ContextBundle.

    This is the most important fragment — it carries the compressed,
    redacted, and policy-checked LLM prompt context.
    """

    priority = FragmentPriority.LLM_SAFE
    token_budget = 16384  # large, but still capped

    def build(self, state) -> dict:
        try:
            from core.context.builder import build_context_bundle

            ctx_ref = state.context.get("context_ref", "")
            bundle = build_context_bundle(
                workspace_id=state.workspace_id or "default",
                user_input=state.user_input or "",
                intent=state.intent or "",
                capability_id=state.context.get("capability_id", ""),
                payload=state.payload,
                context_ref=ctx_ref,
                state_context=state.context,
                run_id=state.request_id,
                trace_id=state.trace_id or "",
            )
            return {
                "ok": True,
                "safe_llm_context": (
                    bundle.safe_llm_context.as_dict()
                    if bundle.safe_llm_context else {}
                ),
                "execution_context": (
                    bundle.execution_context.as_dict()
                    if bundle.execution_context else {}
                ),
                "citations": bundle.citations or [],
                "bundle_available": True,
            }
        except Exception:
            logger.warning("ContextBundleFragment: build failed", exc_info=True)
            return {"ok": True, "bundle_available": False,
                    "safe_llm_context": {}, "execution_context": {}, "citations": []}

    def render(self, data: dict) -> str:
        """ContextBundle is consumed directly by the LLM (not serialized to string).
        Its data is injected into state.context via the collector.
        """
        return ""  # rendered via direct state assignment, not string serialization
