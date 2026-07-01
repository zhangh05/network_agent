"""
Risk Policy Engine for SPEG Engine.

Assesses DAG-wide risk level, distinguishes between:
  - **allow**: safe to run directly
  - **approval_required**: needs user confirmation (frontend approval bubble)
  - **hard_block**: absolutely forbidden, cannot be overridden

This is the last gate before execution — hard_block rejects immediately;
approval_required defers to the caller for user consent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .contracts import BUILTIN_CONTRACTS, get_contract, get_risk_level
from .models import ExecutionDAG, ExecutionNode, RiskLevel
from .command_policy import normalize_command, evaluate_command_policy


# ── Destructive command patterns (trigger approval, not hard block) ────

_DESTRUCTIVE_COMMAND_PATTERNS: list[tuple[str, str]] = [
    # Each tuple: (regex, human_label)
    (r"(^|\s)rm\s+-f\b", "rm -f"),
    (r"(^|\s)rm\s+-rf\b", "rm -rf"),
    (r"(^|\s)del\s+/f\b", "del /f"),
    (r"(^|\s)rmdir\s+/s\b", "rmdir /s"),
    (r"(?i)remove-item\s+-recurse", "Remove-Item -Recurse"),
    (r"(^|\s)format\b", "format"),
    (r"(^|\s)mkfs\b", "mkfs"),
    (r"(^|\s)dd\s+if=", "dd if="),
    (r"chmod\s+-R\s+777", "chmod -R 777"),
    (r"chown\s+-R\b", "chown -R"),
    (r"git\s+reset\s+--hard", "git reset --hard"),
    (r"git\s+clean\s+-fd", "git clean -fd"),
    (r"docker\s+system\s+prune", "docker system prune"),
    (r"kubectl\s+delete\b", "kubectl delete"),
    (r"(^|\s)delete\b", "delete"),
    (r"drop\s+database\b", "drop database"),
    (r"truncate\s+table\b", "truncate table"),
]


# ── Hard-block patterns (absolute, no approval possible) ────────────

_SYSTEM_DESTROY_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+/(\s|$)", "rm -rf /"),
    (r"rm\s+-rf\s+/\*", "rm -rf /*"),
    # Windows paths: match both \ and / separators after normalization
    (r"del\s+C:[\\/]Windows", "del C:\\Windows"),
    (r"del\s+C:[\\/]Users", "del C:\\Users"),
    (r"format\s+C:", "format C:"),
]


@dataclass
class RiskAssessment:
    """Result of a DAG-level risk policy check."""
    risk_level: str = "low"
    safe_to_run: bool = True
    requires_approval: bool = False
    hard_block: bool = False
    blocked_reason: str = ""
    blocked_nodes: list[str] = field(default_factory=list)
    approval_reason: str = ""
    approval_nodes: list[str] = field(default_factory=list)
    approval_details: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    combo_reasons: list[str] = field(default_factory=list)
    alias_normalizations: list[dict[str, str]] = field(default_factory=list)


class RiskPolicyEngine:
    """Risk assessment for execution DAGs.

    Rules (v3.12):
      - credential_access / system dir delete → **hard_block**
      - Destructive commands (rm -rf, git reset --hard, etc.) → **approval_required**
      - 3+ write/mutate → **approval_required**
      - 3+ exec.run → **approval_required** (NOT hard block!)
      - 11+ exec.run → **approval_required** (large_command_batch)
      - 11+ total nodes → **approval_required** (large_tool_batch)
      - exec + external + credential → **approval_required**
      - exec.run count ≤ 10: approval_required but never hard block
    """

    def assess(self, dag: ExecutionDAG) -> RiskAssessment:
        assessment = RiskAssessment()

        exec_count = 0
        write_count = 0
        cred_count = 0
        external_count = 0

        for node in dag.nodes:
            contract = get_contract(node.tool)
            if contract is None:
                continue

            node_risk = contract.risk_level

            # ── CRITICAL contract risk → hard block (e.g. credential_access) ──
            if node_risk == RiskLevel.CRITICAL.value:
                assessment.blocked_nodes.append(node.id)
                assessment.hard_block = True
                assessment.safe_to_run = False
                assessment.blocked_reason = (
                    f"Critical-risk node '{node.id}' ({node.tool}) — hard blocked"
                )

            # ── HIGH contract risk → approval gate ──
            elif node_risk == RiskLevel.HIGH.value:
                if node.id not in assessment.approval_nodes:
                    assessment.approval_nodes.append(node.id)
                assessment.requires_approval = True
                node.approval_required = True

            # ── Contract-based approval flag ──
            if contract.requires_approval:
                if node.id not in assessment.approval_nodes:
                    assessment.approval_nodes.append(node.id)
                assessment.requires_approval = True
                node.approval_required = True

            # ── Unified command policy check ──
            if node.tool == "exec.run" and "command" in node.args:
                cmd = node.args.get("command", "")
                if cmd and isinstance(cmd, str):
                    # System destroy check (hard block) — MUST run first
                    # so we hard-block before any other decision.
                    sys_dest_label = _check_system_destroy(cmd)
                    if sys_dest_label:
                        assessment.blocked_nodes.append(node.id)
                        assessment.hard_block = True
                        assessment.safe_to_run = False
                        assessment.blocked_reason = (
                            f"System-destroy command in node '{node.id}': {sys_dest_label}"
                        )
                        continue  # don't process further — already hard blocked

                    # Destructive command check (approval, not hard block).
                    # MUST run before command_policy to prevent the policy's
                    # own destructive patterns from turning rm -rf into a
                    # hard block (command_policy has FORBIDDEN_COMMAND for
                    # rm, git reset --hard, etc. — we want those to be
                    # approval_required instead).
                    dest_label = _check_destructive_command(cmd)
                    if dest_label:
                       if node.id not in assessment.approval_nodes:
                           assessment.approval_nodes.append(node.id)
                       assessment.requires_approval = True
                       assessment.approval_reason = (
                           assessment.approval_reason or "destructive_command"
                       )
                       assessment.approval_details.append({
                           "node_id": node.id,
                           "tool": node.tool,
                           "command": cmd[:200],
                           "risk_reason": dest_label,
                       })
                       # Skip command_policy for destructive commands —
                       # they've been classified as approval_required.
                       continue

                    # Unified command policy check (hard block for
                    # FORBIDDEN_COMMAND / PATH_TRAVERSAL / reg.exe /
                    # PowerShell abuse etc.)
                    normalized = normalize_command(cmd)
                    decision = evaluate_command_policy(normalized)
                    if not decision.allowed:
                        assessment.blocked_nodes.append(node.id)
                        assessment.hard_block = True
                        assessment.safe_to_run = False
                        assessment.blocked_reason = (
                            assessment.blocked_reason or
                            f"Command policy blocked node '{node.id}': {decision.reason}"
                        )

            # ── Side-effect counts for combo escalation ──
            se = contract.side_effect
            if se == "execute_command":
                exec_count += 1
            elif se in ("write_file", "mutate_local"):
                write_count += 1
            elif se == "external_request":
                external_count += 1
            elif se == "credential_access":
                cred_count += 1

            # ── Alias normalization bookkeeping ──
            if node.action_normalized_from_alias and node.action_original:
                assessment.alias_normalizations.append({
                    "node_id": node.id,
                    "action_original": node.action_original,
                    "action_normalized": node.args.get("action", ""),
                })

        # ── Combo escalation ──
        self._apply_combo_escalation(
            assessment, exec_count, write_count,
            external_count, cred_count, dag,
        )

        # ── Compute composite risk ──
        assessment.risk_level = self._compute_composite(dag)

        # ── If hard_block is already set, nothing else matters ──
        if assessment.hard_block:
            assessment.safe_to_run = False
            return assessment

        # ── If approval is required, mark safe_to_run accordingly ──
        if assessment.requires_approval:
            # Not hard_block, but needs user consent — still
            # "not safe to run automatically"
            assessment.safe_to_run = False

        return assessment

    def _apply_combo_escalation(
        self,
        assessment: RiskAssessment,
        exec_count: int,
        write_count: int,
        external_count: int,
        cred_count: int,
        dag: ExecutionDAG,
    ) -> None:
        total_nodes = dag.total_nodes if dag else len(dag.nodes)

        # 3+ writes → approval required
        if write_count >= 3 and not assessment.hard_block:
            assessment.combo_reasons.append(f"{write_count} write/mutate operations")
            assessment.warnings.append(
                f"Combo: {write_count} write operations detected"
            )
            assessment.requires_approval = True
            if not assessment.approval_reason:
                assessment.approval_reason = "multiple_writes"

        # 3+ exec → approval required (NOT hard block!)
        if exec_count >= 3 and not assessment.hard_block:
            assessment.combo_reasons.append(
                f"{exec_count} command executions"
            )
            assessment.warnings.append(
                f"Combo: {exec_count} command executions — approval required"
            )
            assessment.requires_approval = True
            if not assessment.approval_reason:
                assessment.approval_reason = "multiple_commands"

        # 11+ exec → approval (large command batch)
        if exec_count > 10 and not assessment.hard_block:
            assessment.requires_approval = True
            assessment.approval_reason = "large_command_batch"
            assessment.warnings.append(
                f"Large command batch: {exec_count} exec nodes"
            )

        # 11+ total nodes → approval (large tool batch)
        if total_nodes > 10 and not assessment.hard_block:
            assessment.requires_approval = True
            if not assessment.approval_reason:
                assessment.approval_reason = "large_tool_batch"
            assessment.warnings.append(
                f"Large tool batch: {total_nodes} total nodes"
            )

        # exec + external + credential → approval
        if exec_count and external_count and cred_count and not assessment.hard_block:
            assessment.combo_reasons.append(
                "exec + external + credential_access combo"
            )
            assessment.warnings.append(
                "Combo: exec + external + credential — approval required"
            )
            assessment.requires_approval = True
            if not assessment.approval_reason:
                assessment.approval_reason = "exec_external_credential_combo"

    def _compute_composite(self, dag: ExecutionDAG) -> str:
        max_risk = RiskLevel.LOW
        risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        for node in dag.nodes:
            node_risk = get_risk_level(node.tool)
            try:
                rl = RiskLevel(node_risk)
            except ValueError:
                continue
            if risk_order.get(rl.value, 0) > risk_order.get(max_risk.value, 0):
                max_risk = rl
        return max_risk.value


def _check_destructive_command(cmd: str) -> str:
    """Return a human-readable label if ``cmd`` matches a destructive
    pattern that should trigger an approval gate (NOT hard block)."""
    for pattern, label in _DESTRUCTIVE_COMMAND_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return label
    return ""


def _check_system_destroy(cmd: str) -> str:
    """Return a human-readable label if ``cmd`` matches a system-destroy
    pattern that should be hard-blocked. None if safe from that perspective."""
    cmd_norm = cmd.replace("\\", "/")
    for pattern, label in _SYSTEM_DESTROY_PATTERNS:
        # Use re.IGNORECASE instead of .lower() on the pattern —
        # .replace('\\','/') would destroy regex metacharacters like \s.
        if re.search(pattern, cmd_norm, re.IGNORECASE):
            return label
    return ""
