# tool_runtime/executor.py
"""ToolExecutor — execute a ToolInvocation through the full pipeline.

Pipeline:
  1. Validate invocation + lookup ToolSpec
  2. Validate arguments against input_schema
  3. Run ToolPolicy.check()
  4. If blocked → return ToolResult("blocked")
  5. If dry_run and supported → execute dry-run handler or return early
  6. Execute handler
  7. Redact output
  8. Build audit metadata
  9. Return structured ToolResult
"""

import time
from tool_runtime.schemas import ToolSpec, ToolInvocation, ToolResult, PolicyDecision
from tool_runtime.registry import ToolRegistry
from tool_runtime.policy import ToolPolicy
from tool_runtime.redaction import redact_tool_output
from tool_runtime.audit import build_audit_event


class ToolExecutor:
    """Execute a single tool invocation with full safety pipeline."""

    def __init__(self, registry: ToolRegistry, policy: ToolPolicy = None):
        self.registry = registry
        self.policy = policy or ToolPolicy()

    def execute(self, invocation: ToolInvocation) -> ToolResult:
        """Execute a tool invocation through the full pipeline.

        Returns a structured ToolResult. Never raises — all errors are captured.
        """
        start_time = time.time()

        # ── 1. Validate invocation ──
        if not invocation.tool_id:
            return _failed_result(invocation.invocation_id, "", "Missing tool_id", 0)

        # ── 2. Lookup ToolSpec ──
        spec = self.registry.get_tool(invocation.tool_id)
        if spec is None:
            return _failed_result(
                invocation.invocation_id, invocation.tool_id,
                f"Tool not found: {invocation.tool_id}",
                int((time.time() - start_time) * 1000),
            )

        # ── 3. Validate arguments against schema ──
        schema_errors = _validate_arguments(invocation.arguments, spec.input_schema)
        if schema_errors:
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status="blocked",
                summary=f"Schema validation failed: {', '.join(schema_errors)}",
                errors=schema_errors,
                duration_ms=int((time.time() - start_time) * 1000),
                redacted=False,
                policy_decision=PolicyDecision(allowed=False, reason="schema_validation_failed",
                                               risk_level=spec.risk_level,
                                               blocked_rules=["schema_validation"]),
            )

        # ── 4. Policy check ──
        decision = self.policy.check(spec, invocation)
        if not decision.allowed:
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status="blocked",
                summary=f"Blocked by policy: {decision.reason}",
                errors=[decision.reason],
                duration_ms=int((time.time() - start_time) * 1000),
                redacted=False,
                policy_decision=decision,
            )

        # ── 5. Handle dry_run ──
        if invocation.dry_run and spec.dry_run_supported:
            # Tools that support dry_run should implement their own handler logic.
            # If the handler returns a dict with "dry_run" key, the executor
            # treats it as dry-run output.
            handler = self.registry.get_handler(invocation.tool_id)
            if handler is None:
                return _failed_result(
                    invocation.invocation_id, invocation.tool_id,
                    "Handler not found for dry_run",
                    int((time.time() - start_time) * 1000),
                )
            try:
                raw = handler(invocation)
                # Redact output
                raw_safe = redact_tool_output(raw) if isinstance(raw, dict) else {"output": str(raw)}
                duration = int((time.time() - start_time) * 1000)
                result = ToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=invocation.tool_id,
                    status="dry_run",
                    output=raw_safe,
                    summary=raw_safe.get("summary", f"dry_run completed for {invocation.tool_id}"),
                    duration_ms=duration,
                    redacted=True,
                    policy_decision=decision,
                )
                return result
            except Exception as exc:
                return _failed_result(
                    invocation.invocation_id, invocation.tool_id,
                    f"dry_run failed: {str(exc)[:200]}",
                    int((time.time() - start_time) * 1000),
                )

        # ── 6. Execute handler ──
        handler = self.registry.get_handler(invocation.tool_id)
        if handler is None:
            return _failed_result(
                invocation.invocation_id, invocation.tool_id,
                "Handler not found",
                int((time.time() - start_time) * 1000),
            )

        try:
            raw = handler(invocation)
        except Exception as exc:
            return _failed_result(
                invocation.invocation_id, invocation.tool_id,
                f"Execution failed: {str(exc)[:200]}",
                int((time.time() - start_time) * 1000),
            )

        # ── 7. Redact output ──
        output = redact_tool_output(raw) if isinstance(raw, dict) else {"output": str(raw)}

        duration = int((time.time() - start_time) * 1000)

        # ── 8. Build result ──
        summary = output.get("summary", f"Tool {invocation.tool_id} completed")
        if len(summary) > 500:
            summary = summary[:497] + "..."

        result = ToolResult(
            invocation_id=invocation.invocation_id,
            tool_id=invocation.tool_id,
            status="succeeded",
            output=output,
            summary=summary,
            warnings=output.get("warnings", []),
            errors=output.get("errors", []),
            artifact_ids=output.get("artifact_ids", []),
            duration_ms=duration,
            redacted=True,
            policy_decision=decision,
        )

        return result


def _validate_arguments(arguments: dict, schema: dict) -> list:
    """Validate arguments against a simple JSON Schema subset.

    Only validates 'required' and 'type' checks.
    Returns list of error strings (empty = valid).
    """
    errors = []
    if not schema:
        return errors

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    # Check required fields
    for field in required:
        if field not in arguments:
            errors.append(f"Missing required field: '{field}'")

    # Check types
    for field, field_schema in properties.items():
        if field not in arguments:
            continue
        expected_type = field_schema.get("type", "")
        value = arguments[field]
        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"Field '{field}' expected string, got {type(value).__name__}")
        elif expected_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"Field '{field}' expected number, got {type(value).__name__}")
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(f"Field '{field}' expected boolean, got {type(value).__name__}")
        elif expected_type == "object" and not isinstance(value, dict):
            errors.append(f"Field '{field}' expected object, got {type(value).__name__}")

    return errors


def _failed_result(invocation_id: str, tool_id: str, error: str, duration_ms: int) -> ToolResult:
    """Build a standard failure result."""
    return ToolResult(
        invocation_id=invocation_id,
        tool_id=tool_id,
        status="failed",
        summary=error[:200],
        errors=[error[:200]],
        duration_ms=duration_ms,
        redacted=False,
    )
