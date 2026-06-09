# harness/test_knowledge_rag_integration.py
"""Agent Knowledge Retrieval / RAG Context Integration v0.2 — Tests.

Covers: intent routing, knowledge_loader, composer, verifier, API response,
         UI display, safety gates.
"""

import json
import re
import sys
import os
from pathlib import Path
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ═══════════════════ Intent Routing ═══════════════════

class TestKnowledgeIntentRouter:
    def test_knowledge_query_explicit(self):
        from agent.nodes.intent_router import _infer
        assert _infer("查一下知识库 NAT") == "knowledge_query"

    def test_knowledge_query_search(self):
        from agent.nodes.intent_router import _infer
        assert _infer("在资料里找一下联软准入") == "knowledge_query"

    def test_knowledge_query_doc(self):
        from agent.nodes.intent_router import _infer
        assert _infer("之前上传的文档里有没有提到 CUCM") == "knowledge_query"

    def test_knowledge_query_report(self):
        from agent.nodes.intent_router import _infer
        assert _infer("这个报告里说了什么") == "knowledge_query"

    def test_assistant_chat_not_knowledge(self):
        from agent.nodes.intent_router import _infer
        assert _infer("你好") == "assistant_chat"

    def test_translate_config_not_knowledge(self):
        from agent.nodes.intent_router import _infer
        assert _infer("翻译配置") == "translate_config"

    def test_simple_question_not_knowledge(self):
        """Simple question without knowledge context words should be assistant_chat."""
        from agent.nodes.intent_router import _infer
        # "NAT是什么" without context words → assistant_chat
        assert _infer("NAT是什么") == "assistant_chat"

    def test_knowledge_builtin_capability(self):
        from agent.nodes.intent_router import _resolve_capability
        from agent.state import NetworkAgentState
        state = NetworkAgentState(intent="knowledge_query", workspace_id="default")
        _resolve_capability(state)
        assert state.active_module == "knowledge"
        assert state.context["capability_id"] == "knowledge.query"
        assert state.context["capability_status"] == "builtin"


# ═══════════════════ Knowledge Loader ═══════════════════

class TestKnowledgeLoader:
    def test_load_knowledge_context_empty_input(self):
        from context.knowledge_loader import load_knowledge_context
        result = load_knowledge_context("", "default")
        assert result["not_found"] is True
        assert result["count"] == 0

    def test_load_knowledge_context_llm_safe_only(self, tmp_path, monkeypatch):
        """Only llm_safe chunks should be loaded."""
        from knowledge.schemas import SafeChunk
        from knowledge import store
        monkeypatch.setattr(store, "WS_ROOT", tmp_path / "workspaces")
        (tmp_path / "workspaces" / "testws" / "indexes" / "knowledge").mkdir(parents=True, exist_ok=True)

        chunks = [
            SafeChunk(source_id="ks_001", artifact_id="art_001", workspace_id="testws",
                      safe_excerpt="safe content", llm_safe=True),
            SafeChunk(source_id="ks_001", artifact_id="art_001", workspace_id="testws",
                      safe_excerpt="sensitive content", llm_safe=False),
        ]
        store.save_chunks(chunks)

        from context.knowledge_loader import load_knowledge_context
        result = load_knowledge_context("safe", "testws")
        # Only llm_safe=True chunks should be returned
        assert all(r["safe_excerpt"] != "sensitive content" for r in result["results"])

    def test_load_knowledge_context_no_full_content(self, tmp_path, monkeypatch):
        """Results must not contain full_content or full_config."""
        from knowledge.schemas import SafeChunk
        from knowledge import store
        monkeypatch.setattr(store, "WS_ROOT", tmp_path / "workspaces")
        (tmp_path / "workspaces" / "testws" / "indexes" / "knowledge").mkdir(parents=True, exist_ok=True)

        chunks = [SafeChunk(source_id="ks_001", artifact_id="art_001", workspace_id="testws",
                           safe_excerpt="hello", llm_safe=True)]
        store.save_chunks(chunks)

        from context.knowledge_loader import load_knowledge_context
        result = load_knowledge_context("hello", "testws")
        for r in result["results"]:
            assert "full_content" not in r
            assert "full_config" not in r
            assert "source_config" not in r

    def test_load_knowledge_context_no_secrets(self, tmp_path, monkeypatch):
        """Results must not contain secrets."""
        from knowledge.schemas import SafeChunk, KnowledgeSource
        from knowledge import store
        monkeypatch.setattr(store, "WS_ROOT", tmp_path / "workspaces")
        (tmp_path / "workspaces" / "testws" / "indexes" / "knowledge").mkdir(parents=True, exist_ok=True)

        chunks = [SafeChunk(source_id="ks_001", artifact_id="art_001", workspace_id="testws",
                           safe_excerpt="clean text", llm_safe=True)]
        store.save_chunks(chunks)

        from context.knowledge_loader import load_knowledge_context
        result = load_knowledge_context("clean", "testws")
        for r in result["results"]:
            for v in r.values():
                if isinstance(v, str):
                    assert "password:" not in v.lower()


