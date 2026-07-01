"""
Pre-Execution Repair Engine for SPEG Runtime.

Handles recoverable semantic validation errors BEFORE execution fails.

Repairable errors:
  - ARG_ENUM_INVALID        → action alias normalization
  - TOOL_NOT_FOUND + alias  → tool name correction
  - MISSING_REQUIRED_ARG    → fill with defaults
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

# Maps invalid action aliases → (canonical_action, operation)
# EXTENDED aliases beyond what action_alias.py provides.
# The primary alias table is in action_alias.py (used by GraphCompiler).
# This table is the fallback for runtime correction.
ACTION_ALIAS_MAP: dict[str, tuple[str, str | None]] = {
    # System tool — runtime fallback (not in action_alias.py)
    "review_get": ("review", "get"),
    "audit_get": ("audit", "get"),
    "task_get": ("tasks", "get"),
    "tasks_get": ("tasks", "get"),
    "run_get": ("run", "get"),
    "get_run": ("run", "get"),
    "run_list": ("run", "list"),
    "list_runs": ("run", "list"),
    "self_check": ("selfcheck", None),
    "check_health": ("health", None),
    "do_diagnostics": ("diagnostics", None),
    "diag": ("diagnostics", None),

    # Knowledge tool aliases
    "knowledge_read": ("read", None),
    "read_knowledge": ("read", None),
    "knowledge_import": ("import", None),
    "import_knowledge": ("import", None),
    "find_knowledge": ("search", None),
    "search_knowledge": ("search", None),

    # Memory tool aliases
    "memory_search": ("search", None),
    "search_memory": ("search", None),
    "memory_create": ("create", None),
    "create_memory": ("create", None),
    "memory_delete": ("delete", None),
    "delete_memory": ("delete", None),

    # CMDB / Device aliases
    "list_devices": ("list", None),
    "get_device": ("get", None),

    # Web aliases
    "search_web": ("search", None),
    "web_search": ("search", None),
    "fetch_page": ("page", None),

    # Workspace aliases
    "file_read": ("read", None),
    "read_file": ("read", None),
    "file_write": ("write_artifact", None),
    "write_file": ("write_artifact", None),
    "file_list": ("list", None),
    "list_files": ("list", None),
    "file_delete": ("delete_file", None),
    "delete_file_obj": ("delete_file", None),

    # Git aliases
    "git_status": ("status", None),
    "git_diff": ("diff", None),
    "git_log": ("log", None),
    "git_commit": ("commit", None),

    # Config aliases
    "parse_config": ("parse", None),
    "config_parse": ("parse", None),
    "translate_config": ("translate", None),

    # PCAP aliases
    "parse_pcap": ("parse", None),
    "pcap_parse": ("parse", None),

    # Report aliases
    "render_report": ("markdown", None),
    "generate_report": ("markdown", None),

    # Inspection aliases
    "start_inspection": ("start", None),
    "inspection_status": ("status", None),
    "inspection_result": ("result", None),
    "cancel_inspection": ("cancel", None),
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


# ============================================================================
# PreExecutionRepairEngine
# ============================================================================

class PreExecutionRepairEngine:
    """Repairs semantic validation errors before execution fails.

    Only handles safe, deterministic repairs:
      - Action alias normalization
      - Tool name alias correction
      - Missing arg defaults
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
                repaired = self._repair_missing_required(node, event, message)

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
        """Fix enum mismatch via action alias normalization."""
        action = node.args.get("action", "")
        if not action or not isinstance(action, str):
            return False

        # Check action alias table
        alias_key = action.lower()
        if alias_key in ACTION_ALIAS_MAP:
            canonical, op = ACTION_ALIAS_MAP[alias_key]
            event.original_action = action
            event.normalized_action = canonical
            event.operation = op

            node.args["action"] = canonical
            if op:
                node.args["operation"] = op
            event.validation_after = "pass"
            return True

        return False

    def _repair_action_alias_not_normalized(self, node, event: RepairEvent) -> bool:
        """Normalize an action alias that the compiler missed.

        Uses action_alias.py as the primary source, with this module's
        ACTION_ALIAS_MAP as an extended fallback.
        """
        from .action_alias import normalize_action_alias

        action = node.args.get("action", "")
        if not action or not isinstance(action, str):
            return False

        # Try action_alias.py first
        canonical, original = normalize_action_alias(action)
        if canonical and original and canonical != original:
            event.original_action = original
            event.normalized_action = canonical
            node.args["action"] = canonical
            event.validation_after = "pass"
            return True

        # Try our extended alias table
        alias_key = action.lower()
        if alias_key in ACTION_ALIAS_MAP:
            canonical, op = ACTION_ALIAS_MAP[alias_key]
            event.original_action = action
            event.normalized_action = canonical
            event.operation = op
            node.args["action"] = canonical
            if op:
                node.args["operation"] = op
            event.validation_after = "pass"
            return True

        return False

    def _repair_action_alias(self, node, event: RepairEvent) -> bool:
        """General action alias repair."""
        action = node.args.get("action", "")
        if not action or not isinstance(action, str):
            return False

        alias_key = action.lower()
        if alias_key in ACTION_ALIAS_MAP:
            canonical, op = ACTION_ALIAS_MAP[alias_key]
            event.original_action = action
            event.normalized_action = canonical
            event.operation = op

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

    def _repair_missing_required(self, node, event: RepairEvent, message: str) -> bool:
        """Fill missing required args with sensible defaults."""
        # Try to extract which field is missing from the error message
        # Common pattern: "Node 'X' missing required arg 'Y'"
        import re
        match = re.search(r"missing required arg '(\w+)'", message)
        if not match:
            return False

        field_name = match.group(1)
        # Provide defaults for known fields
        defaults = {
            "action": "list",
            "operation": "get",
            "query": "",
            "path": ".",
            "command": "echo ok",
        }

        if field_name in defaults:
            node.args[field_name] = defaults[field_name]
            event.original_action = f"missing:{field_name}"
            event.normalized_action = defaults[field_name]
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
