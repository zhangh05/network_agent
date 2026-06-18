# context/fragments/memory.py
"""Memory hits fragment — retrieves relevant past interactions via UnifiedRetriever."""

import logging
from .base import ContextFragment, FragmentPriority

logger = logging.getLogger(__name__)


class MemoryHitsFragment(ContextFragment):
    """Retrieves memory hits from unified ContextStore for context injection."""

    priority = FragmentPriority.MEMORY
    token_budget = 2048

    def build(self, state) -> dict:
        ws_id = getattr(state, "workspace_id", "default") or "default"
        user_input = getattr(state, "user_input", "") or ""
        try:
            from context.unified_retriever import get_retriever
            retriever = get_retriever(ws_id)
            hits = retriever.search_memory(user_input, top_k=5)
            return {"ok": True, "hits": hits, "count": len(hits)}
        except Exception:
            logger.debug("MemoryHitsFragment: retrieval failed", exc_info=True)
            return {"ok": True, "hits": [], "count": 0}

    def render(self, data: dict) -> str:
        hits = data.get("hits", [])
        if not hits:
            return ""
        summaries = [h.get("summary", "")[:120] for h in hits[:3]]
        return self.cap(
            f"[memory] {len(hits)} hits\n" +
            "\n".join(f"  - {s}" for s in summaries)
        )
