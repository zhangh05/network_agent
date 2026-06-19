# agent/runtime/response/renderer.py
"""ResponseRenderer — renders a ResponsePlan into human-readable Chinese text."""

from __future__ import annotations

from agent.runtime.response.models import ResponsePlan


class ResponseRenderer:
    """Render a ResponsePlan into a readable content string."""

    def render(self, plan: ResponsePlan, ctx=None) -> str:
        handler = _RENDERERS.get(plan.response_type, _render_answer)
        return handler(plan, ctx)


def _render_answer(plan: ResponsePlan, ctx=None) -> str:
    parts: list[str] = []
    if plan.main_points:
        parts.extend(plan.main_points)
    if plan.warnings:
        parts.append("注意: " + "; ".join(plan.warnings))
    return "\n".join(parts) if parts else ""


def _render_progress(plan: ResponsePlan, ctx=None) -> str:
    lines = [f"任务 {plan.task_id} 进行中"]
    if plan.main_points:
        lines.extend(f"- {p}" for p in plan.main_points)
    if plan.next_actions:
        lines.append("下一步: " + ", ".join(plan.next_actions))
    return "\n".join(lines)


def _render_artifact(plan: ResponsePlan, ctx=None) -> str:
    lines = ["已生成以下产出:"]
    artifact_records = (ctx.metadata.get("artifact_records") or []) if ctx else []
    for rec in artifact_records:
        if isinstance(rec, dict):
            lines.append(f"- [{rec.get('kind', '')}] {rec.get('title', '')} ({rec.get('status', '')})")
    if not artifact_records:
        for aid in plan.artifact_ids:
            lines.append(f"- {aid}")
    if plan.warnings:
        lines.append("注意: " + "; ".join(plan.warnings))
    return "\n".join(lines)


def _render_approval(plan: ResponsePlan, ctx=None) -> str:
    lines = ["以下操作需要审批:"]
    for appr in plan.pending_approvals:
        if isinstance(appr, dict):
            lines.append(f"- {appr.get('action_id', '')} {appr.get('tool_id', '')} (风险: {appr.get('risk', '')})")
        else:
            lines.append(f"- {appr}")
    lines.append("请确认是否继续执行。")
    return "\n".join(lines)


def _render_blocked(plan: ResponsePlan, ctx=None) -> str:
    lines = [f"任务 {plan.task_id} 已被阻塞"]
    if plan.warnings:
        lines.append("原因: " + "; ".join(plan.warnings))
    return "\n".join(lines)


def _render_failed(plan: ResponsePlan, ctx=None) -> str:
    lines = [f"任务 {plan.task_id} 执行失败"]
    if plan.warnings:
        lines.append("原因: " + "; ".join(plan.warnings))
    return "\n".join(lines)


_RENDERERS = {
    "answer": _render_answer,
    "progress": _render_progress,
    "artifact": _render_artifact,
    "approval": _render_approval,
    "blocked": _render_blocked,
    "failed": _render_failed,
}
