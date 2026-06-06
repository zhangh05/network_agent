# tool_runtime/policy.py
"""ToolPolicy — permission and safety enforcement for Tool Runtime v0.1.

Checks:
  1. tool_id exists in registry
  2. tool enabled
  3. risk_level allowed (v0.1: only low)
  4. category allowed
  5. not a forbidden tool_id
  6. dry_run support
  7. timeout within limits
  8. arguments safe (no shell/ssh injection signatures)
"""

from tool_runtime.schemas import ToolSpec, ToolInvocation, PolicyDecision

# v0.1 only low risk is allowed for execution
V01_ALLOWED_RISK_LEVELS = {"low"}

# v0.1 forbidden tool_ids — blocked at policy level even if registered
V01_FORBIDDEN_TOOLS = {
    "ssh.exec", "telnet.exec", "snmp.walk", "nmap.scan", "ping.sweep",
    "command.exec", "shell.exec", "device.exec", "config.push",
    "file.read_any", "file.write_any",
}

# v0.1 allowed categories (from schemas)
from tool_runtime.schemas import V01_ALLOWED_CATEGORIES


class ToolPolicy:
    """Stateless policy checker for Tool Runtime v0.1.

    All checks are pure functions. No side effects, no state.
    """

    def check(self, spec: ToolSpec, invocation: ToolInvocation) -> PolicyDecision:
        """Run all policy checks. Returns PolicyDecision.

        Args:
            spec: The ToolSpec from registry.
            invocation: The incoming ToolInvocation.
        """
        blocked = []
        reason_parts = []

        # ── 1. Tool exists ── (caller should validate; here as safeguard)
        if not spec.tool_id:
            return PolicyDecision(
                allowed=False, reason="tool_not_found",
                risk_level="forbidden",
                blocked_rules=["tool_not_found"],
            )

        # ── 2. Enabled ──
        if not spec.enabled:
            blocked.append("tool_disabled")
            reason_parts.append(f"Tool '{spec.tool_id}' is disabled")

        # ── 3. Forbidden tool_id ──
        if spec.tool_id in V01_FORBIDDEN_TOOLS:
            blocked.append("forbidden_tool_id")
            reason_parts.append(f"Tool '{spec.tool_id}' is forbidden in v0.1")

        # ── 4. Category check ──
        if spec.category and spec.category not in V01_ALLOWED_CATEGORIES:
            blocked.append("forbidden_category")
            reason_parts.append(f"Category '{spec.category}' not allowed in v0.1")

        # ── 5. Risk level ──
        if spec.risk_level != "low":
            blocked.append("risk_level_not_allowed")
            reason_parts.append(
                f"Tool '{spec.tool_id}' risk_level={spec.risk_level} "
                f"not allowed (v0.1 only allows low)"
            )

        # ── 6. Dry-run support ──
        if invocation.dry_run and not spec.dry_run_supported:
            blocked.append("dry_run_not_supported")
            reason_parts.append(f"Tool '{spec.tool_id}' does not support dry_run")

        # ── 7. Timeout ──
        if spec.timeout_seconds > 60:
            blocked.append("timeout_too_high")
            reason_parts.append(f"Tool '{spec.tool_id}' timeout {spec.timeout_seconds}s > 60s limit")

        # ── 8. Argument safety check ──
        arg_check = _check_argument_safety(invocation.arguments)
        if arg_check:
            blocked.append("unsafe_arguments")
            reason_parts.append(f"Unsafe arguments: {arg_check}")

        # ── Decision ──
        if blocked:
            return PolicyDecision(
                allowed=False,
                reason="; ".join(reason_parts),
                risk_level=spec.risk_level,
                blocked_rules=blocked,
                requires_approval=spec.risk_level != "low",
            )

        return PolicyDecision(
            allowed=True,
            reason="ok",
            risk_level=spec.risk_level,
            blocked_rules=[],
            requires_approval=False,
        )


def _check_argument_safety(arguments: dict) -> str:
    """Check arguments for injection or unsafe patterns."""
    args_str = str(arguments).lower()

    # Forbidden argument patterns
    FORBIDDEN_ARGS = [
        ("ssh", "SSH execution not allowed"),
        ("telnet", "Telnet execution not allowed"),
        ("snmp", "SNMP not allowed"),
        ("nmap", "Nmap not allowed"),
        ("ping sweep", "Ping sweep not allowed"),
        ("rm -rf", "Destructive shell command detected"),
        ("/etc/passwd", "Sensitive path detected"),
        ("/etc/shadow", "Sensitive path detected"),
        ("../", "Path traversal detected"),
    ]

    for pattern, reason in FORBIDDEN_ARGS:
        if pattern in args_str:
            return reason

    return ""


def validate_tool_id(tool_id: str) -> bool:
    """Validate tool_id naming convention: category.name"""
    if not tool_id or "." not in tool_id:
        return False
    parts = tool_id.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False
    # Must match: [a-z][a-z0-9_]*.[a-z][a-z0-9_]*
    import re
    return bool(re.match(r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$', tool_id))
