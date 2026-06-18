# context/fragments/registry.py
"""FragmentRegistry — collects, orders, and executes registered context fragments."""

from __future__ import annotations

import logging
from typing import Any

from .base import ContextFragment, FragmentPriority

logger = logging.getLogger(__name__)


class FragmentRegistry:
    """Registry of composable context fragments.

    Usage:
        registry = FragmentRegistry()
        registry.register(WorkspaceStateFragment())
        registry.register(MemoryHitsFragment())
        collected = registry.collect(state)
    """

    def __init__(self) -> None:
        self._fragments: list[ContextFragment] = []

    def register(self, fragment: ContextFragment) -> None:
        """Register a fragment. Auto-assigns fragment_id if not set."""
        if not fragment.fragment_id:
            fragment.fragment_id = fragment.__class__.__name__
        self._fragments.append(fragment)

    def collect(self, state: Any) -> dict:
        """Collect all fragments in priority order.

        Returns:
            dict with keys:
            - fragments: {fragment_id: fragment_data}
            - render_order: [fragment_id, ...]  (priority-sorted)
            - total_tokens_used: int  (sum of rendered lengths)
            - failed: [fragment_id, ...]  (fragments that failed)
            - skipped: [fragment_id, ...]  (fragments skipped due to budget)
        """
        results: dict[str, dict] = {}
        rendered: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        total_tokens = 0

        # Sort by priority (lower = injected first)
        ordered = sorted(self._fragments, key=lambda f: int(f.priority))

        for frag in ordered:
            fname = frag.fragment_id
            try:
                data = frag.build(state)
                if not data.get("ok"):
                    failed.append(fname)
                    logger.debug("context_fragment %s: build returned ok=False", fname)
                    continue
                results[fname] = data
                rendered_text = frag.render(data)
                if rendered_text:
                    rendered.append(fname)
                    total_tokens += len(rendered_text.encode("utf-8"))
                else:
                    skipped.append(fname)
            except Exception as e:
                failed.append(fname)
                logger.debug("context_fragment %s: exception during build: %s", fname, e)

        return {
            "fragments": results,
            "render_order": rendered,
            "total_tokens_used": total_tokens,
            "failed": failed,
            "skipped": skipped,
        }

    def clear(self) -> None:
        """Remove all registered fragments."""
        self._fragments.clear()

    def __len__(self) -> int:
        return len(self._fragments)