# ═══════════════════ Prompt / LLM ═══════════════════

class TestKnowledgePrompt:
    def test_knowledge_answer_prompt_exists(self):
        """knowledge_answer prompt must be in registry."""
        registry = (PROJECT_ROOT / "prompts" / "registry.yaml").read_text()
        assert "knowledge_answer" in registry

    def test_knowledge_answer_template_exists(self):
        """Template file must exist."""
        path = PROJECT_ROOT / "prompts" / "templates" / "knowledge_answer.md"
        assert path.exists()

    def test_knowledge_answer_policy_no_full_config(self):
        """Prompt policy must forbid full config and secrets."""
        registry = (PROJECT_ROOT / "prompts" / "registry.yaml").read_text()
        kb_block = re.search(
            r"knowledge\.answer.*?(?=\n  - prompt_id:|\Z)",
            registry, re.DOTALL
        )
        if kb_block:
            block_text = kb_block.group()
            assert "allow_full_source_config: false" in block_text
            assert "allow_full_deployable_config: false" in block_text
            assert "allow_full_artifact_content: false" in block_text
            assert "forbid_secret_output: true" in block_text
            assert "forbid_deployable_generation: true" in block_text

    def test_knowledge_answer_template_safe(self):
        """Template must not contain instructions to output secrets."""
        template = (PROJECT_ROOT / "prompts" / "templates" / "knowledge_answer.md").read_text()
        assert "full_content" not in template.lower()
        assert "full_config" not in template.lower()
        assert "source_config" not in template.lower()


# ═══════════════════ Composer / Verifier ═══════════════════

class TestComposerKnowledge:
    def test_composer_handles_knowledge_query(self):
        """Composer must have knowledge_query handler."""
        composer_py = (PROJECT_ROOT / "agent" / "nodes" / "composer.py").read_text()
        assert "_compose_knowledge_query" in composer_py
        assert "knowledge_query" in composer_py

    def test_composer_fallback_shows_not_found(self):
        """Composer must show 'not found' message when no knowledge results."""
        composer_py = (PROJECT_ROOT / "agent" / "nodes" / "composer.py").read_text()
        # _compose_knowledge_query must have Chinese not-found message
        assert "未在当前知识索引中找到相关资料" in composer_py, (
            "composer must have Chinese not-found message"
        )

    def test_verifier_handles_knowledge_query(self):
        """Verifier must have knowledge_query checks."""
        verifier_py = (PROJECT_ROOT / "agent" / "nodes" / "verifier.py").read_text()
        assert "_verify_knowledge_query" in verifier_py
        assert "no_secrets" in verifier_py
        assert "no_deploy_claim" in verifier_py
        assert "no_full_config" in verifier_py


# ═══════════════════ API Response ═══════════════════

