"""Permission check — unified tool permission checking and approval routing.

Extracted from loop.py to separate permission/approval logic from the agentic loop.
"""

from agent.protocol.tool_result import ToolResult
from agent.runtime.permission_matrix import PermissionMatrix, PermissionAction, PermissionDecision


def check_tool_permission(tool_id: str, spec, context, turn) -> tuple[bool, bool]:
    """Check permission for a tool call.

    Returns:
        (requires_approval: bool, denied: bool, decision: PermissionDecision)
        - If denied is True, the tool must not be dispatched.
        - If requires_approval is True, the user must approve before dispatch.
    """
    pm = PermissionMatrix()
    risk_level = getattr(spec, 'risk_level', 'low') if spec else 'low'

    # Classify action — prefer spec.permission_action
    if spec and getattr(spec, 'permission_action', ''):
        pa = getattr(spec, 'permission_action', '')
        if pa == 'exec':
            action = PermissionAction.EXEC
        elif pa == 'write':
            action = PermissionAction.WRITE
        elif pa == 'network':
            action = PermissionAction.NETWORK
        else:
            action = PermissionAction.READ
    else:
        # Fallback to string-based inference
        turn.warnings.append(f"permission_action_inferred: {tool_id}")
        if risk_level == 'high':
            action = PermissionAction.EXEC
        elif tool_id.startswith(('workspace.file.', 'workspace.artifact.', 'knowledge.', 'memory.')) and \
                any(w in tool_id for w in ('edit', 'write', 'save', 'create',
                                           'patch', 'delete', 'archive',
                                           'import', 'export', 'update')):
            action = PermissionAction.WRITE
        elif tool_id.startswith(('web.', 'news.', 'weather.')):
            action = PermissionAction.NETWORK
        elif risk_level == 'medium' and any(w in tool_id for w in ('write', 'save', 'create', 'edit', 'patch', 'update', 'delete', 'archive', 'export')):
            action = PermissionAction.WRITE
        else:
            action = PermissionAction.READ

    decision = pm.check(tool_id, action, context, spec=spec)

    if decision == PermissionDecision.DENY:
        # DENY is terminal — it cannot be escalated to REQUIRE_APPROVAL.
        # High-risk tools (shell, python) are REQUIRE_APPROVAL by default via
        # the PermissionMatrix; if the matrix explicitly returns DENY (e.g. for
        # forbidden or unknown exec tools), that decision is final.
        turn.warnings.append(f"permission_denied_terminal: {tool_id}")
        return False, True, decision

    requires_approval = decision == PermissionDecision.REQUIRE_APPROVAL
    return requires_approval, False, decision


def check_shell_safety(tool_id: str, arguments: dict) -> tuple[bool, str]:
    """Check if a shell/powershell command is safe to execute.

    v3.9.5: delegates to ``tool_runtime.dangerous_patterns``. Only
    destructive patterns (rm -rf, dd if=, mkfs, fork bomb, PowerShell
    Invoke-Expression, etc.) cause ``(False, denied_word)``. Pipes,
    redirects, chaining, sensitive-path substrings, and arbitrary
    network commands all pass — they are medium risk and surface in
    the prompt layer instead of being blocked.

    Returns (safe: bool, denied_word: str).
    """
    if tool_id not in ('exec.run', 'exec.run'):
        return True, ""

    from tool_runtime.dangerous_patterns import scan_arguments_for_dangerous
    matched = scan_arguments_for_dangerous(arguments or {})
    if matched:
        return False, matched
    return True, ""


def needs_approval(tool_id: str, spec, risk_level: str, requires_approval: bool) -> bool:
    """Determine if a tool requires user approval."""
    is_high_risk = risk_level == 'high'
    return is_high_risk or requires_approval or getattr(spec, 'requires_approval', False)


def build_permission_denied_result(tool_id: str) -> ToolResult:
    """Build a ToolResult for a permission-denied tool call."""
    return ToolResult(
        ok=False,
        summary=f"Permission denied for {tool_id}",
        errors=["permission_denied"],
    )


def build_shell_denied_result(tool_id: str, denied_word: str) -> ToolResult:
    """Build a ToolResult for an unsafe shell command."""
    return ToolResult(
        ok=False,
        summary=f"Unsafe command denied: {denied_word}",
        errors=["unsafe_command_denied"],
    )
