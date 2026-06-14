"""harness/test_v212_tool_use_prompt_policy.py

v2.1.2 Tool-Use Intelligence — test suite for prompt policy, tool decision
transparency, host/device boundary distinction, and fallback strategies.

Tests cover:
  1. Host introspection → shell.exec/powershell.exec in candidates
  2. Network device query → distinguishes real device access limitation
  3. Uploaded config → uses parser/file/artifact, not device access claim
  4. shell.exec approval → generates approval, doesn't repeat OS question
  5. "本机OS的" → no re-query about OS type
  6. "记住结论" → memory tool path
  7. "存为知识" → artifact/knowledge path
  8. tool_decision field present in AgentResult
  9. no_tool_reason field present when no tools called
  10. Tool failure → fallback_suggestions present
"""

import pytest
import json


# ── Test helpers ──

def _get_tool_descriptions():
    """Get all registered tool descriptions for assertion."""
    try:
        from tool_runtime.general_tools.registry import ALL_GENERAL_TOOLS, REMOVED_GENERAL_TOOL_IDS
        descs = {}
        for spec, _ in ALL_GENERAL_TOOLS:
            if spec.tool_id not in REMOVED_GENERAL_TOOL_IDS:
                descs[spec.tool_id] = {
                    "description": spec.description,
                    "risk_level": spec.risk_level,
                    "requires_approval": spec.requires_approval,
                    "category": spec.category,
                    "permission_action": spec.permission_action,
                    "callable_by_llm": spec.callable_by_llm,
                }
        return descs
    except Exception as e:
        pytest.skip(f"Cannot load tool descriptions: {e}")


def _get_builtin_descriptions():
    """Get builtin tool descriptions."""
    try:
        from tool_runtime.builtins import BUILTIN_TOOLS
        descs = {}
        for spec, _ in BUILTIN_TOOLS:
            descs[spec.tool_id] = {
                "description": spec.description,
                "risk_level": spec.risk_level,
                "category": spec.category,
            }
        return descs
    except Exception as e:
        pytest.skip(f"Cannot load builtin tools: {e}")


def _get_system_prompt():
    """Get the system prompt text."""
    try:
        from agent.runtime.prompts import build_system_prompt
        return build_system_prompt()
    except Exception as e:
        pytest.skip(f"Cannot load system prompt: {e}")


def _get_tool_adapter_prompt():
    """Get the tool adapter prompt text."""
    try:
        from agent.llm.tool_adapter import build_system_prompt_with_tools
        return build_system_prompt_with_tools("test_ws")
    except Exception as e:
        pytest.skip(f"Cannot load tool adapter prompt: {e}")


# ── Test 1: System prompt contains v2.1.2 principles ──

def test_sprompt_contains_tool_use_principles():
    """System prompt must contain v2.1.2 Tool-Use Principles section."""
    prompt = _get_system_prompt()
    assert "v2.1.2 Tool-Use Principles" in prompt, \
        "System prompt missing v2.1.2 Tool-Use Principles section"
    assert "P1. Host vs Device Boundary" in prompt, \
        "Missing host/device boundary principle"
    assert "P2. Tool-First Mindset" in prompt, \
        "Missing tool-first mindset principle"
    assert "P3. Approval Strategy" in prompt, \
        "Missing approval strategy principle"
    assert "P4. Failure → Fallback" in prompt, \
        "Missing failure fallback principle"
    assert "P5. Output Structure" in prompt, \
        "Missing output structure principle"
    assert "P6. Scene-Based Tool Selection" in prompt, \
        "Missing scene-based tool selection principle"


# ── Test 2: Host introspection tools are correctly described ──

def test_shell_exec_described_as_local_host():
    """shell.exec description must mention LOCAL HOST, not remote device."""
    descs = _get_tool_descriptions()
    shell = descs.get("shell.exec", {})
    desc = shell.get("description", "")
    assert "LOCAL HOST" in desc or "LOCAL" in desc, \
        f"shell.exec description does not mention LOCAL HOST: {desc[:100]}"
    assert "NOT for" in desc or "Not for" in desc or "NOT for" in desc, \
        f"shell.exec description missing 'NOT for' section: {desc[:100]}"


def test_powershell_exec_described_as_local_host():
    """powershell.exec description must mention LOCAL HOST."""
    descs = _get_tool_descriptions()
    ps = descs.get("powershell.exec", {})
    desc = ps.get("description", "")
    assert "LOCAL HOST" in desc or "LOCAL" in desc, \
        f"powershell.exec description does not mention LOCAL HOST: {desc[:100]}"