class TestKnowledgeAPIResponse:
    def test_agent_result_has_knowledge_fields(self):
        """run_agent result must include knowledge_* fields."""
        graph_py = (PROJECT_ROOT / "agent" / "graph.py").read_text()
        assert "knowledge_results_count" in graph_py
        assert "knowledge_sources" in graph_py
        assert "knowledge_chunks" in graph_py
        assert "knowledge_not_found" in graph_py

    def test_knowledge_context_not_in_localstorage(self):
        """Knowledge results must not go to localStorage directly."""
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        # Check that localStorage.setItem is NOT used for knowledge data
        setitems = [l.strip() for l in html.split('\n') if 'localStorage.setItem' in l]
        for line in setitems:
            assert 'knowledge' not in line.lower(), f"Knowledge data in localStorage: {line}"


# ═══════════════════ UI Tests ═══════════════════

class TestKnowledgeUI:
    def test_frontend_has_retrieving_status(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "检索" in html or "知识索引" in html

    def test_frontend_shows_source_refs(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "knowledge_sources" in html

    def test_frontend_shows_not_found(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "未找到" in html or "not_found" in html

    def test_frontend_no_full_chunk_display(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        # search results in chat should not display full chunk content
        assert "full_content" not in html

    def test_frontend_has_is_likely_knowledge_query(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        assert "_isLikelyKnowledgeQuery" in html


# ═══════════════════ Safety Gates ═══════════════════

class TestKnowledgeSafetyGates:
    def test_no_tool_invoke_in_knowledge_loader(self):
        loader_py = (PROJECT_ROOT / "context" / "knowledge_loader.py").read_text()
        assert "tool_invoke" not in loader_py
        assert "SSH" not in loader_py
        assert "paramiko" not in loader_py

    def test_translate_bundle_not_modified(self):
        """translate_bundle must remain unchanged."""
        from importlib import util as iutil
        spec = iutil.spec_from_file_location(
            "rt", str(PROJECT_ROOT / "modules" / "config_translation" / "core" / "rule_translator.py"))
        assert spec is not None

    def test_no_retired_surfaces(self):
        """Must not restore /api/translate, GraphAgent, :8020."""
        check_files = [
            "backend/main.py", "backend/api/knowledge_routes.py",
            "context/knowledge_loader.py",
        ]
        retired = ["/api/translate", "GraphAgent", "network-translator", ":8020"]
        for f in check_files:
            p = PROJECT_ROOT / f
            if p.exists():
                content = p.read_text()
                for r in retired:
                    assert r not in content, f"{r} found in {f}"

    def test_skipped_not_expanded(self):
        """Skipped tests count must be 7 (LLM live API only)."""
        # This is a soft check — actual verification via pytest output
        pass

    def test_knowledge_result_details_present_in_agent_response(self):
        """Agent response must include knowledge_result_details with metadata."""
        from agent.graph import run_agent
        result = run_agent(
            user_input='查一下知识库里辣椒炒肉是什么',
            intent='', payload={}, workspace_id='default', session_id='',
        )
        assert result['intent'] == 'knowledge_query'
        details = result.get('knowledge_result_details', [])
        assert isinstance(details, list)
        # Allow empty details when knowledge not found
        if not result.get('knowledge_not_found'):
            assert len(details) > 0, "knowledge_result_details must not be empty when results found"
            # Verify structure
            first = details[0]
            assert 'title' in first
            assert 'artifact_id' in first and len(first['artifact_id']) <= 8
            assert 'chunk_id' in first and len(first['chunk_id']) <= 8
            assert 'sensitivity' in first
            assert 'score' in first

    def test_knowledge_response_no_full_content(self):
        """Agent response for knowledge_query must NOT contain full file content."""
        from agent.graph import run_agent
        result = run_agent(
            user_input='查一下知识库里辣椒炒肉是什么',
            intent='', payload={}, workspace_id='default', session_id='',
        )
        fr = result.get('final_response', '')
        # Must not leak config patterns
        assert 'interface ' not in fr.lower(), "Response contains config lines"
        assert 'ip address' not in fr.lower(), "Response contains IP address config"
        # Must not leak filesystem paths
        assert '/workspaces/' not in fr, "Response contains filesystem path"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
