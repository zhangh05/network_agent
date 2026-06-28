# agent/runtime/tool_execution/approval_stage.py
"""ApprovalStage — interrupt-based approval (non-blocking, durable). v3.10."""

from __future__ import annotations


class ApprovalStage:
    """Handle approval flow for high-risk tool calls via interrupt/resume."""

    def run(self, state, tool_call, spec, risk_level, requires_approval,
            arg_source, arg_risk, events, step):
        tid = tool_call.real_tool_id

        if not _needs_approval(tid, spec, risk_level, requires_approval):
            return None, False

        # v3.9.5: shell safety is destructive-only. We delegate to the
        # unified pattern set in tool_runtime.dangerous_patterns. If a
        # destructive command is detected, the policy layer (run before
        # us) has already escalated risk to "high" + requires_approval;
        # here we just verify the bubble interrupt setup is correct.
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
            return result, True

        # v3.10: Interrupt — explicit task_id/step_id binding
        ws_id = getattr(state, 'workspace_id', '') or getattr(state.session, 'workspace_id', '')
        sid = getattr(state.session, 'session_id', '')
        rid = getattr(state, 'run_id', '') or getattr(getattr(state, 'turn', None), 'turn_id', '')
        task_id = getattr(state, 'task_id', '') or ''

        if not task_id or not ws_id:
            from agent.protocol.tool_result import ToolResult
            return ToolResult(
                ok=False,
                summary=f"Cannot interrupt: missing task_id or workspace_id",
                errors=["interrupt_missing_context"],
            ), True

        try:
            from agent.runtime.durable.interrupt import interrupt_before_tool
            interrupt_result = interrupt_before_tool(
                task_id=task_id,
                ws_id=ws_id,
                session_id=sid,
                run_id=rid,
                step_id=getattr(step, 'step_id', str(step)),
                tool_invocation={
                    "tool_id": tid,
                    "arguments": dict(tool_call.arguments),
                },
                risk_decision={
                    "risk_level": risk_level,
                    "reason": f"High-risk tool {tid} requires approval",
                },
            )
            if not interrupt_result.get("ok"):
                from agent.protocol.tool_result import ToolResult
                return ToolResult(
                    ok=False,
                    summary=f"Interrupt setup failed: {interrupt_result.get('error', 'unknown')}",
                    errors=["interrupt_setup_failed"],
                ), True

            from agent.protocol.tool_result import ToolResult
            pending = ToolResult(
                ok=False,
                summary=f"Approval required for {tid} (id={interrupt_result['approval_id']})",
                errors=["approval_pending"],
                metadata={
                    "approval_id": interrupt_result["approval_id"],
                    "status": "pending",
                    "task_id": task_id,
                },
            )
            return pending, True
        except Exception as e:
            from agent.protocol.tool_result import ToolResult
            return ToolResult(
                ok=False,
                summary=f"Approval interrupt failed: {str(e)[:200]}",
                errors=["interrupt_setup_failed"],
            ), True


    @staticmethod
    def is_blocked(result) -> bool:
        if result is None: return False
        errs = getattr(result, 'errors', []) or []
        return bool(errs) and any(e in errs for e in (
            'approval_pending', 'unsafe_command_denied', 'interrupt_setup_failed'
        ))


def _check_shell_safety(tid: str, args: dict) -> tuple[bool, str]:
    """v3.9.5: delegate to the unified dangerous-pattern scanner.

    Earlier versions embedded their own short list of destructive
    substrings (rm -rf, mkfs, etc.) and missed several real-world
    cases. The single source of truth is now
    :mod:`tool_runtime.dangerous_patterns`.
    """
    from tool_runtime.dangerous_patterns import scan_arguments_for_dangerous
    if not isinstance(args, dict):
        return True, ""
    matched = scan_arguments_for_dangerous(args)
    if matched:
        return False, matched
    return True, ""


def _needs_approval(tid: str, spec, risk_level: str, requires_approval: bool) -> bool:
    if requires_approval: return True
    if risk_level in ("high", "critical"): return True
    try:
        from tool_runtime.manifest_registry import get_manifest
        m = get_manifest(tid)
        if m and (m.requires_approval or m.risk_level in ("high", "critical") or m.destructive):
            return True
    except Exception:
        pass
    return False
