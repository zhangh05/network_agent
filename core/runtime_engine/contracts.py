"""
Tool Contract System for SSOT Runtime Engine.

Every canonical tool MUST have a ToolContract declaring:
  - input/output schema
  - side effect classification
  - risk level
  - idempotency
  - concurrency group
  - approval requirement
  - rollback support

This is the source of truth for semantic validation, risk policy,
scheduling, and rollback.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolContract:
    """Immutable contract for a single canonical tool.

    v3.10 (retry policy): the dataclass defaults are intentionally
    conservative. A new contract that omits ``idempotent`` /
    ``max_retries`` / ``side_effect`` will be treated as unsafe and
    will NOT be retried by the ToolRetryPolicy:

      - ``idempotent = False``        — never auto-retry
      - ``max_retries = 0``           — at most zero retries
      - ``side_effect = "unknown"``   — never auto-retry

    Every entry in ``BUILTIN_CONTRACTS`` below sets the relevant
    fields explicitly, so the dataclass defaults only matter for
    contracts added at runtime / future / unknown tools.
    """
    name: str
    display_name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    side_effect: str = "unknown"        # read | write_file | mutate_local | mutate_remote | execute_command | external_request | credential_access | unknown
    risk_level: str = "low"             # low | medium | high | critical
    idempotent: bool = False
    timeout_seconds: int = 60
    max_retries: int = 0
    concurrency_group: str | None = None
    requires_approval: bool = False
    rollback_supported: bool = False
    optional: bool = False
    priority: str = "normal"            # high | normal | low


# ============================================================================
# Built-in Contract Registry — all 22 canonical tools
# ============================================================================

BUILTIN_CONTRACTS: dict[str, ToolContract] = {
    # --- exec ---
    "exec.run": ToolContract(
        name="exec.run",
        display_name="Shell Execution",
        description="Execute shell commands locally or remotely",
        input_schema={
            "required": ["command"],
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number"},
                "cwd": {"type": "string"},
                "env": {"type": "object"},
            },
        },
        output_schema={"properties": {"stdout": {"type": "string"}, "stderr": {"type": "string"}, "exit_code": {"type": "number"}}},
        side_effect="execute_command",
        risk_level="medium",
        idempotent=False,
        timeout_seconds=120,
        max_retries=0,
        concurrency_group="shell",
        requires_approval=False,
        rollback_supported=False,
    ),

    # --- git ---
    "git.manage": ToolContract(
        name="git.manage",
        display_name="Git Management",
        description="Manage git repository operations",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["status", "diff", "log", "commit", "push", "branch", "checkout"]}}},
        output_schema={},
        side_effect="write_file",
        risk_level="medium",
        idempotent=False,
        timeout_seconds=60,
        concurrency_group="git",
        requires_approval=False,
        rollback_supported=True,
    ),

    # --- device ---
    "device.manage": ToolContract(
        name="device.manage",
        display_name="Device Asset Management",
        description="Manage CMDB device assets",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["list", "get", "add", "update", "delete", "export"]}}},
        output_schema={},
        side_effect="mutate_local",
        risk_level="medium",
        idempotent=False,
        timeout_seconds=30,
        concurrency_group="cmdb",
        rollback_supported=True,
        optional=True,
    ),

    # --- browser ---
    "browser.manage": ToolContract(
        name="browser.manage",
        display_name="Browser Automation",
        description="Automate browser interactions via Playwright",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["navigate", "extract", "screenshot", "click", "fill"]}}},
        output_schema={},
        side_effect="external_request",
        risk_level="medium",
        idempotent=False,
        timeout_seconds=90,
        concurrency_group="browser",
        requires_approval=False,
    ),

    # --- web ---
    "web.manage": ToolContract(
        name="web.manage",
        display_name="Web Search",
        description="Web search, weather, and page fetch",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["search", "weather", "page"]}}},
        output_schema={},
        side_effect="external_request",
        risk_level="low",
        idempotent=True,
        timeout_seconds=30,
        concurrency_group="external_http",
    ),

    # --- data ---
    "data.manage": ToolContract(
        name="data.manage",
        display_name="Data Processing",
        description="Process structured data (csv, table, validate, filter, deduplicate)",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["csv", "table", "validate", "filter", "deduplicate"]}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=30,
        max_retries=1,
    ),

    # --- report ---
    "report.manage": ToolContract(
        name="report.manage",
        display_name="Report Rendering",
        description="Render reports in markdown, mermaid, HTML, diff formats",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["markdown", "artifact", "summary", "mermaid", "html", "diff"]}}},
        output_schema={},
        side_effect="write_file",
        risk_level="low",
        idempotent=True,
        timeout_seconds=30,
    ),

    # --- config ---
    "config.manage": ToolContract(
        name="config.manage",
        display_name="Config Analysis",
        description="Parse, translate, extract, diff, and summarize configuration",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["parse", "translate", "extract", "diff", "summarize"]}}},
        output_schema={},
        side_effect="read",
        risk_level="medium",
        idempotent=True,
        timeout_seconds=60,
        max_retries=1,
    ),

    # --- pcap ---
    "pcap.manage": ToolContract(
        name="pcap.manage",
        display_name="PCAP Analysis",
        description="Analyze network packet captures",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["parse", "session", "filter", "align"]}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=120,
        max_retries=1,
    ),

    # --- knowledge ---
    "knowledge.manage": ToolContract(
        name="knowledge.manage",
        display_name="Knowledge Base",
        description="Search, read, import knowledge base documents",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["search", "read", "import", "source_manage"]}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=30,
        concurrency_group="external_http",
        max_retries=1,
    ),

    # --- memory ---
    "memory.manage": ToolContract(
        name="memory.manage",
        display_name="Memory Management",
        description="Create, search, update, confirm, and delete memory records",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["search", "create", "update", "confirm", "delete", "profile"]}}},
        output_schema={},
        side_effect="mutate_local",
        risk_level="low",
        idempotent=False,
        timeout_seconds=15,
        rollback_supported=True,
    ),

    # --- skill ---
    "skill.manage": ToolContract(
        name="skill.manage",
        display_name="Skill Management",
        description="List, find, load, and inspect agent skills",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["list", "find", "load", "inspect"]}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=10,
        max_retries=1,
    ),

    # --- agent ---
    "agent.manage": ToolContract(
        name="agent.manage",
        display_name="Multi-Agent Management",
        description="Spawn sub-agents, run team tasks, retrieve results",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["spawn", "team_run", "result_get", "role_list"]}}},
        output_schema={},
        side_effect="execute_command",
        risk_level="medium",
        idempotent=False,
        timeout_seconds=300,
        concurrency_group="subagent",
        requires_approval=False,
    ),

    # --- system ---
    "system.manage": ToolContract(
        name="system.manage",
        display_name="System Introspection",
        description="System diagnostics, health checks, self-check, audit",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["diagnostics", "health", "selfcheck", "tasks", "audit", "run", "session", "review"]}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=15,
        max_retries=1,
    ),

    # --- text ---
    "text.analyze": ToolContract(
        name="text.analyze",
        display_name="Text Analysis",
        description="Redact, diff, extract keywords, classify, regex",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["redact", "diff", "keywords", "classify", "extract_entities", "regex"]}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=15,
        max_retries=1,
    ),

    # --- code ---
    "code.search": ToolContract(
        name="code.search",
        display_name="Code Search",
        description="Search code with ripgrep",
        input_schema={"required": ["query"], "properties": {"query": {"type": "string"}, "path": {"type": "string"}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=30,
        max_retries=1,
    ),

    # --- workspace.file ---
    "workspace.file": ToolContract(
        name="workspace.file",
        display_name="Workspace File Operations",
        description="Read, write, edit, glob, and delete workspace files",
        input_schema={"required": ["action", "path"], "properties": {
            "action": {"type": "string", "enum": ["list", "read", "read_image", "edit", "patch", "write_artifact", "glob", "delete_file"]},
            "path": {"type": "string"},
        }},
        output_schema={},
        side_effect="write_file",
        risk_level="medium",
        idempotent=False,
        timeout_seconds=30,
        concurrency_group="filesystem",
        rollback_supported=True,
    ),

    # --- workspace.artifact ---
    "workspace.artifact": ToolContract(
        name="workspace.artifact",
        display_name="Workspace Artifact Operations",
        description="List, read, save, tag, delete, diff, and export artifacts",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["list", "read", "save", "tag", "delete", "diff", "export"]}}},
        output_schema={},
        side_effect="mutate_local",
        risk_level="low",
        idempotent=False,
        timeout_seconds=15,
        rollback_supported=True,
    ),

    # --- workspace.filestore ---
    "workspace.filestore": ToolContract(
        name="workspace.filestore",
        display_name="Workspace FileStore",
        description="Reference and import file store items",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["references", "import"]}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=15,
        max_retries=1,
    ),

    # --- workspace.metadata ---
    "workspace.metadata.get": ToolContract(
        name="workspace.metadata.get",
        display_name="Workspace Metadata",
        description="Retrieve workspace metadata",
        input_schema={"required": [], "properties": {}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=5,
        max_retries=1,
    ),

    # --- workspace.document.pdf ---
    "workspace.document.pdf.extract_text": ToolContract(
        name="workspace.document.pdf.extract_text",
        display_name="PDF Text Extraction",
        description="Extract text from PDF documents",
        input_schema={"required": ["path"], "properties": {"path": {"type": "string"}}},
        output_schema={},
        side_effect="read",
        risk_level="low",
        idempotent=True,
        timeout_seconds=60,
        max_retries=1,
    ),

    # --- inspection ---
    "inspection.manage": ToolContract(
        name="inspection.manage",
        display_name="CMDB Device Inspection",
        description="CMDB-driven device health inspection",
        input_schema={"required": ["action"], "properties": {"action": {"type": "string", "enum": ["start", "status", "result", "cancel"]}}},
        output_schema={},
        side_effect="execute_command",
        risk_level="medium",
        idempotent=False,
        timeout_seconds=300,
        concurrency_group="ssh",
        requires_approval=False,
    ),
}


def _sync_contracts_from_canonical_registry() -> None:
    """Keep SSOT Runtime's semantic contract layer aligned with canonical tools.

    SSOT Runtime owns scheduling/risk metadata such as concurrency groups, retry
    defaults, and per-stage timeouts. It must not own a second copy of public
    input schemas or user-facing tool descriptions; those belong to
    ``core.tools.canonical_registry`` and are also what the planner sees via
    ToolRuntimeClient. Syncing here prevents drift such as weather forecast
    parameters or inspection actions disappearing from semantic validation.
    """
    try:
        from core.tools.canonical_registry import CANONICAL_REGISTRY
    except Exception:
        return

    for tool_id, entry in CANONICAL_REGISTRY.items():
        contract = BUILTIN_CONTRACTS.get(tool_id)
        if contract is None:
            continue
        contract.description = entry.description or contract.description
        contract.input_schema = deepcopy(entry.input_schema or {})
        # Do not copy manifest risk/approval/timeout here. SSOT Runtime owns its
        # execution risk model separately from LLM visibility. For example,
        # exec.run remains high-risk in SSOT Runtime even if the runtime manifest
        # applies more granular command-level policy later.


_sync_contracts_from_canonical_registry()


def get_contract(tool_name: str) -> ToolContract | None:
    """Get the ToolContract for a canonical tool. Returns None if unknown."""
    return BUILTIN_CONTRACTS.get(tool_name)


def get_side_effect(tool_name: str) -> str:
    """Get the side_effect type for a tool. Defaults to 'read'."""
    contract = BUILTIN_CONTRACTS.get(tool_name)
    return contract.side_effect if contract else "read"


def get_risk_level(tool_name: str) -> str:
    """Get the risk level for a tool. Defaults to 'low'."""
    contract = BUILTIN_CONTRACTS.get(tool_name)
    return contract.risk_level if contract else "low"


def get_concurrency_group(tool_name: str) -> str | None:
    """Get the concurrency group for a tool."""
    contract = BUILTIN_CONTRACTS.get(tool_name)
    return contract.concurrency_group if contract else None
