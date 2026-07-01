"""
Graph Compiler — deterministic conversion of Planner JSON → Execution DAG IR.

Responsibilities:
  - Action-alias normalization (canonical mapping BEFORE semantic
    validation; tracked on each node for audit/risk/trace surfaces)
  - Dependency resolution (topological sort by depth)
  - Cycle elimination
  - Node normalization (assign depth, link deps)
  - Layer grouping for parallel execution
"""

from __future__ import annotations

from collections import deque

from .action_alias import normalize_action_alias
from .models import ExecutionDAG, ExecutionNode, PlanNode, SPEGConfig


class GraphCompiler:
    """Compiles raw PlanNode list into a validated ExecutionDAG."""

    def __init__(self, config: SPEGConfig):
        self._config = config

    def compile(self, plan_nodes: list[PlanNode]) -> ExecutionDAG:
        """Convert plan nodes into an execution DAG.

        Returns an ExecutionDAG with nodes assigned to depth layers.
        """
        if not plan_nodes:
            return ExecutionDAG(
                nodes=[],
                layers={},
                total_nodes=0,
                max_depth=0,
            )

        # Phase 1: Create ExecutionNode instances + normalize action
        # aliases BEFORE semantic validation. Any legacy / colloquial
        # token (e.g. ``session_get``) is rewritten to the canonical
        # enum value, and the original token + a flag are recorded
        # on the node so downstream audit surfaces the drift.
        node_map: dict[str, ExecutionNode] = {}
        for pn in plan_nodes:
            action_original = ""
            action_normalized_from_alias = False
            if isinstance(pn.args, dict):
                raw_action = pn.args.get("action")
                if isinstance(raw_action, str) and raw_action:
                    canonical, original = normalize_action_alias(raw_action)
                    if original and canonical and original != canonical:
                        # Rewrite the arg in-place; downstream layers
                        # (semantic_validator / risk / audit) only see
                        # the canonical token.
                        pn.args["action"] = canonical
                        action_original = original
                        action_normalized_from_alias = True
                    # canonical == original or original is None: leave
                    # the args alone; ``action_normalized_from_alias``
                    # stays False.
            node_map[pn.id] = ExecutionNode(
                id=pn.id,
                tool=pn.tool,
                args=pn.args,
                deps=list(pn.deps),
                action_original=action_original,
                action_normalized_from_alias=action_normalized_from_alias,
            )

        # Phase 2: Validate dependency references
        for nid, node in node_map.items():
            for dep in node.deps:
                if dep not in node_map:
                    raise ValueError(
                        f"Node '{nid}' depends on '{dep}' which does not exist in the graph"
                    )

        # Phase 3: Topological sort + assign depths
        self._assign_depths(node_map)

        # Phase 4: Build layers
        layers: dict[int, list[ExecutionNode]] = {}
        max_depth = 0
        for node in node_map.values():
            max_depth = max(max_depth, node.depth)
            if node.depth not in layers:
                layers[node.depth] = []
            layers[node.depth].append(node)

        # Phase 5: Build final DAG
        all_nodes = list(node_map.values())

        return ExecutionDAG(
            nodes=all_nodes,
            layers=layers,
            total_nodes=len(all_nodes),
            max_depth=max_depth,
        )

    def _assign_depths(self, node_map: dict[str, ExecutionNode]) -> None:
        """Topological sort: node depth = 1 + max(dep depths), 0 if no deps.

        Uses BFS with in-degree counting to handle arbitrary DAG topologies.
        Detects cycles and eliminates them (drops cycle-causing edges).
        """
        # Compute in-degrees
        in_degree: dict[str, int] = {nid: 0 for nid in node_map}
        adj: dict[str, list[str]] = {nid: [] for nid in node_map}

        for nid, node in node_map.items():
            for dep in node.deps:
                if dep in node_map:
                    adj[dep].append(nid)
                    in_degree[nid] += 1

        # Cycle detection: Kahn's algorithm
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])

        # If no nodes with in-degree 0, there's a cycle → break it
        if not queue:
            queue = self._break_cycle(node_map, in_degree, adj)

        assigned = 0
        total = len(node_map)
        depths: dict[str, int] = {}

        while queue:
            nid = queue.popleft()
            assigned += 1

            # Compute depth = 1 + max(dep depth), 0 if no deps
            if node_map[nid].deps:
                depths[nid] = 1 + max(
                    depths.get(d, 0) for d in node_map[nid].deps if d in depths
                )
            else:
                depths[nid] = 0

            for child in adj.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        # Any remaining nodes are part of a cycle → assign depth = 0 as safety
        for nid in node_map:
            if nid not in depths:
                depths[nid] = 0
                # Remove their deps to break cycle
                node_map[nid].deps = []

        # Write depths back
        for nid, d in depths.items():
            node_map[nid].depth = d

    def _break_cycle(
        self,
        node_map: dict[str, ExecutionNode],
        in_degree: dict[str, int],
        adj: dict[str, list[str]],
    ) -> deque:
        """Break cycles by removing edges from the node with fewest total connections."""
        # Find the node with minimum degree (in + out)
        best_node = min(
            node_map.keys(),
            key=lambda nid: in_degree.get(nid, 0) + len(adj.get(nid, [])),
        )
        # Remove all its dependencies to break the cycle
        node_map[best_node].deps = []
        in_degree[best_node] = 0
        for parent, children in adj.items():
            if best_node in children:
                children.remove(best_node)
        return deque([best_node])
