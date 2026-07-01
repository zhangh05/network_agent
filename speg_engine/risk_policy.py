"""
Risk Policy Engine for SPEG Engine.

Assesses DAG-wide risk level, applies composite escalation rules,
enforces hard-block forbidden patterns, and manages approval gates.

This is the last gate before execution — if risk policy rejects,
the DAG does NOT run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import BUILTIN_CONTRACTS, get_contract, get_risk_level
from .models import ExecutionDAG, ExecutionNode, RiskLevel
from .command_policy import normalize_command, evaluate_command_policy


@dataclass
class RiskAssessment:
    """Result of a DAG-level risk policy check."""
    risk_level: str = "low"
    safe_to_run: bool = True
    requires_approval: bool = False
    blocked_reason: str = ""
    blocked_nodes: list[str] = field(default_factory=list)
    approval_nodes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    combo_reasons: list[str] = field(default_factory=list)


class RiskPolicyEngine:
    """Bank-grade risk assessment for execution DAGs.

    Rules:
      - CRITICAL nodes → hard block (unless explicitly allowed)
      - HIGH nodes → approval gate
      - Combo escalation: 3+ writes → HIGH, 2+ exec → HIGH, 3+ exec → CRITICAL
      - Forbidden command patterns → hard block
    """

    def assess(self, dag: ExecutionDAG) -> RiskAssessment:
        assessment = RiskAssessment()

        # Per-node risk analysis
        for node in dag.nodes:
            contract = get_contract(node.tool)
            if contract is None:
                continue

            node_risk = contract.risk_level

            # CRITICAL → hard block
            if node_risk == RiskLevel.CRITICAL.value:
                assessment.blocked_nodes.append(node.id)
                assessment.safe_to_run = False
                assessment.blocked_reason = f"Critical-risk node '{node.id}' ({node.tool}) blocked by policy"

            # HIGH → approval gate
            elif node_risk == RiskLevel.HIGH.value:
                assessment.approval_nodes.append(node.id)
                assessment.requires_approval = True
                node.approval_required = True

            # Contract-based approval
            if contract.requires_approval:
                assessment.approval_nodes.append(node.id)
                assessment.requires_approval = True
                node.approval_required = True

            # v1.0: Unified command policy check via command_policy
            if node.tool == "exec.run" and "command" in node.args:
                cmd = node.args.get("command", "")
                if cmd and isinstance(cmd, str):
                    normalized = normalize_command(cmd)
                    decision = evaluate_command_policy(normalized)
                    if not decision.allowed:
                        assessment.blocked_nodes.append(node.id)
                        assessment.safe_to_run = False
                        assessment.blocked_reason = (
                            assessment.blocked_reason or
                            f"Command policy blocked node '{node.id}': {decision.reason}"
                        )

        # Combo escalation
        self._check_combo_escalation(dag, assessment)

        # Compute composite risk
        assessment.risk_level = self._compute_composite(dag)

        # If critical after combo, block
        if assessment.risk_level == RiskLevel.CRITICAL.value:
            assessment.safe_to_run = False
            assessment.blocked_reason = (
                assessment.blocked_reason or
                f"Composite risk escalated to CRITICAL: {', '.join(assessment.combo_reasons)}"
            )

        return assessment

    def _check_combo_escalation(
        self,
        dag: ExecutionDAG,
        assessment: RiskAssessment,
    ) -> None:
        write_nodes = []
        exec_nodes = []
        external_nodes = []
        cred_nodes = []

        for node in dag.nodes:
            contract = get_contract(node.tool)
            if contract is None:
                continue
            se = contract.side_effect
            if se in ("write_file", "mutate_local"):
                write_nodes.append(node.id)
            elif se == "execute_command":
                exec_nodes.append(node.id)
            elif se == "external_request":
                external_nodes.append(node.id)
            elif se == "credential_access":
                cred_nodes.append(node.id)

        # Multiple writes → HIGH
        if len(write_nodes) >= 3:
            assessment.combo_reasons.append(f"{len(write_nodes)} write/mutate operations")
            assessment.warnings.append(f"Combo: {len(write_nodes)} write operations detected")

        # Multiple exec → escalate
        if len(exec_nodes) >= 2:
            assessment.combo_reasons.append(f"{len(exec_nodes)} command executions")
            assessment.warnings.append(f"Combo: {len(exec_nodes)} command executions — risk escalated")

        # Exec + external + credential → CRITICAL
        if exec_nodes and external_nodes and cred_nodes:
            assessment.combo_reasons.append("exec + external + credential_access combo")
            assessment.warnings.append("CRITICAL: exec + external + credential combo detected")

    def _compute_composite(self, dag: ExecutionDAG) -> str:
        """Compute the highest risk across all nodes with combo escalation."""
        max_risk = RiskLevel.LOW

        write_count = 0
        exec_count = 0

        for node in dag.nodes:
            node_risk = get_risk_level(node.tool)
            try:
                rl = RiskLevel(node_risk)
            except ValueError:
                continue

            # Track max risk
            risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            if risk_order.get(rl.value, 0) > risk_order.get(max_risk.value, 0):
                max_risk = rl

            contract = get_contract(node.tool)
            if contract:
                se = contract.side_effect
                if se in ("write_file", "mutate_local"):
                    write_count += 1
                elif se == "execute_command":
                    exec_count += 1

        # Combo escalation
        if write_count >= 3 and max_risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
            max_risk = RiskLevel.HIGH
        if exec_count >= 2 and max_risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
            max_risk = RiskLevel.HIGH
        if exec_count >= 3:
            max_risk = RiskLevel.CRITICAL

        return max_risk.value
