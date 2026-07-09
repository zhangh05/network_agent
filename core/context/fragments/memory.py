# context/fragments/memory.py
"""Memory hits fragment — retrieves relevant past memories for auto-injection."""

import logging
from .base import ContextFragment, FragmentPriority

logger = logging.getLogger(__name__)

_CONTENT_PREVIEW = 120  # chars per memory content in auto-injection
_MAX_MEMORIES = 3       # max memories to auto-inject


class MemoryHitsFragment(ContextFragment):
    """Retrieves memory hits from unified ContextStore for auto-injection.

    Renders titles AND content previews so the LLM can act on stored
    knowledge without needing an explicit memory.manage(search) call.
    """

    priority = FragmentPriority.MEMORY
    token_budget = 2048

    def build(self, state) -> dict:
        ws_id = getattr(state, "workspace_id", "") or ""
        if not ws_id:
            return {"ok": False, "error": "workspace_id_required",
                    "hits": [], "count": 0}
        user_input = getattr(state, "user_input", "") or ""
        try:
            from core.context.unified_retriever import get_retriever
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
        lines = []
        for h in hits[:_MAX_MEMORIES]:
            mem_type = h.get("memory_type", "")
            title = h.get("title", h.get("summary", ""))
            content = (h.get("content_preview") or h.get("content", "") or "")[:_CONTENT_PREVIEW]
            if content:
                lines.append(f"[{mem_type}] {title}")
                lines.append(f"  {content}")
            else:
                lines.append(f"[{mem_type}] {title}")
        return self.cap(
            f"[memory] {len(hits)} relevant memories (compact preview; use memory.manage(search) for full recall)\n"
            + "\n".join(lines)
        )
