"""
Audit Log for SPEG Engine.

Every request generates an immutable audit record with:
  - request-level metadata
  - executed/blocked/failed nodes
  - sensitive field redaction
  - per-node traceability (request_id + node_run_id)

Audit records are NOT writable by normal execution flows.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from .models import (
    AuditRecord,
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    SPEGConfig,
    StatelessContext,
    ToolResult,
)


SENSITIVE_FIELDS: set[str] = {
    "password", "passwd", "token", "secret", "key",
    "credential", "auth", "cookie", "session", "private_key",
    "api_key", "access_key", "bearer",
}


class AuditLogger:
    """Immutable audit log generator."""

    def __init__(self):
        self._records: list[AuditRecord] = []

    def create_record(
        self,
        ctx: StatelessContext,
        dag: ExecutionDAG | None,
        node_results: dict[str, ToolResult],
        risk_level: str = "low",
        approval_required: bool = False,
        planner_model: str = "",
        llm_call_count: int = 0,
        duration_ms: float = 0.0,
    ) -> AuditRecord:
        """Generate an immutable audit record for this request."""

        request_hash = hashlib.sha256(
            (ctx.user_input + ctx.request_id).encode()
        ).hexdigest()[:16]

        executed = []
        blocked = []
        failed = []

        if dag:
            for node in dag.nodes:
                result = node_results.get(node.id)
                node_entry = {
                    "node_id": node.id,
                    "tool": node.tool,
                    "node_run_id": node.node_run_id or str(uuid.uuid4())[:8],
                    "args": self._redact_args(node.args),
                    "depth": node.depth,
                    "status": node.status.value,
                    "latency_ms": node.latency_ms,
                }
                # v3.10: action-alias provenance. When GraphCompiler
                # normalized a planner alias (``session_get`` →
                # ``session``), we record both the original and the
                # canonical token so the audit trail can spot
                # planner terminology drift without losing the
                # canonical surface.
                if node.action_normalized_from_alias:
                    node_entry["action_original"] = node.action_original
                    node_entry["action_normalized_from_alias"] = True

                if node.status == ExecutionStatus.SUCCESS:
                    node_entry["result_summary"] = self._redact_result(result.data) if result else None
                    executed.append(node_entry)
                elif node.status == ExecutionStatus.FAILED:
                    node_entry["error"] = result.error if result else node.error
                    failed.append(node_entry)
                elif node.status == ExecutionStatus.SKIPPED:
                    blocked.append(node_entry)

        record = AuditRecord(
            request_id=ctx.request_id,
            session_id=ctx.session_id,
            created_at=time.time(),
            user_request_hash=request_hash,
            planner_model=planner_model,
            llm_call_count=llm_call_count,
            dag_nodes=dag.total_nodes if dag else 0,
            dag_depth=dag.max_depth if dag else 0,
            risk_level=risk_level,
            approval_required=approval_required,
            executed_nodes=executed,
            blocked_nodes=blocked,
            failed_nodes=failed,
            duration_ms=duration_ms,
        )

        self._records.append(record)
        return record

    def _redact_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive fields from node args."""
        if not args:
            return {}
        redacted = {}
        for key, value in args.items():
            if key.lower() in SENSITIVE_FIELDS:
                redacted[key] = "***REDACTED***"
            elif isinstance(value, dict):
                redacted[key] = self._redact_args(value)
            elif isinstance(value, str) and any(
                sf in value.lower() for sf in SENSITIVE_FIELDS
            ):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = value
        return redacted

    def _redact_result(self, data: Any) -> Any:
        """Redact sensitive data from results."""
        if isinstance(data, dict):
            return self._redact_args(data)
        if isinstance(data, str) and len(data) > 500:
            return data[:500] + "..."
        return data

    @property
    def records(self) -> list[AuditRecord]:
        return list(self._records)

    def last_record(self) -> AuditRecord | None:
        return self._records[-1] if self._records else None
