# agent/runtime/permission_matrix.py
"""Permission Matrix — single entry point for all permission decisions.

Provides a unified interface for checking tool permissions, path safety,
command safety, and network URL safety. Wires into existing policy checks
and serves as the authoritative decision point for all actions.
"""

import enum
import re
from pathlib import Path
from typing import Any

from tool_runtime.policy import (
    ToolPolicy,
    V02_FORBIDDEN_TOOLS,
    V02_FORBIDDEN_PATTERNS,
)
from tool_runtime.schemas import PolicyDecision


# ═══════════════════════════
# Enums
# ═══════════════════════════

class PermissionAction(str, enum.Enum):
    """Types of actions that can be checked."""
    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    NETWORK = "network"


class PermissionDecision(str, enum.Enum):
    """Outcome of a permission check."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


# ═══════════════════════════
# Matrix
# ═══════════════════════════

class PermissionMatrix:
    """Unified permission checker.

    Serves as the single entry point for all permission decisions,
    routing to appropriate policy checks based on tool_id and action type.
    """

    def __init__(self) -> None:
        self._tool_policy = ToolPolicy()

    def check(
        self,
        tool_id: str,
        action: PermissionAction,
        context: dict | None = None,
        spec: Any = None,
    ) -> PermissionDecision:
        """Check whether a tool/action is permitted.

        Args:
            tool_id: The tool identifier (e.g. 'exec.run', 'workspace.file').
            action: The action type (READ, WRITE, EXEC, NETWORK).
            context: Optional context dict with workspace_id, session_id, etc.
            spec: Optional ToolSpec for richer policy checking.

        Returns:
            PermissionDecision: ALLOW, DENY, or REQUIRE_APPROVAL.
        """
        # 1. Check forbidden tools (single source of truth: tool_runtime.policy)
        from tool_runtime.policy import is_tool_forbidden
        if is_tool_forbidden(tool_id):
            return PermissionDecision.DENY

        # 2. Check action-specific rules
        if action == PermissionAction.EXEC:
            # Unified local/remote command execution always needs approval.
            if tool_id == "exec.run":
                return PermissionDecision.REQUIRE_APPROVAL
            # Unknown exec tools are denied
            return PermissionDecision.DENY

        if action == PermissionAction.NETWORK:
            # Network actions: check if tool is in web category
            if spec and getattr(spec, 'category', '') in ('web', 'news', 'weather'):
                # Also check URL safety if arguments contain a URL
                if context:
                    url = ""
                    if isinstance(context, dict):
                        url = context.get("url") or context.get("arguments", {}).get("url", "")
                    elif hasattr(context, "user_input"):
                        # TurnContext or similar object — check safe_context for URL
                        sc = getattr(context, "safe_context", {}) or {}
                        url = sc.get("url", "")
                    if url and not check_network_url(str(url)):
                        return PermissionDecision.DENY
                return PermissionDecision.ALLOW
            # Unknown network tools require approval
            return PermissionDecision.REQUIRE_APPROVAL

        if action == PermissionAction.WRITE:
            # Write actions: check tool spec risk level
            if spec and getattr(spec, 'risk_level', '') == 'high':
                return PermissionDecision.REQUIRE_APPROVAL
            if spec and getattr(spec, 'risk_level', '') == 'medium':
                return PermissionDecision.ALLOW  # medium is allowed but audited
            # Low-risk WRITE with known tool → ALLOW
            return PermissionDecision.ALLOW

        if action == PermissionAction.READ:
            # Read actions are generally allowed
            return PermissionDecision.ALLOW

        # Default: deny unknown tools
        return PermissionDecision.DENY

    def check_tool(self, spec, invocation) -> PolicyDecision:
        """Run full policy check using the existing ToolPolicy.

        Args:
            spec: ToolSpec for the tool being invoked.
            invocation: ToolInvocation with arguments and context.

        Returns:
            PolicyDecision from the policy system.
        """
        return self._tool_policy.check(spec, invocation)

    def action_for_tool(self, tool_id: str) -> PermissionAction:
        """Determine the permission action category for a tool_id.

        Args:
            tool_id: The tool identifier.

        Returns:
            PermissionAction category (READ, WRITE, EXEC, NETWORK).
        """
        if tool_id == "exec.run":
            return PermissionAction.EXEC
        if tool_id in {"web.manage", "browser.manage"}:
            return PermissionAction.NETWORK
        read_tools = (
            "workspace.artifact", "workspace.file", "workspace.filestore",
            "workspace.metadata.get", "workspace.document.pdf.extract_text",
            "knowledge.manage", "memory.manage", "skill.manage",
            "system.manage", "text.analyze", "data.manage",
            "report.manage", "code.search", "pcap.manage", "config.manage",
        )
        if tool_id in read_tools:
            return PermissionAction.READ
        return PermissionAction.WRITE


# ═══════════════════════════
# Safety check functions
# ═══════════════════════════

# Dangerous paths that should never be accessed
# v3.9.5: named ``_DANGEROUS_PATH_PATTERNS`` (was ``_DANGEROUS_PATTERNS``)
# to avoid collision with the command-level dangerous pattern set in
# ``tool_runtime.dangerous_patterns``.
_DANGEROUS_PATHS = {
    "/etc/passwd", "/etc/shadow", "/etc/sudoers",
    "/root", "/var/root",
    "~/.ssh", "~/.aws", "~/.config",
    "/proc", "/sys", "/dev",
    "C:\\Windows\\System32",
    "C:\\Users\\Administrator",
}

_DANGEROUS_PATH_PATTERNS = [
    re.compile(r"^~?/\.(ssh|aws|gnupg|docker|kube|config)"),
    re.compile(r"^/etc/(passwd|shadow|sudoers|ssl|certs)"),
    re.compile(r"^/proc/"),
    re.compile(r"^/sys/"),
    re.compile(r"^/dev/"),
    re.compile(r"^/root/"),
    re.compile(r"^/var/root/"),
    re.compile(r"^C:\\Windows\\System32", re.IGNORECASE),
    re.compile(r"^C:\\Users\\Administrator", re.IGNORECASE),
]


def check_dangerous_path(path: str) -> bool:
    """Check if a file path is dangerous/sensitive.

    Args:
        path: Absolute or relative file path.

    Returns:
        True if the path is dangerous and should be blocked.
    """
    normalized = str(Path(path).expanduser().resolve())
    norm_lower = normalized.lower()

    # Check exact matches
    for dangerous in _DANGEROUS_PATHS:
        check = str(Path(dangerous).expanduser().resolve()).lower()
        if norm_lower == check or norm_lower.startswith(check + "/"):
            return True

    # Check patterns
    for pattern in _DANGEROUS_PATH_PATTERNS:
        if pattern.search(normalized) or pattern.search(path):
            return True

    # Block path traversal
    if ".." in path.replace("\\", "/"):
        return True

    return False


def check_safe_command(command: str) -> bool:
    """v3.9.5: removed. The legacy character blacklist is gone. Shell
    command safety is decided by
    :func:`tool_runtime.dangerous_patterns.is_destructive_command`
    which returns True only for explicitly destructive patterns
    (rm -rf, dd if=, mkfs, etc.). This stub is kept only to preserve
    any import sites during the transition; new code should call
    :func:`is_destructive_command` directly.
    """
    from tool_runtime.dangerous_patterns import is_destructive_command
    return not is_destructive_command(command or "")


def check_network_url(url: str) -> bool:
    """Check if a network URL is safe to access.

    Args:
        url: HTTP/HTTPS URL string.

    Returns:
        True if the URL is safe for general access.
    """
    from urllib.parse import urlparse

    if not url or not url.strip():
        return False

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    # Only allow http/https
    if parsed.scheme not in ("http", "https"):
        return False

    # Block localhost and private IP ranges
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False

    # Block localhost
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False

    # Block private IP ranges
    PRIVATE_PREFIXES = (
        "10.", "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
        "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
        "172.30.", "172.31.", "192.168.", "169.254.", "198.18.",
        "198.19.",
    )
    for prefix in PRIVATE_PREFIXES:
        if hostname.startswith(prefix):
            return False

    # Block internal/private TLDs
    BLOCKED_TLDS = (".local", ".internal", ".localhost", ".test", ".example")
    for tld in BLOCKED_TLDS:
        if hostname.endswith(tld):
            return False

    return True
