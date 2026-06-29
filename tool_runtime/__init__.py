# tool_runtime/__init__.py
"""Tool Runtime Foundation v0.1 — atomic, auditable, policy-controlled tool execution.

This package provides the base layer for tool registration, policy enforcement,
execution, redaction, and audit metadata. Real device access is provided by
the canonical tool layer (``tool_runtime.canonical_registry`` — e.g.
``exec.run(target=ssh|telnet)``); this foundation layer is policy/registry
agnostic to where the call goes.

Architecture:
  Module Service → Tool Runtime → Tool Provider

Key components:
  - ToolSpec: tool definition and metadata
  - ToolInvocation: a single tool call request
  - ToolResult: structured execution result
  - ToolRegistry: tool registration and discovery
  - ToolPolicy: permission and safety enforcement
  - ToolExecutor: invocation → result pipeline
  - Redaction: output sanitization
  - Audit: trace/audit metadata builder
"""

from tool_runtime.schemas import ToolSpec, ToolInvocation, ToolResult, PolicyDecision
from tool_runtime.registry import ToolRegistry
from tool_runtime.policy import ToolPolicy, V02_FORBIDDEN_TOOLS
from tool_runtime.executor import ToolExecutor
from tool_runtime.redaction import redact_tool_output, contains_secret
from tool_runtime.audit import build_audit_event
