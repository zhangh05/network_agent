# tool_runtime/policy.py
"""ToolPolicy v0.2 — permission and safety enforcement with risk levels.

Checks:
  1. tool_id exists in registry
  2. tool enabled
  3. risk_level enforcement (low=allowed, medium=conditional, high=approval+gates)
  4. category allowed (v0.2 expanded categories)
  5. not a forbidden tool_id
  6. dry_run support
  7. timeout within limits
  8. arguments safe (no shell/ssh injection signatures)
  9. high-risk: requires_approval + approval_id check
  10. high-risk: dry_run default enforcement
  11. approved_exec: command_id/script_id from allowlist
"""

from tool_runtime.schemas import ToolSpec, ToolInvocation, PolicyDecision

# v0.2 allowed risk levels
V02_ALLOWED_RISK_LEVELS = {"low", "medium", "high"}

# v0.2 forbidden tool_ids — blocked at policy level even if registered
V02_FORBIDDEN_TOOLS = {
    "ssh.exec", "telnet.exec", "snmp.walk", "nmap.scan", "ping.sweep",
    "command.exec", "shell.exec", "device.exec", "config.push",
    "file.read_any", "file.write_any",
    "powershell.exec",
}

# v0.2 forbidden tool_id patterns — regex patterns that catch variants
# e.g. shell_exec_v2, config.push_force, ssh.exec_legacy
import re as _re
V02_FORBIDDEN_PATTERNS = [
    _re.compile(r"^shell[\._].*exec", _re.IGNORECASE),
    _re.compile(r"^ssh[\._].*exec", _re.IGNORECASE),
    _re.compile(r"^telnet[\._].*exec", _re.IGNORECASE),
    _re.compile(r"^snmp[\._].*(walk|set|write)", _re.IGNORECASE),
    _re.compile(r"^nmap[\._].*scan", _re.IGNORECASE),
    _re.compile(r"^ping[\._].*sweep", _re.IGNORECASE),
    _re.compile(r"^command\.exec$"),
    _re.compile(r"^command[\._]exec(?!_approved)[_\w]*$", _re.IGNORECASE),
    _re.compile(r"^device[\._].*exec", _re.IGNORECASE),
    _re.compile(r"^config[\._].*push", _re.IGNORECASE),
    _re.compile(r"^file[\._].*(read_any|write_any|delete_any)", _re.IGNORECASE),
    _re.compile(r"^powershell\.exec$"),
    _re.compile(r"^powershell[\._]exec(?!_approved)[_\w]*$", _re.IGNORECASE),
]

# v0.3 high-risk approved_exec tools — need approval_id but accept arbitrary commands
V02_APPROVED_EXEC_TOOLS = {
    "shell.exec",
    "powershell.exec",
}

# v0.3: handlers accept arbitrary commands, allowlists removed.
# Policy still enforces: high risk → requires approval_id,
# argument safety checks (no chaining/injection patterns).

from tool_runtime.schemas import V02_ALLOWED_CATEGORIES


