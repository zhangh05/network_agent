# agent/runtime/response/composer.py
"""ResponseComposer — orchestrates policy → plan → render → final_response."""

from __future__ import annotations

from agent.runtime.response.models import FinalResponse
from agent.runtime.response.policy import ResponsePolicy
from agent.runtime.response.renderer import ResponseRenderer


class ResponseComposer:
    """Compose a FinalResponse from runtime state and write to ctx.metadata."""

    def __init__(self):
        self._policy = ResponsePolicy()
        self._renderer = ResponseRenderer()

    def compose(self, ctx) -> FinalResponse:
        plan = self._policy.decide(ctx)
        content = self._renderer.render(plan, ctx)
        resp = FinalResponse(
            content=content,
            response_type=plan.response_type,
            artifact_ids=list(plan.artifact_ids),
            task_id=plan.task_id,
            step_id=plan.step_id,
        )
        ctx.metadata["final_response"] = {
            "content": resp.content,
            "response_type": resp.response_type,
            "artifact_ids": resp.artifact_ids,
            "task_id": resp.task_id,
            "step_id": resp.step_id,
        }
        return resp
