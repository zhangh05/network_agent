# agent/runtime/tool_execution/approval_stage.py
"""ApprovalStage — interrupt-based approval (non-blocking, durable).

v3.10: Approval is a runtime interrupt, not a blocking wait.
High-risk tools trigger interrupt_before_tool() → checkpoint → pending_action.
Execution resumes only through resume_after_approval().
No blocking store.wait() — that path is forbidden.
"""

from __future__ import annotations


class ApprovalStage:
    """Handle approval flow for high-risk tool calls via interrupt/resume."""

    def run(self, state, tool_call, spec, risk_level, requires_approval,
            arg_source, arg_risk, events, step):
        tid = tool_call.real_tool_id

        if not _needs_approval(tid, spec, risk_level, requires_approval):
            return None, False  # no approval needed

        # Shell safety check — block dangerous patterns immediately
        safe, denied_word = _check_shell_safety(tid, tool_call.arguments)
        if not safe:
            from agent.protocol.tool_result import ToolResult
            result = ToolResult(
                ok=False,
                summary=f"Tool {tid} blocked: unsafe command '{denied_word}'",
                errors=["unsafe_command_denied"],
            )
            events.tool_call_failed(tid, ["unsafe_command_denied"])
            events.record_tool_result(step, tid, False, "unsafe_command_denied")
            return result, True  # denied

        # v3.10: Create approval via interrupt (non-blocking)
        from agent.approval import get_approval_store
        store = get_approval_store()
        ws_id = getattr(state, 'workspace_id', '') or getattr(state.session, 'workspace_id', '')
        apr = store.create(
            session_id=state.session.session_id,
            tool_id=tid,
            arguments=tool_call.arguments,
            description=getattr(spec, 'description', '')[:200],
            risk_level=risk_level,
            workspace_id=ws_id,
            run_id=getattr(state, 'run_id', ''),
            job_id=getattr(state, 'job_id', ''),
            metadata={
                "argument_source": arg_source,
                "argument_risk": arg_risk.risk_level,
                "recommendation": arg_risk.recommendation or "",
                "reason": arg_risk.reason or "",
            },
        )
        events.approval_required(apr.approval_id, apr.tool_id)

        # v3.10: Interrupt (non-blocking) — return pending result.
        # The caller (pipeline/ActionExecutor) should see this as a pending state
        # and stop executing this tool until resume_after_approval is called.
        try:
            from agent.runtime.durable.interrupt import interrupt_before_tool
            # Build tool invocation dict for interrupt
            tool_invocation = {
                "tool_id": tid,
                "arguments": tool_call.arguments,
            }
            risk_decision = {
                "risk_level": risk_level,
                "reason": arg_risk.reason or f"High-risk tool {tid}",
            }
            # Find or create TaskState reference
            task_id = getattr(state, 'task_id', '') or ''
            interrupt_result = interrupt_before_tool(
                task=state,  # pass state which may have task_id attr
                step=step,
                tool_invocation=tool_invocation,
                risk_decision=risk_decision,
            )
            # Return pending — tool execution paused waiting for user decision
            from agent.protocol.tool_result import ToolResult
            pending_result = ToolResult(
                ok=False,
                summary=f"Approval required for {tid} (id={apr.approval_id})",
                errors=["approval_pending"],
                metadata={"approval_id": apr.approval_id, "status": "pending"},
            )
            events.approval_pending(apr.tool_id)
            return pending_result, True  # stop tool execution, waiting for resume
        except Exception as e:
            from agent.protocol.tool_result import ToolResult
            error_result = ToolResult(
                ok=False,
                summary=f"Approval interrupt setup failed for {tid}: {str(e)[:200]}",
                errors=["interrupt_setup_failed"],
            )
            events.tool_call_failed(tid, ["interrupt_setup_failed"])
            return error_result, True

    # For backward compat — the old API had an is_blocked method
    @staticmethod
    def is_blocked(result) -> bool:
        """Check if a result indicates blocked/pending approval."""
        if result is None:
            return False
        errs = getattr(result, 'errors', []) or []
        return bool(errs) and any(
            e in errs for e in ('approval_pending', 'unsafe_command_denied',
                                 'interrupt_setup_failed')
        )


# ── Internal helpers (kept local to avoid cross-module import loops) ──

def _check_shell_safety(tid: str, args: dict) -> tuple[bool, str]:
    """Check shell tool args for dangerous command patterns."""
    cmd = ""
    if isinstance(args, dict):
        cmd = str(args.get("command", args.get("cmd", "")))
    if not cmd:
        return True, ""
    # Block critical patterns immediately
    dangerous = ["rm -rf /", "mkfs.", "shutdown", "format c:", "> /dev/sda",
                 "dd if=", ":(){ :|:& };:", "curl | sh", "wget -O - | sh"]
    cmd_lower = cmd.lower()
    for d in dangerous:
        if d.lower() in cmd_lower:
            return False, d
    return True, ""


def _needs_approval(tid: str, spec, risk_level: str, requires_approval: bool) -> bool:
    """Determine if a tool call needs approval.

    v3.10: Delegates to CapabilityManifest when available.
    """
    if requires_approval:
        return True
    if risk_level in ("high", "critical"):
        return True
    # Check manifest for override
    try:
        from tool_runtime.manifest_registry import get_manifest
        m = get_manifest(tid)
        if m and m.requires_approval:
            return True
        if m and m.risk_level in ("high", "critical"):
            return True
        if m and m.destructive:
            return True
    except Exception:
        pass
    return False