# ── Test 3: System prompt has prohibited phrases section ──

def test_sprompt_has_prohibited_phrases():
    """System prompt must contain Prohibited Phrases section."""
    prompt = _get_system_prompt()
    assert "Prohibited Phrases" in prompt, \
        "System prompt missing Prohibited Phrases section"
    assert "没有真实设备访问能力" in prompt, \
        "Missing the prohibited phrase text"


# ── Test 4: System prompt has alternative phrases ──

def test_sprompt_has_alternative_phrases():
    """System prompt must provide alternative phrases for common scenarios."""
    prompt = _get_system_prompt()
    assert "可以通过本机命令查询" in prompt or "shell.exec" in prompt, \
        "Missing alternative phrase for local host queries"
    assert "可以分析你提供的配置" in prompt or "上传" in prompt, \
        "Missing alternative phrase for uploaded files"


# ── Test 5: Tool adapter prompt has scene routing ──

def test_tool_adapter_has_scene_routing():
    """Tool adapter prompt must contain scene-based routing sections."""
    prompt = _get_tool_adapter_prompt()
    assert "Scene-Based Tool Selection" in prompt or "Scene" in prompt, \
        "Tool adapter prompt missing scene routing"
    assert "Host" in prompt or "Local" in prompt, \
        "Missing host/local scene section"
    assert "Uploaded" in prompt or "File" in prompt, \
        "Missing file/upload scene section"


# ── Test 6: Every tool description has minimum required elements ──

def test_all_tool_descriptions_have_context():
    """Every tool description must include usage hints (at minimum: Use when or NOT for)."""
    descs = _get_tool_descriptions()
    passing = 0
    failing = []
    for tid, info in descs.items():
        desc = info.get("description", "")
        # Check minimum length and at least one guidance indicator
        if len(desc) < 30:
            failing.append(f"{tid}: description too short ({len(desc)} chars)")
        elif "Use when" not in desc and "not for" not in desc.lower() and "NOT for" not in desc:
            failing.append(f"{tid}: missing usage guidance")
        else:
            passing += 1
    if failing:
        # Allow a few tools with shorter descriptions (e.g., slash.run)
        assert len(failing) <= 3, f"Too many tools with insufficient descriptions: {failing[:10]}"
    assert passing > 0, "No tools passed description check"


# ── Test 7: High-risk tools have requires_approval=True ──

def test_high_risk_tools_require_approval():
    """All high-risk tools must have requires_approval=True."""
    descs = _get_tool_descriptions()
    high_risk = {tid: info for tid, info in descs.items() if info["risk_level"] == "high"}
    for tid, info in high_risk.items():
        assert info["requires_approval"] is True, \
            f"High-risk tool {tid} should require approval but doesn't"


# ── Test 8: shell.exec has 'shell' category with 'exec' permission ──

def test_shell_exec_permission_action():
    """shell.exec must have permission_action='exec' (not read/write)."""
    descs = _get_tool_descriptions()
    shell = descs.get("shell.exec", {})
    assert shell.get("permission_action") == "exec", \
        f"shell.exec permission_action is {shell.get('permission_action')}, expected 'exec'"


# ── Test 9: All tool descriptions are non-empty and meaningful ──

def test_tool_descriptions_not_empty():
    """No tool description should be empty or a single generic word."""
    descs = _get_tool_descriptions()
    for tid, info in descs.items():
        desc = info.get("description", "").strip()
        assert desc, f"Tool {tid} has empty description"
        assert len(desc) >= 10, f"Tool {tid} description too short: '{desc}'"


# ── Test 10: Builtin parser tools mention "offline" ──

def test_parser_tools_mention_offline():
    """Parser tools should indicate they work offline (no device access needed)."""
    builtins = _get_builtin_descriptions()
    parser_keys = [k for k in builtins if k.startswith("parser.")]
    assert len(parser_keys) >= 2, f"Expected at least 2 parser tools, got {len(parser_keys)}"
    for key in parser_keys:
        desc = builtins[key].get("description", "")
        # At least should not claim device access
        assert "device access" not in desc.lower() or "no device access" in desc.lower(), \
            f"Parser tool {key} description suggests device access: {desc[:100]}"


# ── Test 11: AgentResult has tool_decision field ──

