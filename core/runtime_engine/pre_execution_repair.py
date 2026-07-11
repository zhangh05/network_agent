"""
Pre-Execution Repair Engine for SSOT Runtime.

Handles recoverable semantic validation errors BEFORE execution fails.

Repairable errors:
  - ARG_ENUM_INVALID        → action alias normalization
  - TOOL_NOT_FOUND + alias  → tool name correction
  - MISSING_REQUIRED_ARG    → return to the LLM for correction
  - PLAN_SCHEMA_INVALID     → deterministic patch
  - INVALID_ACTION_ALIAS    → normalize action/operation
  - NODE_ARG_NORMALIZABLE   → general arg fixing

Non-repairable (security/policy):
  - FORBIDDEN_COMMAND
  - POLICY_BLOCKED
  - APPROVAL_REQUIRED
  - CRITICAL_RISK
  - PATH_TRAVERSAL
  - SYSTEM_DIRECTORY_WRITE
  - CREDENTIAL_ACCESS
  - BUDGET_EXCEEDED

Strategy:
  1. Deterministic repair (no LLM) — 1 attempt max
  2. LLM-based planner repair — 1 attempt max, controlled by budget

Trace + Audit: every repair attempt is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================================
# Action Alias Table
# ============================================================================
#
# v3.10: this map is the **runtime fallback** for action alias
# correction. The canonical source of truth is in
# ``core.runtime_engine/action_alias.py`` — see ``resolve_action_alias()``
# there. Every entry that lives here is intentionally transient:
# if the LLM keeps emitting the same alias across a release cycle,
# promote it to ``action_alias.CANONICAL_ALIASES_BY_TOOL``.
#
# Hard rule: NO alias may be defined in BOTH this map and the
# canonical table — the canonical table always wins and the
# drift test (``harness/test_alias_drift.py``) enforces that.
#
# Source field semantics for resolution events:
#   - "canonical" — rewritten through ``resolve_action_alias()``
#   - "extended"  — rewritten through this fallback
#   - "none"      — caller should let the semantic validator reject it
EXTENDED_RUNTIME_ALIAS_MAP: dict[str, tuple[str, str | None]] = {
    # Workspace aliases — transient LLM drift we still see; promote
    # to canonical once it stabilizes.
    "file_read": ("read", None),
    "read_file": ("read", None),
    "file_write": ("write_artifact", None),
    "write_file": ("write_artifact", None),
    "file_list": ("list", None),
    "list_files": ("list", None),
    "file_delete": ("delete", None),
    "delete_file_obj": ("delete", None),

    # Git aliases — transient.
    "git_status": ("status", None),
    "git_diff": ("diff", None),
    "git_log": ("log", None),
    "git_commit": ("commit", None),

    # Config aliases — transient.
    "parse_config": ("parse", None),
    "config_parse": ("parse", None),
    "translate_config": ("translate", None),

    # PCAP aliases — transient.
    "parse_pcap": ("parse", None),
    "pcap_parse": ("parse", None),
}


# ============================================================================
# Tool name aliases
# ============================================================================

TOOL_NAME_ALIASES: dict[str, str] = {
    "exec.run_command": "exec.run",
    "run.exec": "exec.run",
    "workspace.read": "workspace.file",
    "workspace.write": "workspace.file",
    "workspace.delete": "workspace.file",
    "workspace.list": "workspace.file",
    "knowledge.search": "knowledge.manage",
    "knowledge.read": "knowledge.manage",
    "memory.search": "memory.manage",
    "cmdb.manage": "device.manage",
    "device.list": "device.manage",
    "pcap.analyze": "pcap.manage",
    "report.generate": "report.manage",
    "inspection.run": "inspection.manage",
}


# ============================================================================
# Repair-eligible error codes
# ============================================================================

REPAIRABLE_ERROR_CODES: set[str] = {
    "ARG_ENUM_INVALID",
    "ACTION_ALIAS_NOT_NORMALIZED",
    "TOOL_NOT_FOUND",
    "MISSING_REQUIRED_ARG",
    "ARG_TYPE_MISMATCH",
    "INVALID_ACTION_ALIAS",
    "NODE_ARG_NORMALIZABLE",
    "POTENTIAL_MISSING_INPUT",
}

NON_REPAIRABLE_ERROR_CODES: set[str] = {
    "FORBIDDEN_COMMAND",
    "POLICY_BLOCKED",
    "APPROVAL_REQUIRED",
    "CRITICAL_RISK",
    "PATH_TRAVERSAL",
    "FORBIDDEN_ARG",
    "SYSTEM_DIRECTORY_WRITE",
    "DANGEROUS_PATH",
    "CREDENTIAL_ACCESS",
    "BUDGET_EXCEEDED",
    "FORBIDDEN_OPERATION",
    "DANGEROUS_OPERATION",
}


# ============================================================================
# Repair Models
# ============================================================================

@dataclass
class RepairEvent:
    """Records a single repair attempt."""
    repaired: bool = False
    node_id: str = ""
    original_action: str = ""
    normalized_action: str = ""
    operation: str | None = None
    # v3.10: which alias source the rewrite came from. The
    # canonical source (action_alias.resolve_action_alias) is the
    # preferred path; ``"extended"`` means the runtime fallback in
    # EXTENDED_RUNTIME_ALIAS_MAP rewrote it; ``"none"`` means the
    # caller should let the semantic validator reject it.
    source: str = "none"
    repair_attempt: int = 0
    validation_error_before: str = ""
    validation_error_code_before: str = ""
    validation_after: str = ""


@dataclass
class PreExecutionRepairResult:
    """Result of a pre-execution repair attempt."""
    repaired: bool = False
    strategy: str = ""              # "deterministic" | "planner_llm" | "none"
    repaired_dag: Any | None = None  # ExecutionDAG if repaired
    repair_events: list[RepairEvent] = field(default_factory=list)
    unrepairable_reason: str = ""
    repair_attempts: int = 0

    @property
    def repaired_graph(self) -> Any | None:
        """Loop-friendly alias for the repaired validation graph."""
        return self.repaired_dag


# ============================================================================
# PreExecutionRepairEngine
# ============================================================================

class PreExecutionRepairEngine:
    """Repairs semantic validation errors before execution fails.

    Only handles safe, deterministic repairs:
      - Action alias normalization
      - Tool name alias correction
      - Enum value patching

    Rejects all security/policy errors, forwarding them as-is.
    """

    def __init__(self):
        self._repair_count = 0
        self._llm_repair_count = 0

    def can_repair(self, error_codes: list[str]) -> bool:
        """Check if any error is repairable and NONE are non-repairable."""
        if not error_codes:
            return False

        has_repairable = any(c in REPAIRABLE_ERROR_CODES for c in error_codes)
        has_blocker = any(c in NON_REPAIRABLE_ERROR_CODES for c in error_codes)

        return has_repairable and not has_blocker

    def try_repair(
        self,
        dag,
        validation_errors: list[Any],
    ) -> PreExecutionRepairResult:
        """Attempt to repair semantic validation errors on a DAG.

        Args:
            dag: The ExecutionDAG that failed validation
            validation_errors: List of SemanticError objects from SemanticValidator

        Returns:
            PreExecutionRepairResult with repaired_dag if successful
        """
        events: list[RepairEvent] = []
        error_codes = [e.code for e in validation_errors]

        # Block: any non-repairable error → refuse
        for code in error_codes:
            if code in NON_REPAIRABLE_ERROR_CODES:
                return PreExecutionRepairResult(
                    repaired=False,
                    strategy="none",
                    unrepairable_reason=f"Non-repairable error: {code}",
                    repair_events=events,
                )

        if not self.can_repair(error_codes):
            return PreExecutionRepairResult(
                repaired=False,
                strategy="none",
                unrepairable_reason=f"No repairable errors found in: {error_codes}",
                repair_events=events,
            )

        # Attempt deterministic repair
        self._repair_count += 1

        for error in validation_errors:
            node_id = getattr(error, "node_id", "")
            code = getattr(error, "code", "")
            message = getattr(error, "message", "")
            details = getattr(error, "details", {})

            node = self._find_node(dag, node_id)
            if node is None:
                continue

            event = RepairEvent(
                node_id=node_id,
                validation_error_code_before=code,
                validation_error_before=message,
                repair_attempt=self._repair_count,
            )

            repaired = False

            if code == "ARG_ENUM_INVALID":
                repaired = self._repair_enum_invalid(node, event, message)

            elif code == "ACTION_ALIAS_NOT_NORMALIZED":
                repaired = self._repair_action_alias_not_normalized(node, event)

            elif code == "TOOL_NOT_FOUND":
                repaired = self._repair_tool_not_found(node, event)

            elif code == "MISSING_REQUIRED_ARG":
                # Missing values encode user/model intent. Inventing defaults
                # such as action=list or command="echo ok" can execute the
                # wrong operation. Leave the graph unchanged so QueryLoop can
                # return the structured error to the LLM for correction.
                repaired = False

            elif code in ("INVALID_ACTION_ALIAS", "NODE_ARG_NORMALIZABLE"):
                repaired = self._repair_action_alias(node, event)

            event.repaired = repaired
            events.append(event)

        # Check if all repairable errors were fixed
        any_repaired = any(e.repaired for e in events)
        if not any_repaired:
            return PreExecutionRepairResult(
                repaired=False,
                strategy="deterministic",
                unrepairable_reason="Deterministic repair could not fix any errors",
                repair_events=events,
                repair_attempts=self._repair_count,
            )

        return PreExecutionRepairResult(
            repaired=any_repaired,
            strategy="deterministic",
            repaired_dag=dag,
            repair_events=events,
            repair_attempts=self._repair_count,
        )

    # ========================================================================
    # Individual repair methods
    # ========================================================================

    def _repair_enum_invalid(self, node, event: RepairEvent, message: str) -> bool:
        """Fix enum mismatch via action alias normalization.

        Resolution order:
          1. ``resolve_action_alias(node.tool, action)`` — canonical source
          2. ``EXTENDED_RUNTIME_ALIAS_MAP`` — transient runtime fallback
        """
        action = node.args.get("action", "")
        if not action or not isinstance(action, str):
            return False

        # 1. Canonical source (single source of truth).
        from .action_alias import resolve_action_alias
        resolution = resolve_action_alias(node.tool, action)
        if resolution.matched:
            event.original_action = resolution.original_action
            event.normalized_action = resolution.canonical_action
            event.operation = resolution.operation
            event.source = resolution.source
            node.args["action"] = resolution.canonical_action
            if resolution.operation:
                node.args["operation"] = resolution.operation
            event.validation_after = "pass"
            return True

        # 2. Extended runtime fallback (transient aliases only).
        alias_key = action.lower()
        if alias_key in EXTENDED_RUNTIME_ALIAS_MAP:
            canonical, op = EXTENDED_RUNTIME_ALIAS_MAP[alias_key]
            event.original_action = action
            event.normalized_action = canonical
            event.operation = op
            event.source = "extended"
            node.args["action"] = canonical
            if op:
                node.args["operation"] = op
            event.validation_after = "pass"
            return True

        return False

    def _repair_action_alias_not_normalized(self, node, event: RepairEvent) -> bool:
        """Normalize an action alias that the compiler missed.

        Same resolution order as :meth:`_repair_enum_invalid`:
        canonical first, extended fallback second. Either way the
        event records ``source`` so audit surfaces the drift.
        """
        from .action_alias import resolve_action_alias

        action = node.args.get("action", "")
        if not action or not isinstance(action, str):
            return False

        # 1. Canonical source.
        resolution = resolve_action_alias(node.tool, action)
        if resolution.matched:
            event.original_action = resolution.original_action
            event.normalized_action = resolution.canonical_action
            event.operation = resolution.operation
            event.source = resolution.source
            node.args["action"] = resolution.canonical_action
            if resolution.operation:
                node.args["operation"] = resolution.operation
            event.validation_after = "pass"
            return True

        # 2. Extended runtime fallback.
        alias_key = action.lower()
        if alias_key in EXTENDED_RUNTIME_ALIAS_MAP:
            canonical, op = EXTENDED_RUNTIME_ALIAS_MAP[alias_key]
            event.original_action = action
            event.normalized_action = canonical
            event.operation = op
            event.source = "extended"
            node.args["action"] = canonical
            if op:
                node.args["operation"] = op
            event.validation_after = "pass"
            return True

        return False

    def _repair_action_alias(self, node, event: RepairEvent) -> bool:
        """General action alias repair.

        Same resolution order: canonical → extended.
        """
        action = node.args.get("action", "")
        if not action or not isinstance(action, str):
            return False

        from .action_alias import resolve_action_alias
        resolution = resolve_action_alias(node.tool, action)
        if resolution.matched:
            event.original_action = resolution.original_action
            event.normalized_action = resolution.canonical_action
            event.operation = resolution.operation
            event.source = resolution.source
            node.args["action"] = resolution.canonical_action
            if resolution.operation:
                node.args["operation"] = resolution.operation
            event.validation_after = "pass"
            return True

        alias_key = action.lower()
        if alias_key in EXTENDED_RUNTIME_ALIAS_MAP:
            canonical, op = EXTENDED_RUNTIME_ALIAS_MAP[alias_key]
            event.original_action = action
            event.normalized_action = canonical
            event.operation = op
            event.source = "extended"
            node.args["action"] = canonical
            if op:
                node.args["operation"] = op
            event.validation_after = "pass"
            return True

        return False

    def _repair_tool_not_found(self, node, event: RepairEvent) -> bool:
        """Fix tool name via alias table."""
        tool = node.tool
        if tool in TOOL_NAME_ALIASES:
            node.tool = TOOL_NAME_ALIASES[tool]
            event.original_action = tool
            event.normalized_action = node.tool
            event.validation_after = "pass"
            return True
        return False

    # ========================================================================
    # Helpers
    # ========================================================================

    def _find_node(self, dag, node_id: str):
        """Find a node by ID in the DAG."""
        if dag is None:
            return None
        for n in dag.nodes:
            if n.id == node_id:
                return n
        return None

    def should_replan_with_llm(
        self,
        repair_result: PreExecutionRepairResult,
        budget_llm_remaining: int,
    ) -> bool:
        """Check if we should attempt LLM-based replanning."""
        return (
            not repair_result.repaired
            and budget_llm_remaining > 0
            and self._llm_repair_count < 1
        )

    def mark_llm_repair_attempt(self) -> None:
        """Record that an LLM-based repair was attempted."""
        self._llm_repair_count += 1