class ToolPolicy:
    """Stateless policy checker for Tool Runtime v0.2.

    Supports low/medium/high risk levels with approval gates.
    All checks are pure functions. No side effects, no state.
    """

    def check(self, spec: ToolSpec, invocation: ToolInvocation) -> PolicyDecision:
        """Run all policy checks. Returns PolicyDecision."""
        blocked = []
        reason_parts = []

        # ── 1. Tool exists ──
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
        if spec.tool_id in V02_FORBIDDEN_TOOLS:
            blocked.append("forbidden_tool_id")
            reason_parts.append(f"Tool '{spec.tool_id}' is forbidden in v0.2")
        else:
            # Check regex patterns for forbidden variants
            for pattern in V02_FORBIDDEN_PATTERNS:
                if pattern.search(spec.tool_id):
                    blocked.append("forbidden_tool_id_pattern")
                    reason_parts.append(
                        f"Tool '{spec.tool_id}' matches forbidden pattern"
                    )
                    break

        # ── 4. Category check ──
        if spec.category and spec.category not in V02_ALLOWED_CATEGORIES:
            blocked.append("forbidden_category")
            reason_parts.append(f"Category '{spec.category}' not allowed in v0.2")

        # ── 5. Risk level gate ──
        if spec.risk_level not in V02_ALLOWED_RISK_LEVELS:
            blocked.append("risk_level_not_allowed")
            reason_parts.append(
                f"Tool '{spec.tool_id}' risk_level={spec.risk_level} not allowed"
            )

        # ── 6. HIGH risk: approval enforcement ──
        if spec.risk_level == "high" and not blocked:
            if not spec.requires_approval:
                blocked.append("high_risk_no_approval_required")
                reason_parts.append(
                    f"Tool '{spec.tool_id}' risk=high but requires_approval=false"
                )
            elif not invocation.approval_id:
                blocked.append("high_risk_no_approval_id")
                reason_parts.append(
                    f"Tool '{spec.tool_id}' requires approval_id, none provided"
                )

        # ── 7. HIGH risk: approved_exec — now accepts arbitrary commands,
        #     no allowlist check. Safety enforced by handler timeouts +
        #     argument injection checks below. ──

        # ── 8. Dry-run support ──
        if invocation.dry_run and not spec.dry_run_supported:
            blocked.append("dry_run_not_supported")
            reason_parts.append(f"Tool '{spec.tool_id}' does not support dry_run")

        # ── 9. Timeout ──
        max_timeout = 120 if spec.risk_level in ("medium", "high") else 60
        if spec.timeout_seconds > max_timeout:
            blocked.append("timeout_too_high")
            reason_parts.append(
                f"Tool '{spec.tool_id}' timeout {spec.timeout_seconds}s > {max_timeout}s limit"
            )

        # ── 10. Argument safety check ──
        arg_check = _check_argument_safety(invocation.arguments, spec.tool_id)
        if arg_check:
            blocked.append("unsafe_arguments")
            reason_parts.append(f"Unsafe arguments: {arg_check}")

        # ── Decision ──
        requires_approval = spec.risk_level == "high" and spec.requires_approval

        if blocked:
            return PolicyDecision(
                allowed=False,
                reason="; ".join(reason_parts),
                risk_level=spec.risk_level,
                blocked_rules=blocked,
                requires_approval=requires_approval,
            )

        return PolicyDecision(
            allowed=True,
            reason="ok",
            risk_level=spec.risk_level,
            blocked_rules=[],
            requires_approval=requires_approval,
        )


def _check_argument_safety(arguments: dict, tool_id: str = "") -> str:
    """Check arguments for injection or unsafe patterns."""
    args_str = str(arguments).lower()

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
        ("curl", "curl download not allowed in arguments"),
        ("wget", "wget download not allowed in arguments"),
        ("remove-item", "Destructive PowerShell command detected"),
        ("new-item", "File creation outside workspace detected"),
        ("set-executionpolicy", "Execution policy change not allowed"),
    ]

    # Shell/PowerShell specific checks
    if tool_id in ("shell.exec", "powershell.exec"):
        extra_checks = [
            ("&&", "Command chaining detected"),
            ("||", "Command chaining detected"),
            (";", "Command separator detected"),
            ("`", "Command substitution detected"),
            ("$(", "Shell expansion detected"),
            ("|", "Pipe detected"),
            (">", "Redirection detected"),
            ("<", "Input redirection detected"),
        ]
        FORBIDDEN_ARGS = FORBIDDEN_ARGS + extra_checks

    # PowerShell forbidden patterns (built-in, not configurable)
    POWERSHELL_FORBIDDEN_PATTERNS = [
        "Invoke-Expression", "Start-Process", "DownloadString",
        "Invoke-WebRequest", "Set-ExecutionPolicy", "Invoke-RestMethod",
    ]
    if tool_id == "powershell.exec":
        for pat in POWERSHELL_FORBIDDEN_PATTERNS:
            if pat.lower() in args_str:
                return f"PowerShell forbidden pattern: {pat}"

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
    import re
    return bool(re.match(r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$', tool_id))