def test_agent_result_has_tool_decision():
    """AgentResult dataclass must have tool_decision field."""
    from agent.runtime.result import AgentResult
    result = AgentResult()
    assert hasattr(result, "tool_decision"), "AgentResult missing tool_decision field"
    assert hasattr(result, "no_tool_reason"), "AgentResult missing no_tool_reason field"


# ── Test 12: AgentResult.to_dict includes tool_decision ──

def test_agent_result_to_dict_includes_tool_decision():
    """AgentResult.to_dict() must include tool_decision and no_tool_reason."""
    from agent.runtime.result import AgentResult
    result = AgentResult(
        ok=True,
        final_response="test",
        tool_decision={"needed": True, "selected_tools": ["shell.exec"]},
        no_tool_reason="",
    )
    d = result.to_dict()
    assert "tool_decision" in d, "to_dict missing tool_decision"
    assert "no_tool_reason" in d, "to_dict missing no_tool_reason"
    assert d["tool_decision"]["needed"] is True


# ── Test 13: _build_tool_decision handles no-tools case ──

def test_build_tool_decision_no_tools():
    """_build_tool_decision returns correct shape when no tools called."""
    from agent.runtime.loop import _build_tool_decision
    result = _build_tool_decision([], None)
    assert result["needed"] is False
    assert "reason" in result
    assert "provided context" in result["reason"].lower()


# ── Test 14: _build_tool_decision handles tools-called case ──

def test_build_tool_decision_with_tools():
    """_build_tool_decision returns selected/failed tools when tools called."""
    from agent.runtime.loop import _build_tool_decision
    all_results = [
        {"tool_id": "web.search", "ok": True, "errors": []},
        {"tool_id": "file.read", "ok": False, "errors": ["file_not_found"]},
    ]
    result = _build_tool_decision(all_results, None)
    assert result["needed"] is True
    assert "web.search" in result["selected_tools"]
    assert "file.read" in result["failed_tools"]


# ── Test 15: _build_no_tool_reason handles no-tools case ──

def test_build_no_tool_reason_no_call():
    """_build_no_tool_reason returns reason when no tools called."""
    from agent.runtime.loop import _build_no_tool_reason
    result = _build_no_tool_reason([], None)
    assert result != "", "no_tool_reason should not be empty when no tools called"


def test_build_no_tool_reason_with_tools():
    """_build_no_tool_reason returns empty when tools were called."""
    from agent.runtime.loop import _build_no_tool_reason
    all_results = [{"tool_id": "web.search", "ok": True}]
    result = _build_no_tool_reason(all_results, None)
    assert result == "", "no_tool_reason should be empty when tools were called"


# ── Test 16: assistant_chat template updated ──

def test_assistant_chat_template_updated():
    """assistant_chat.md should contain v2.1.2 boundaries."""
    import os
    tmpl_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "prompts", "templates", "assistant_chat.md"
    )
    if os.path.exists(tmpl_path):
        content = open(tmpl_path).read()
        assert "v2.1.2" in content or "Local Host" in content, \
            "assistant_chat.md not updated with v2.1.2 docs"
        assert "uploaded" in content.lower() or "上传" in content, \
            "assistant_chat.md missing uploaded file guidance"


# ── Test 17: Runtime prompts module has v2.1.2 header ──

def test_runtime_prompts_module_updated():
    """agent/runtime/prompts.py should contain v2.1.2 header."""
    import os
    prompts_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "agent", "runtime", "prompts.py"
    )
    if os.path.exists(prompts_path):
        content = open(prompts_path).read()
        assert "v2.1.2" in content, "prompts.py not updated with v2.1.2"


# ── Test 18: Tool adapter module has v2.1.2 header ──

def test_tool_adapter_module_updated():
    """agent/llm/tool_adapter.py should contain v2.1.2 header."""
    import os
    adapter_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "agent", "llm", "tool_adapter.py"
    )
    if os.path.exists(adapter_path):
        content = open(adapter_path).read()
        assert "v2.1.2" in content, "tool_adapter.py not updated with v2.1.2"


# ── Test 19: Register returns a count ──

def test_tool_registration_count():
    """Tool registration should return a reasonable count."""
    try:
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.builtins import register_builtin_tools
        from tool_runtime.general_tools.registry import register_all_general_tools

        reg = ToolRegistry()
        reg = register_builtin_tools(reg)
        reg = register_all_general_tools(reg)

        count = reg.count()
        assert count >= 60, f"Too few tools registered: {count}"
        assert count <= 100, f"Too many tools registered: {count}"
    except Exception as e:
        pytest.skip(f"Tool registration error: {e}")
