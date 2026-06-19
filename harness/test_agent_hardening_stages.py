"""Regression checks for agent hardening stages.

These tests intentionally avoid real LLM calls. They validate routing,
planner visibility, local-ops exposure rules, and same-session turn
serialization without invoking a real model provider.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from agent.runtime.tool_category_router import route_tool_scene
from agent.runtime.tool_planner import plan_tools
from tool_runtime.tool_namespace import TOOL_NAMESPACE


LOCAL_EXEC_TOOLS = {
    "host.shell.exec",
    "host.powershell.exec",
    "host.python.exec",
}
SUB_AGENT_TOOLS = {
    "agent.spawn",
    "agent.role.list",
    "agent.result.get",
}


def _plan(text: str) -> dict:
    rule_scene = route_tool_scene(text)
    return plan_tools(
        user_input=text,
        safe_context={},
        rule_scene=rule_scene,
        available_catalog={"tools": list(TOOL_NAMESPACE)},
        model_config={"enabled": False},
    )


def _candidates(text: str) -> set[str]:
    return set(_plan(text).get("candidate_tools") or [])


def test_simple_chat_does_not_expose_local_ops_or_sub_agents():
    candidates = _candidates("你好")
    assert not (LOCAL_EXEC_TOOLS & candidates)
    assert not (SUB_AGENT_TOOLS & candidates)


def test_knowledge_qa_does_not_expose_local_ops():
    candidates = _candidates("知识库里有没有 OSPF 相关资料")
    assert "knowledge.search" in candidates
    assert not (LOCAL_EXEC_TOOLS & candidates)


def test_config_translate_does_not_fallback_to_local_shell():
    candidates = _candidates("把这个华三配置翻译成思科配置")
    assert "network.config.translate" in candidates
    assert {"workspace.file.read", "workspace.file.list"} & candidates
    assert not ({"host.shell.exec", "host.powershell.exec"} & candidates)


def test_explicit_local_ops_exposes_execution_tools():
    plan = _plan("查看本机端口和进程")
    candidates = set(plan.get("candidate_tools") or [])
    assert LOCAL_EXEC_TOOLS & candidates
    assert plan.get("visibility", {}).get("local_ops_enabled") is True


def test_parallel_complex_task_exposes_sub_agent_but_not_local_shell():
    candidates = _candidates("请分别检查所有文件，并行整理结果")
    assert SUB_AGENT_TOOLS & candidates
    assert not ({"host.shell.exec", "host.powershell.exec"} & candidates)


def test_unknown_tools_fail_closed_in_planner():
    rule_scene = {
        "primary_category": "web",
        "category": "web",
        "groups": {},
        "candidate_tools": ["host.shell.exec", "unknown.tool.exec"],
        "signals": {},
    }
    plan = plan_tools(
        user_input="普通问题",
        safe_context={},
        rule_scene=rule_scene,
        available_catalog={"tools": ["host.shell.exec", "unknown.tool.exec"]},
        model_config={"enabled": False},
    )
    candidates = set(plan.get("candidate_tools") or [])
    assert "unknown.tool.exec" not in candidates
    assert "host.shell.exec" not in candidates
    assert "unknown.tool.exec" in plan.get("governance", {}).get("unknown_tools_filtered", [])


def test_same_session_turns_are_serialized(monkeypatch):
    from agent.app.facade import AgentApp
    from agent.core.session import AgentSession

    active = 0
    max_active = 0
    lock = threading.Lock()
    calls = []

    def fake_submit(self, op):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            calls.append(op.user_input)
        time.sleep(0.05)
        with lock:
            active -= 1
        return SimpleNamespace(
            to_dict=lambda: {
                "ok": True,
                "session_id": op.session_id,
                "turn_id": op.session_id + "_turn",
                "final_response": "ok",
                "metadata": {},
            }
        )

    monkeypatch.setattr(AgentSession, "submit", fake_submit)
    app = AgentApp(services=SimpleNamespace())
    results = []
    errors = []

    def worker(i):
        try:
            results.append(app.submit_user_message(
                user_input=f"msg-{i}",
                session_id="hardening_test_session",
                workspace_id="default",
                metadata={},
            ))
        except Exception as exc:  # pragma: no cover - failure path asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 2
    assert sorted(calls) == ["msg-0", "msg-1"]
    assert max_active == 1
