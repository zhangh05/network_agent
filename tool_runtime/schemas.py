# tool_runtime/schemas.py
"""ToolSpec, ToolInvocation, ToolResult, PolicyDecision — canonical Tool Runtime schemas.

These are independent of the legacy tool_calls/tool_results in agent/state.py.
Tool Runtime uses its own data model, not the Agent's skill execution records.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ── Valid enums ──
VALID_RISK_LEVELS = {"low", "medium", "high", "forbidden"}
VALID_TOOL_STATUSES = {"succeeded", "failed", "blocked", "dry_run"}
VALID_TOOL_CATEGORIES = {
    "artifact", "parser", "report", "command",
    "knowledge", "web", "session", "runtime", "text", "workspace",
    "shell", "powershell", "python",
    "network", "device", "ssh", "telnet", "snmp", "nmap", "file",
    "skill", "memory",
}
# v0.2 — expanded categories for general agent tools
V02_ALLOWED_CATEGORIES = {
    "artifact", "parser", "report", "command",
    "knowledge", "web", "session", "runtime", "text", "workspace",
    "shell", "powershell",  # high-risk: only approved_exec allowed
    "skill", "memory",
}


@dataclass
class ToolSpec:
    """Canonical tool definition — metadata + safety contract.

    A ToolSpec describes what a tool does and what constraints apply.
    It does NOT contain the handler function (stored separately in registry).
    """

    tool_id: str = ""                 # e.g. "parser.parse_config_text"
    name: str = ""                    # Human-readable name
    description: str = ""             # What it does
    category: str = ""                # artifact | parser | report | command
    version: str = "0.1.0"
    enabled: bool = True
    risk_level: str = "low"          # low | medium | high | forbidden
    input_schema: dict = field(default_factory=dict)     # JSON Schema for arguments
    output_schema: dict = field(default_factory=dict)    # JSON Schema for output
    timeout_seconds: int = 30
    dry_run_supported: bool = True
    writes_artifact: bool = False
    reads_artifact: bool = False
    requires_approval: bool = False
    callable_by_llm: bool = True
    tags: list = field(default_factory=list)

    def __post_init__(self):
        if self.risk_level not in VALID_RISK_LEVELS:
            raise ValueError(f"Invalid risk_level: {self.risk_level}")
        if self.category and self.category not in VALID_TOOL_CATEGORIES:
            raise ValueError(f"Invalid category: {self.category}")

    def as_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "enabled": self.enabled,
            "risk_level": self.risk_level,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "timeout_seconds": self.timeout_seconds,
            "dry_run_supported": self.dry_run_supported,
            "writes_artifact": self.writes_artifact,
            "reads_artifact": self.reads_artifact,
            "requires_approval": self.requires_approval,
            "callable_by_llm": self.callable_by_llm,
            "tags": self.tags,
        }


@dataclass
class ToolInvocation:
    """A single tool invocation request.

    Created by the caller (Module Service or authorized component).
    NOT stored in agent/state.py tool_calls (which is legacy skill metadata).
    """

    invocation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tool_id: str = ""
    arguments: dict = field(default_factory=dict)
    workspace_id: Optional[str] = None
    run_id: Optional[str] = None
    job_id: Optional[str] = None
    dry_run: bool = False
    requested_by: str = ""            # e.g. "module:config_translation", "agent:admin"
    approval_id: Optional[str] = None  # Required for high-risk tools
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PolicyDecision:
    """Result of a ToolPolicy check."""

    allowed: bool = True
    reason: str = ""
    risk_level: str = "low"
    blocked_rules: list = field(default_factory=list)     # which rules blocked execution
    requires_approval: bool = False


@dataclass
class ToolResult:
    """Structured result of a tool invocation.

    Independent of agent/state.py tool_results (legacy skill metadata).
    """

    invocation_id: str = ""
    tool_id: str = ""
    status: str = "succeeded"         # succeeded | failed | blocked | dry_run
    output: dict = field(default_factory=dict)
    summary: str = ""
    artifact_ids: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    duration_ms: int = 0
    redacted: bool = False
    policy_decision: Optional[PolicyDecision] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.status not in VALID_TOOL_STATUSES:
            raise ValueError(f"Invalid status: {self.status}")

    def as_dict(self) -> dict:
        return {
            "invocation_id": self.invocation_id,
            "tool_id": self.tool_id,
            "status": self.status,
            "summary": self.summary[:500],
            "artifact_ids": self.artifact_ids,
            "warnings": self.warnings[:20],
            "errors": self.errors[:20],
            "duration_ms": self.duration_ms,
            "redacted": self.redacted,
            "policy_decision": self.policy_decision.__dict__ if self.policy_decision else None,
            "created_at": self.created_at,
        }
