# tool_runtime/policy.py
"""ToolPolicy — permission and safety enforcement with risk levels.

Checks:
  1. tool_id exists in registry
  2. tool enabled
  3. risk_level metadata (low/medium/high); risk alone does not block calls
  4. category allowed (v0.2 expanded categories)
  5. not a forbidden tool_id
  6. dry_run support
  7. timeout within limits
  8. arguments safe (no shell/ssh injection signatures)
  9. unsafe arguments block execution
"""

from tool_runtime.schemas import ToolSpec, ToolInvocation, PolicyDecision

V02_ALLOWED_RISK_LEVELS = {"low", "medium", "high"}

# Forbidden tool_ids — blocked at policy level even if registered
V02_FORBIDDEN_TOOLS = {
    "ssh.exec", "telnet.exec", "snmp.walk", "nmap.scan", "ping.sweep",
    "command.exec", "device.exec", "config.push",
    "file.read_any", "file.write_any",
}

# Forbidden tool_id patterns — regex patterns that catch variants
# e.g. shell_exec_v2, config.push_force, ssh.exec_old
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
# V02_APPROVED_EXEC_TOOLS removed (manifest-driven)

# v0.3: handlers accept arbitrary commands, allowlists removed.
# Policy only blocks unsafe arguments (for example destructive shell commands).
# Risk/approval metadata is surfaced for UI/audit, but does not by itself deny a call.
# v3.10: All policy decisions derived from CapabilityManifest (not ToolSpec).

import logging
_log = logging.getLogger(__name__)


def _warn(msg: str):
    _log.warning(msg)
from tool_runtime.schemas import V02_ALLOWED_CATEGORIES


def is_tool_forbidden(tool_id: str) -> bool:
    """Check if a tool_id is forbidden (exact match or regex pattern).

    Single source of truth for forbidden tool checks — used by both
    tool_runtime.policy and agent.runtime.permission_matrix.
    """
    if tool_id in V02_FORBIDDEN_TOOLS:
        return True
    for pattern in V02_FORBIDDEN_PATTERNS:
        if pattern.search(tool_id):
            return True
    return False


# ── Safe Command Allowlist ──
# Commands whose first word is in this set are marked as safe-cmd
# (still subject to high-risk approval gates for exec tools).
SAFE_COMMAND_ALLOWLIST = {
    # Core shell utils
    "ls", "pwd", "cat", "head", "tail", "grep", "echo", "wc", "sort", "uniq",
    "cut", "tr", "awk", "sed", "find", "xargs", "tee", "diff", "cmp",
    "file", "stat", "du", "df", "which", "type", "env", "printenv",
    "mkdir", "touch", "cp", "mv", "rmdir",
    # Network diagnostics (read-only)
    "ip", "ifconfig", "hostname", "ping", "traceroute", "tracepath",
    "nslookup", "dig", "host", "netstat", "ss", "arp", "route",
    "curl", "wget", "scutil", "networksetup",
    # Process / system info (read-only)
    "ps", "top", "uptime", "uname", "whoami", "id", "groups",
    "lsof", "dmesg", "sysctl", "systemctl", "launchctl", "sw_vers",
    # Python / Git / Build
    "python", "python3", "pip", "pip3", "git", "node", "npm", "npx",
    "make", "cmake",
}


def is_safe_command_first_word(command: str) -> bool:
    """Check if the first word of a command is in the safe allowlist.

    Args:
        command: Full shell command string.

    Returns:
        True if the first word is in SAFE_COMMAND_ALLOWLIST.
    """
    if not command or not command.strip():
        return False
    first_word = command.strip().split(maxsplit=1)[0]
    return first_word in SAFE_COMMAND_ALLOWLIST


