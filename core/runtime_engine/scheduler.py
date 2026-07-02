"""
Resource Scheduler for SSOT Runtime Engine.

Controls concurrency across the entire DAG execution:
  - Global max concurrency (default 8)
  - Per-layer max concurrency (default 5)
  - Per-concurrency-group limits (ssh=2, shell=4, etc.)
  - Node priority ordering (HIGH → NORMAL → LOW)
  - Budget checks before each batch

This replaces raw asyncio.gather() with controlled batching.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .contracts import BUILTIN_CONTRACTS, get_concurrency_group
from .models import (
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    NodePriority,
    SSOTRuntimeConfig,
)


class ResourceScheduler:
    """Controls resource allocation for DAG execution layers.

    Applies:
      - max_global_concurrency
      - max_layer_concurrency
      - concurrency_group limits
      - priority ordering
    """

    def __init__(self, config: SSOTRuntimeConfig | None = None):
        cfg = config or SSOTRuntimeConfig()
        self._max_global = cfg.max_global_concurrency
        self._max_layer = cfg.max_layer_concurrency
        # Default group limits
        self._group_limits: dict[str, int] = {
            "ssh": 2,
            "shell": 4,
            "browser": 1,
            "subagent": 2,
            "external_http": 4,
            "filesystem": 3,
            "git": 1,
            "cmdb": 2,
        }

    def schedule_layer(
        self,
        nodes: list[ExecutionNode],
        active_global_count: int,
    ) -> list[ExecutionNode]:
        """Schedule a batch of nodes for execution.

        Applies global, layer, and group concurrency limits.
        Returns the subset of nodes that are allowed to run.

        Args:
            nodes: All ready nodes at this depth
            active_global_count: Currently executing nodes across all layers

        Returns:
            Nodes cleared to execute in this batch
        """
        # Filter to only pending nodes
        ready = [n for n in nodes if n.status == ExecutionStatus.PENDING]
        if not ready:
            return []

        # Priority sort: HIGH first, then NORMAL, then LOW
        ready.sort(key=lambda n: (
            0 if n.priority == NodePriority.HIGH else
            1 if n.priority == NodePriority.NORMAL else 2
        ))

        # Global limit
        available_global = self._max_global - active_global_count
        if available_global <= 0:
            return []

        # Layer limit
        layer_cap = min(self._max_layer, available_global)

        # Group tracking in this batch
        group_counts: dict[str, int] = defaultdict(int)
        scheduled: list[ExecutionNode] = []

        for node in ready:
            if len(scheduled) >= layer_cap:
                break

            # Group concurrency limit
            group = get_concurrency_group(node.tool)
            if group and group in self._group_limits:
                limit = self._group_limits[group]
                if group_counts[group] >= limit:
                    continue
                group_counts[group] += 1

            scheduled.append(node)

        return scheduled

    @property
    def max_global(self) -> int:
        return self._max_global

    @property
    def max_layer(self) -> int:
        return self._max_layer

    def set_group_limit(self, group: str, limit: int) -> None:
        """Override a concurrency group limit."""
        self._group_limits[group] = limit
