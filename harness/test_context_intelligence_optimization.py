"""Context-intelligence optimizations: explicit files, grounding, tool hints."""

from types import SimpleNamespace


def test_explicit_file_id_is_resolved_as_safe_context(temp_dirs):
    from storage.file_store import write_agent_output
    from agent.runtime.context_file_refs import resolve_explicit_file_refs

    rec = write_agent_output(
        "ctxintel",
        "interface Gi0/1\n ip address 10.0.0.1 255.255.255.0\n",
        "artifact_output",
        title="running-config",
        file_kind="config",
    )

    refs = resolve_explicit_file_refs("ctxintel", f"分析 file_id={rec.file_id}")

    assert refs
    assert refs[0]["file_id"] == rec.file_id
    assert refs[0]["verified"] is True
    assert "ip address" in refs[0]["content"]
    assert refs[0]["truncated"] is False


def test_missing_explicit_file_id_is_marked_unverified(temp_dirs):
    from agent.runtime.context_file_refs import resolve_explicit_file_refs

    refs = resolve_explicit_file_refs("ctxintel_missing", "分析 file_id=file_missing123")

    assert refs
    assert refs[0]["file_id"] == "file_missing123"
    assert refs[0]["verified"] is False
    assert refs[0]["status"] == "unverified"


def test_safe_context_stage_preserves_preparsed_file_refs():
    from agent.runtime.context_pipeline.stages import SafeContextStage

    ctx = SimpleNamespace(
        workspace_id="default",
        session_id="s1",
        model_config={},
        runtime_snapshot={},
        metadata={},
        safe_context={"explicit_file_refs": [{"file_id": "file_1", "verified": True}]},
    )

    result = SafeContextStage().run(
        ctx=ctx,
        evidence_bundle=None,
        services=None,
        tool_scene={},
        rule_tool_scene={},
        selected_visible_tools=[],
        selected_skills=[],
        skill_snapshot={},
        module_snapshot={},
        capability_registry=None,
    )

    assert result.ok is True
    assert ctx.safe_context["explicit_file_refs"][0]["file_id"] == "file_1"


def test_prompt_tool_catalog_marks_required_and_optional_tools():
    from agent.runtime.prompt_architecture.compiler import compile_runtime_prompt

    ctx = SimpleNamespace(
        runtime_snapshot={"status": "ok"},
        safe_context={
            "workspace_id": "default",
            "tool_scene": {
                "tool_planning_decision": {
                    "required_tools": ["workspace.file"],
                    "optional_tools": ["web.manage"],
                }
            },
        },
        metadata={"visible_tools": ["workspace.file", "web.manage"]},
        visible_tool_ids=["workspace.file", "web.manage"],
        workspace_id="default",
        session_id="s1",
        requested_by="turn_runner",
    )

    prompt = compile_runtime_prompt(ctx).final_prompt

    assert "[recommended]" in prompt
    assert "[optional]" in prompt


def test_trust_policy_marks_unverified_file_backed_knowledge(temp_dirs):
    from agent.runtime.cognition.evidence_models import EvidenceBundle, EvidenceItem
    from agent.runtime.cognition.trust_policy import TrustPolicy

    evidence = EvidenceBundle()
    evidence.knowledge_items.append(EvidenceItem(
        evidence_id="k1",
        source_type="knowledge",
        source_id="file_missing123",
        content="stale fact",
    ))

    report = TrustPolicy().apply(evidence, SimpleNamespace(workspace_id="ctxintel_trust"))

    assert report["grounding"]["unverified_count"] == 1
    assert evidence.knowledge_items[0].metadata["grounding_status"] == "unverified"


def test_core_tools_for_context_does_not_inflate_all_tools():
    from agent.runtime.context_pipeline.stages import _core_tools_for_context
    from tool_runtime.tool_namespace import TOOL_NAMESPACE as _ALL_TOOLS

    ctx = SimpleNamespace(user_input="总结一下")
    tools = _core_tools_for_context(ctx, {"categories": ["knowledge"], "groups": {}})

    assert "workspace.file" in tools
    assert "skill.manage" in tools
    assert "git.manage" not in tools
    assert "device.manage" not in tools
    assert len(tools) < len(list(_ALL_TOOLS))


def test_core_tools_for_context_includes_agent_tools_for_subagent_scene():
    from agent.runtime.context_pipeline.stages import _core_tools_for_context

    ctx = SimpleNamespace(user_input="派发子agent，让它搜索一下BGP邻居的建立条件")
    tools = _core_tools_for_context(ctx, {
        "categories": ["agent", "web"],
        "groups": {"agent": ["subagent"], "web": ["search"]},
    })

    assert "agent.manage" in tools
    assert "agent.manage" in tools
    assert "agent.manage" in tools
    assert "web.manage" in tools


def test_context_pipeline_simple_chat_exposes_no_tools():
    from agent.core.session import AgentSession
    from agent.core.turn import AgentTurn
    from agent.protocol.op import AgentOp
    from agent.runtime.context_pipeline.pipeline import ContextPipeline
    from agent.runtime.services import default_runtime_services

    session = AgentSession(session_id="ctx_simple_no_tools", workspace_id="default")
    turn = AgentTurn.from_op(AgentOp.user_message("你好", session_id=session.session_id, workspace_id="default"))
    ctx = ContextPipeline().run(session, turn, default_runtime_services())

    assert ctx.metadata["context_status"] == "ok"
    assert ctx.visible_tool_ids == []
    assert ctx.tool_router.model_visible_tools() == []


def test_llm_summary_compaction_creates_progress_summary():
    from agent.runtime.context_compactor import CompactionStrategy, compact_messages

    messages = [
        {"role": "user", "content": f"step {i}: checked config and found issue {i}", "message_id": f"u{i}"}
        for i in range(10)
    ] + [
        {"role": "assistant", "content": "recent answer", "message_id": "a_recent"},
        {"role": "user", "content": "continue", "message_id": "u_recent"},
    ]

    compacted, meta = compact_messages(
        messages,
        keep_recent=2,
        strategy=CompactionStrategy.LLM_SUMMARY,
        trigger="test",
    )

    assert meta["strategy"] == "llm_summary"
    assert meta["summary_message_created"] is True
    assert compacted[0]["role"] == "assistant"
    assert "State of progress" in compacted[0]["content"]
    assert compacted[-1]["content"] == "continue"
