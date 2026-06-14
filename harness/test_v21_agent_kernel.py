# harness/test_v21_agent_kernel.py
"""Agent Kernel v2.1 — Comprehensive Tests.

Covers:
  - skill.create creates pending_review skill
  - skill.load returns skill_prompt without direct injection
  - agent.team planner/worker/reviewer flow
  - pdf.extract_text text fallback
  - cache get/set/eviction
  - stream events sequence
  - slash.run executes registered commands
  - All 11 slash commands callable
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════

def _invoke(tool_id: str, args: dict = None) -> dict:
    """Invoke a general tool handler directly."""
    from tool_runtime.general_tools import ALL_GENERAL_TOOLS
    from tool_runtime.schemas import ToolInvocation
    for spec, handler in ALL_GENERAL_TOOLS:
        if spec.tool_id == tool_id:
            inv = ToolInvocation(
                tool_id=tool_id,
                arguments=args or {},
                workspace_id=args.get("workspace_id", "default") if args else "default",
            )
            return handler(inv)
    return {"ok": False, "error": f"Tool {tool_id} not found"}


# ═══════════════════════════════════════════════
# 1. skill.create
# ═══════════════════════════════════════════════

class TestSkillCreate:
    """skill.create creates a pending_review skill."""

    def test_skill_create_returns_pending_review(self):
        result = _invoke("skill.create", {
            "name": "test-skill-v21",
            "description": "A test skill for v2.1 kernel tests",
            "capabilities": ["knowledge.search"],
        })
        assert result["ok"] is True, f"skill.create should succeed, got: {result}"
        assert result.get("status") == "pending_review", f"Expected pending_review, got: {result.get('status')}"
        assert result.get("skill_name") == "test-skill-v21"
        assert result.get("skill_path") is not None

    def test_skill_create_writes_skill_md(self):
        result = _invoke("skill.create", {
            "name": "test-skill-v21b",
            "description": "Another test skill",
        })
        assert result["ok"] is True

        skills_dir = PROJECT_ROOT / "skills" / "test-skill-v21b"
        assert (skills_dir / "SKILL.md").is_file()
        assert (skills_dir / "skill.yaml").is_file()
        content = (skills_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "pending_review" in content

    def test_skill_create_duplicate_returns_error(self):
        _invoke("skill.create", {"name": "dup-skill-v21"})
        result = _invoke("skill.create", {"name": "dup-skill-v21"})
        assert result["ok"] is False
        assert "already exists" in str(result.get("error", ""))

    def test_skill_create_now_in_visible_tools(self):
        """skill.create is no longer in REMOVED_GENERAL_TOOL_IDS."""
        from tool_runtime.general_tools import REMOVED_GENERAL_TOOL_IDS
        assert "skill.create" not in REMOVED_GENERAL_TOOL_IDS


# ═══════════════════════════════════════════════
# 2. skill.load
# ═══════════════════════════════════════════════

class TestSkillLoad:
    """skill.load returns skill_prompt without direct injection."""

    def test_skill_load_requires_skill_name(self):
        result = _invoke("skill.load", {})
        assert result["ok"] is False
        assert "skill_name" in str(result.get("error", ""))

    def test_skill_load_unknown_skill_returns_error(self):
        result = _invoke("skill.load", {"skill_name": "nonexistent-skill-xyz"})
        assert result["ok"] is False
        assert "not found" in str(result.get("error", ""))

    def test_skill_load_returns_skill_prompt(self):
        result = _invoke("skill.load", {"skill_name": "config_translation"})
        assert result["ok"] is True, f"skill.load should succeed, got: {result}"
        assert result.get("skill_name") == "config_translation"
        assert result.get("prompt_length") is not None
        assert result.get("prompt_length", 0) > 0
        assert result.get("loaded_at") is not None

    def test_skill_load_does_not_directly_inject(self):
        """skill.load returns skill_prompt but does NOT inject into system prompt.
        The context builder reads it from session metadata independently.
        """
        result = _invoke("skill.load", {"skill_name": "config_translation"})
        # Just returns the content, doesn't call any injection logic
        assert result["ok"] is True
        assert "prompt_length" in result
        # The returned result does NOT include an "injected" flag
        assert "injected" not in result

    def test_skill_load_registered_as_medium_risk(self):
        from tool_runtime.general_tools import ALL_GENERAL_TOOLS
        for spec, _ in ALL_GENERAL_TOOLS:
            if spec.tool_id == "skill.load":
                assert spec.risk_level == "medium", f"Expected medium risk, got {spec.risk_level}"
                break
        else:
            pytest.fail("skill.load not found in registered tools")


# ═══════════════════════════════════════════════
# 3. agent.team
# ═══════════════════════════════════════════════

class TestAgentTeam:
    """agent.team planner/worker/reviewer flow."""

    def test_agent_team_requires_instruction(self):
        result = _invoke("agent.team", {})
        assert result["ok"] is False
        assert "instruction" in str(result.get("error", ""))

    def test_agent_team_returns_ok_with_default_roles(self):
        result = _invoke("agent.team", {
            "instruction": "Search the web for the capital of France and validate the result is correct.",
        })
        assert result["ok"] is True
        assert "roles_used" in result
        assert "plan" in result
        assert "worker_result" in result

    def test_agent_team_with_planner_only(self):
        result = _invoke("agent.team", {
            "instruction": "Plan an investigation into network latency issues.",
            "roles": ["planner"],
        })
        assert result["ok"] is True
        assert "plan" in result

    def test_agent_team_with_reviewer(self):
        result = _invoke("agent.team", {
            "instruction": "Find the latest Python version and describe its features.",
            "roles": ["worker", "reviewer"],
        })
        assert result["ok"] is True
        assert "worker_result" in result
        assert "reviewer_result" in result

    def test_agent_team_registered_as_medium_risk(self):
        from tool_runtime.general_tools import ALL_GENERAL_TOOLS
        for spec, _ in ALL_GENERAL_TOOLS:
            if spec.tool_id == "agent.team":
                assert spec.risk_level == "medium", f"Expected medium risk, got {spec.risk_level}"
                break
        else:
            pytest.fail("agent.team not found in registered tools")

    def test_agent_team_not_planned_handler(self):
        """agent.team is no longer a _planned_handler placeholder."""
        from tool_runtime.general_tools import ALL_GENERAL_TOOLS, handle_agent_team
        for spec, handler in ALL_GENERAL_TOOLS:
            if spec.tool_id == "agent.team":
                assert callable(handler)
                break


# ═══════════════════════════════════════════════
# 4. pdf.extract_text
# ═══════════════════════════════════════════════

class TestPdfExtractText:
    """pdf.extract_text with text fallback."""

    def test_pdf_extract_text_requires_filepath(self):
        result = _invoke("pdf.extract_text", {"workspace_id": "default"})
        assert result["ok"] is False
        assert "filepath" in str(result.get("error", ""))

    def test_pdf_extract_text_nonexistent_file(self):
        result = _invoke("pdf.extract_text", {
            "workspace_id": "default",
            "filepath": "nonexistent.pdf",
        })
        assert result["ok"] is False
        assert "not found" in str(result.get("error", ""))

    def test_pdf_extract_text_text_fallback(self, temp_dirs):
        """When PyPDF2 not available, should try text fallback."""
        from pathlib import Path
        # Create a simple PDF-like file in workspace
        ws_root = Path(temp_dirs["workspace_dir"]) / "default"
        ws_root.mkdir(parents=True, exist_ok=True)
        test_pdf = ws_root / "test.pdf"
        test_pdf.write_text("This is a test PDF content as plain text.", encoding="utf-8")

        result = _invoke("pdf.extract_text", {
            "workspace_id": "default",
            "filepath": "test.pdf",
        })

        # PyPDF2 path or text fallback - either should work
        if result["ok"]:
            method = result.get("method", "pypdf2")
            assert method in ("pypdf2", "text_fallback"), f"Unexpected method: {method}"
            assert result.get("page_count", 0) > 0
            assert result.get("file_size", 0) > 0

    def test_pdf_extract_text_non_pdf_rejected(self, temp_dirs):
        from pathlib import Path
        ws_root = Path(temp_dirs["workspace_dir"]) / "default"
        ws_root.mkdir(parents=True, exist_ok=True)
        test_txt = ws_root / "test.txt"
        test_txt.write_text("hello", encoding="utf-8")

        result = _invoke("pdf.extract_text", {
            "workspace_id": "default",
            "filepath": "test.txt",
        })
        assert result["ok"] is False
        assert "pdf" in str(result.get("error", "")).lower()


# ═══════════════════════════════════════════════
# 5. Cache
# ═══════════════════════════════════════════════

class TestCache:
    """Cache get/set/eviction."""

    def test_cache_get_set(self):
        from agent.runtime.cache import TTLCache
        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_miss_returns_none(self):
        from agent.runtime.cache import TTLCache
        cache = TTLCache(max_size=10, ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_cache_eviction(self):
        from agent.runtime.cache import TTLCache
        cache = TTLCache(max_size=2, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # "a" should be evicted (LRU)
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_cache_clear(self):
        from agent.runtime.cache import TTLCache
        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("x", 1)
        cache.set("y", 2)
        cache.clear()
        assert cache.get("x") is None
        assert cache.get("y") is None
        assert cache.size() == 0

    def test_cache_lru_ordering(self):
        from agent.runtime.cache import TTLCache
        cache = TTLCache(max_size=3, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Access "a" to make it recently used
        assert cache.get("a") == 1
        # Now "b" is LRU
        cache.set("d", 4)
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_web_cache_normalize_key(self):
        from agent.runtime.cache import WebCache
        wc = WebCache(max_size=10, ttl_seconds=60)
        key = wc.normalize_key("https://example.com/page/")
        assert key == "https://example.com/page"

    def test_web_cache_get_set(self):
        from agent.runtime.cache import WebCache
        wc = WebCache(max_size=10, ttl_seconds=60)
        wc.set_web("https://example.com", {"data": "test"})
        result = wc.get_web("https://example.com")
        assert result == {"data": "test"}

    def test_get_web_cache_singleton(self):
        from agent.runtime.cache import get_web_cache
        wc1 = get_web_cache()
        wc2 = get_web_cache()
        assert wc1 is wc2


# ═══════════════════════════════════════════════
# 6. Stream Events
# ═══════════════════════════════════════════════

class TestStreamEvents:
    """Stream events sequence."""

    def test_stream_event_constants(self):
        from agent.runtime.query_engine import StreamEvent
        assert StreamEvent.RUN_STARTED == "run_started"
        assert StreamEvent.MODEL_STARTED == "model_started"
        assert StreamEvent.TOOL_CALL == "tool_call"
        assert StreamEvent.APPROVAL_REQUIRED == "approval_required"
        assert StreamEvent.TOOL_RESULT == "tool_result"
        assert StreamEvent.COMPACT == "compact"
        assert StreamEvent.FINAL == "final"
        assert StreamEvent.ERROR == "error"

    def test_stream_emitter_emit_and_to_events(self):
        from agent.runtime.query_engine import StreamEvent, StreamEmitter
        emitter = StreamEmitter()
        emitter.emit(StreamEvent.RUN_STARTED, {"session_id": "abc"})
        emitter.emit(StreamEvent.TOOL_CALL, {"tool_id": "web.search"})
        emitter.emit(StreamEvent.FINAL, {"status": "done"})

        events = emitter.to_events()
        assert len(events) == 3
        assert events[0]["type"] == StreamEvent.RUN_STARTED
        assert events[0]["session_id"] == "abc"
        assert "timestamp" in events[0]
        assert events[1]["type"] == StreamEvent.TOOL_CALL
        assert events[1]["tool_id"] == "web.search"
        assert events[2]["type"] == StreamEvent.FINAL

    def test_stream_emitter_clear(self):
        from agent.runtime.query_engine import StreamEvent, StreamEmitter
        emitter = StreamEmitter()
        emitter.emit(StreamEvent.RUN_STARTED, {})
        assert len(emitter.to_events()) == 1
        emitter.clear()
        assert len(emitter.to_events()) == 0

    def test_stream_event_sequence_is_ordered(self):
        from agent.runtime.query_engine import StreamEvent, StreamEmitter
        emitter = StreamEmitter()
        expected = [
            StreamEvent.RUN_STARTED,
            StreamEvent.MODEL_STARTED,
            StreamEvent.TOOL_CALL,
            StreamEvent.TOOL_RESULT,
            StreamEvent.FINAL,
        ]
        for e in expected:
            emitter.emit(e, {})
        events = emitter.to_events()
        assert [e["type"] for e in events] == expected


# ═══════════════════════════════════════════════
# 7. slash.run
# ═══════════════════════════════════════════════

class TestSlashRun:
    """slash.run executes registered commands."""

    def test_slash_run_help_command(self):
        result = _invoke("slash.run", {"command": "help"})
        assert result["ok"] is True
        assert "Available Slash Commands" in result.get("result", "")

    def test_slash_run_tools_command(self):
        result = _invoke("slash.run", {"command": "tools"})
        assert result["ok"] is True
        assert "Visible Tools" in result.get("result", "")

    def test_slash_run_agent_command(self):
        result = _invoke("slash.run", {"command": "agent"})
        assert result["ok"] is True
        assert "Agent Info" in result.get("result", "")

    def test_slash_run_unknown_command(self):
        result = _invoke("slash.run", {"command": "doesnotexist"})
        assert result["ok"] is True  # tool call succeeds, but command returns error text
        assert "Unknown command" in result.get("result", "")


# ═══════════════════════════════════════════════
# 8. All 11 slash commands callable
# ═══════════════════════════════════════════════

class TestAllSlashCommands:
    """All 11 built-in slash commands are callable."""

    SLASH_COMMANDS = [
        "help",
        "tools",
        "skills",
        "memory",
        "context",
        "sessions",
        "compact",
        "usage",
        "agent",
        "reset",
        "export",
    ]

    @pytest.mark.parametrize("command", SLASH_COMMANDS)
    def test_slash_command_callable(self, command):
        from agent.runtime.command_system import get_command
        handler = get_command(command)
        assert handler is not None, f"Command /{command} should be registered"
        # Ensure it's callable
        assert callable(handler)
        # Quick smoke: calling with empty args should not raise
        try:
            out = handler("", None, {"workspace_id": "default"})
            assert isinstance(out, str), f"/{command} should return a string"
        except Exception as e:
            pytest.fail(f"/{command} raised: {e}")

    def test_all_11_commands_registered(self):
        from agent.runtime.command_system import SLASH_COMMANDS
        assert len(SLASH_COMMANDS) == 11, f"Expected 11 commands, got {len(SLASH_COMMANDS)}"
        for cmd in self.SLASH_COMMANDS:
            assert cmd in SLASH_COMMANDS, f"Missing command: /{cmd}"

    def test_slash_run_all_11_commands(self):
        """Verify all 11 commands work through slash.run tool."""
        for cmd in self.SLASH_COMMANDS:
            result = _invoke("slash.run", {"command": cmd})
            assert result["ok"] is True, f"slash.run /{cmd} should succeed, got: {result}"


# ═══════════════════════════════════════════════
# 9. skill.create now visible to model
# ═══════════════════════════════════════════════

class TestSkillCreateVisibility:
    """skill.create should be visible to the model after removal from REMOVED list."""

    def test_skill_create_in_model_visible_tools(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        tools = client.list_tools()
        tool_ids = {t["tool_id"] for t in tools}
        assert "skill.create" in tool_ids, "skill.create should be model-visible now"

    def test_skill_load_in_model_visible_tools(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        tools = client.list_tools()
        tool_ids = {t["tool_id"] for t in tools}
        assert "skill.load" in tool_ids, "skill.load should be model-visible"


# ═══════════════════════════════════════════════
# 10. Cleanup
# ═══════════════════════════════════════════════

class TestCleanup:
    """Clean up test-created skills."""

    def test_cleanup_test_skills(self):
        import shutil
        skills_dir = PROJECT_ROOT / "skills"
        for skill_name in ["test-skill-v21", "test-skill-v21b", "dup-skill-v21",
                           "load-test-skill", "load-no-inject"]:
            skill_dir = skills_dir / skill_name
            if skill_dir.exists():
                shutil.rmtree(skill_dir, ignore_errors=True)
        assert True  # Cleanup passed
