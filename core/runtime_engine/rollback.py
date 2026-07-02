"""
Rollback System for SSOT Runtime Engine.

Every tool with side_effect != "read" must declare rollback support.
For mutation failures, generates a rollback assessment:
  - rollback recommended
  - rollback available
  - rollback not available

Does NOT auto-execute rollback on network devices without explicit approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import BUILTIN_CONTRACTS, get_contract
from .models import ExecutionDAG, ExecutionNode, RollbackAction, RollbackPlan, ToolResult


class RollbackEngine:
    """Assesses and generates rollback plans for mutation nodes."""

    def assess(
        self,
        dag: ExecutionDAG,
        node_results: dict[str, ToolResult],
    ) -> RollbackPlan:
        """Generate a rollback assessment for the entire DAG run.

        Only generates rollback for successful mutation nodes
        when a later critical node fails.
        """
        plan = RollbackPlan()

        # Identify successful mutation nodes
        mutations: list[tuple[ExecutionNode, ToolResult]] = []
        for node in dag.nodes:
            result = node_results.get(node.id)
            if result is None:
                continue
            contract = get_contract(node.tool)
            if contract is None:
                continue
            if contract.side_effect not in ("read", "external_request") and result.success:
                mutations.append((node, result))

        # Identify failed critical nodes
        critical_failures = [
            n for n in dag.nodes
            if node_results.get(n.id) and not node_results[n.id].success
        ]

        if not critical_failures:
            return plan

        # Generate rollback actions for mutations
        for node, result in mutations:
            contract = get_contract(node.tool)
            if not contract:
                continue

            if contract.rollback_supported:
                action = RollbackAction(
                    node_id=node.id,
                    rollback_tool=node.tool,
                    args=node.args,
                    reason=f"Rollback after critical failure in nodes: {[n.id for n in critical_failures]}",
                )
                plan.actions.append(action)
                plan.rollback_available = True
            else:
                plan.warnings.append(
                    f"Node '{node.id}' ({node.tool}) mutated state but has NO rollback support"
                )

        if plan.rollback_available and critical_failures:
            plan.rollback_recommended = True

        return plan
