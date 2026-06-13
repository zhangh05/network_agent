"""Regression tests for tool/skill/module wiring.

These cover integration failures that are easy to miss when each registry is
tested in isolation.
"""

import pytest

from agent.core.session import AgentSession
from agent.core.turn import AgentTurn
from agent.protocol.op import AgentOp
from agent.protocol.tool_call import ToolCall
from agent.runtime.context_builder import build_turn_context
from agent.runtime.services import default_runtime_services


def _ctx_for(message: str):
    services = default_runtime_services()
    session = AgentSession(session_id="tool_design_regression", workspace_id="default")
    turn = AgentTurn(turn_id="tool_design_turn", op=AgentOp(user_input=message))
    return build_turn_context(session, turn, services)


def _tool_names(ctx):
    return {t["function"]["name"] for t in ctx.tool_router.model_visible_tools()}


def test_assistant_chat_turn_exposes_no_business_tools():
    ctx = _ctx_for("今天天气如何？")

    assert ctx.metadata["selected_skills"] == ["assistant_chat"]
    assert ctx.metadata["visible_tools"] == []
    assert _tool_names(ctx) == set()


def test_capability_discovery_turn_exposes_no_business_tools():
    ctx = _ctx_for("你能做什么？")

    assert ctx.metadata["selected_skills"] == ["assistant_chat", "capability_discovery"]
    assert ctx.metadata["visible_tools"] == []
    assert _tool_names(ctx) == set()


def test_artifact_list_uses_capability_handler_in_default_runtime():
    ctx = _ctx_for("列出产物")

    assert "artifact__list" in _tool_names(ctx)
    call = ToolCall(
        call_id="artifact-list-regression",
        llm_tool_name="artifact__list",
        real_tool_id="artifact.list",
        arguments={"workspace_id": "default"},
    )
    result = ctx.tool_router.dispatch(call, ctx)

    assert result.ok is True
    assert result.raw.get("tool_id") == "artifact.list"
    assert "content" in result.raw
    assert "data" in result.raw
    assert result.raw.get("authoritative") is False
    assert result.raw.get("deployable_config") is False


def test_capability_handler_resolution_fail_fast():
    from agent.capabilities.registry import CapabilityRegistry
    from agent.capabilities.schemas import (
        CapabilityManifest,
        CapabilityModuleSpec,
        CapabilitySafetySpec,
        CapabilitySkillSpec,
        CapabilityToolRef,
    )
    from agent.tools.registry import ToolRegistry

    cap = CapabilityManifest(
        capability_id="broken",
        name="Broken",
        status="enabled",
        module=CapabilityModuleSpec(module_id="broken", status="enabled"),
        skills=[
            CapabilitySkillSpec(
                skill_id="broken_skill",
                status="enabled",
                related_tools=["broken.tool"],
            )
        ],
        tools=[
            CapabilityToolRef(
                tool_id="broken.tool",
                status="enabled",
                callable_by_llm=True,
                handler_ref="agent.modules.no_such_module:nope",
                input_schema={"type": "object", "properties": {}},
            )
        ],
        safety=CapabilitySafetySpec(),
    )

    with pytest.raises(RuntimeError, match="Failed to resolve handler"):
        ToolRegistry().register_capability_tools(CapabilityRegistry([cap]))


def test_public_registry_uses_runtime_capability_ids():
    from agent.capabilities import get_default_capability_registry
    from registry.loader import load_capabilities

    runtime_ids = {c.capability_id for c in get_default_capability_registry().list_all()}
    public_ids = {c.capability_id for c in load_capabilities(reload=True)}

    assert public_ids == runtime_ids