class ToolPolicy:
    """Stateless policy checker for Tool Runtime v0.2.

    Supports low/medium/high risk levels with approval gates.
    All checks are pure functions. No side effects, no state.
    """

    def check(self, spec: ToolSpec, invocation: ToolInvocation) -> PolicyDecision:
        """Run all policy checks. Returns PolicyDecision."""
        blocked = []
        reason_parts = []

        # ── 0. v3.10: CapabilityManifest is the single truth source ──
        # All policy decisions (risk, approval, idempotency, timeout, etc.)
        # must derive from CapabilityManifest, not ToolSpec alone.
        manifest = None
        if spec.tool_id:
            try:
                from tool_runtime.manifest_registry import get_manifest
                manifest = get_manifest(spec.tool_id)
            except Exception:
                pass

        # Override ToolSpec fields with manifest values (manifest is authoritative)
        if manifest:
            # If ToolSpec disagrees with manifest, log a warning
            if spec.risk_level and manifest.risk_level and spec.risk_level != manifest.risk_level:
                _warn(f"Tool {spec.tool_id}: ToolSpec risk={spec.risk_level} != manifest risk={manifest.risk_level}")
            effective_risk = manifest.risk_level or spec.risk_level or "low"
            effective_approval = manifest.requires_approval
            effective_destructive = manifest.destructive
            effective_idempotency = manifest.idempotency or "safe_to_retry"
            effective_timeout = manifest.timeout_seconds or spec.timeout_seconds or 30
        else:
            effective_risk = spec.risk_level or "low"
            effective_approval = spec.requires_approval
            effective_destructive = spec.destructive if hasattr(spec, 'destructive') else False
            effective_idempotency = "unknown"
            effective_timeout = spec.timeout_seconds or 30

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
        if is_tool_forbidden(spec.tool_id):
            blocked.append("forbidden_tool_id")
            reason_parts.append(f"Tool '{spec.tool_id}' is forbidden")

        # ── 4. Category check ──
        if spec.category and spec.category not in V02_ALLOWED_CATEGORIES:
            blocked.append("forbidden_category")
            reason_parts.append(f"Category '{spec.category}' not allowed in v0.2")

        # ── 5. Risk level gate ──
        if effective_risk not in V02_ALLOWED_RISK_LEVELS:
            blocked.append("risk_level_not_allowed")
            reason_parts.append(
                f"Tool '{spec.tool_id}' risk_level={effective_risk} not allowed"
            )

        # ── 6. Risk is metadata, not a call blocker ──
        # High-risk/destructive tools remain visible and callable by the LLM.
        # Safety enforcement happens on the arguments below.

        # ── 8. Dry-run support ──
        if invocation.dry_run and not spec.dry_run_supported:
            blocked.append("dry_run_not_supported")
            reason_parts.append(f"Tool '{spec.tool_id}' does not support dry_run")

        # ── 9. Timeout ──
        max_timeout = 600 if effective_risk == "high" else (300 if effective_risk == "medium" else 120)
        if effective_timeout > max_timeout:
            blocked.append("timeout_too_high")
            reason_parts.append(
                f"Tool '{spec.tool_id}' timeout {effective_timeout}s > {max_timeout}s limit"
            )

        # ── 10. Argument safety check ──
        arg_check = _check_argument_safety(invocation.arguments, spec.tool_id)
        if arg_check:
            blocked.append("unsafe_arguments")
            reason_parts.append(f"Unsafe arguments: {arg_check}")

        # ── Decision ──
        requires_approval = effective_risk == "high" and effective_approval

        if blocked:
            return PolicyDecision(
                allowed=False,
                reason="; ".join(reason_parts),
                risk_level=effective_risk,
                blocked_rules=blocked,
                requires_approval=requires_approval,
            )

        return PolicyDecision(
            allowed=True,
            reason="ok",
            risk_level=effective_risk,
            blocked_rules=[],
            requires_approval=requires_approval,
        )


def _check_argument_safety(arguments: dict, tool_id: str = "") -> str:
    """Check arguments for injection or unsafe patterns."""
    FORBIDDEN_ARGS = [
        ("snmp", "SNMP not allowed"),
        ("nmap", "Nmap not allowed"),
        ("ping sweep", "Ping sweep not allowed"),
        ("rm -rf", "Destructive shell command detected"),
        ("/etc/passwd", "Sensitive path detected"),
        ("/etc/shadow", "Sensitive path detected"),
        ("../", "Path traversal detected"),
        ("remove-item", "Destructive PowerShell command detected"),
        ("new-item", "File creation outside workspace detected"),
        ("set-executionpolicy", "Execution policy change not allowed"),
    ]

    # Shell/PowerShell specific checks. Only command-like fields are checked;
    # do not stringify the entire arguments dict, because user text may contain
    # examples such as "/etc/passwd" without being a path argument.
    if tool_id == "exec.run":
        command = str((arguments or {}).get("command", "")).lower()
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
        for pattern, reason in extra_checks:
            if pattern in command:
                return reason
        for pattern, reason in FORBIDDEN_ARGS:
            if pattern in command:
                return reason
    else:
        command = ""

    # PowerShell forbidden patterns (built-in, not configurable)
    POWERSHELL_FORBIDDEN_PATTERNS = [
        "Invoke-Expression", "Start-Process", "DownloadString",
        "Invoke-WebRequest", "Set-ExecutionPolicy", "Invoke-RestMethod",
    ]
    if tool_id == "exec.run":
        for pat in POWERSHELL_FORBIDDEN_PATTERNS:
            if pat.lower() in command:
                return f"PowerShell forbidden pattern: {pat}"

    for value in _iter_safety_relevant_values(arguments or {}):
        text = str(value).lower()
        for pattern, reason in FORBIDDEN_ARGS:
            if pattern in text:
                return reason

    return ""


def _iter_safety_relevant_values(arguments: dict):
    relevant_names = {
        "command", "cmd", "shell", "args", "path", "filepath", "file_path",
        "repo_path", "target_dir", "working_dir", "source", "destination",
    }
    for key, value in (arguments or {}).items():
        key_l = str(key).lower()
        if isinstance(value, dict):
            yield from _iter_safety_relevant_values(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield from _iter_safety_relevant_values(item)
                elif any(name in key_l for name in relevant_names):
                    yield item
        elif any(name in key_l for name in relevant_names):
            yield value


def validate_tool_id(tool_id: str) -> bool:
    """Validate tool_id naming convention: category.name"""
    if not tool_id or "." not in tool_id:
        return False
    parts = tool_id.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False
    import re
    return bool(re.match(r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$', tool_id))
