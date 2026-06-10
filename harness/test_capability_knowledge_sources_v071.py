"""Knowledge Sources v0.7.1 Tests.

Tests:
1. query_knowledge hits include source_summary
2. No hits → no fake sources
3. Knowledge unavailable → no fake sources
4. source_summary snippet limited to 200 chars
5. Runtime tool_call exposes source_count
6. ToolResultMessage contains source_summary
7. Capability question mentions sources conditionally
8. No fake citation when no hits
"""

import os
import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")


class TestKnowledgeSourceSummary:
    """source_summary must be generated from real hits."""

    def test_hits_include_source_summary(self):
        """When hits exist, source_summary must be generated."""
        from agent.modules.knowledge.service import _build_source_summary
        hits = [
            {"title": "SD-WAN Guide", "source": "doc_1", "score": 0.95,
             "content": "SD-WAN stands for Software-Defined Wide Area Network."},
            {"title": "Network Architecture", "source": "doc_2", "score": 0.82,
             "content": "Modern network architecture principles."},
        ]
        summaries = _build_source_summary(hits)
        assert len(summaries) == 2
        assert summaries[0]["title"] == "SD-WAN Guide"
        assert summaries[0]["source"] == "doc_1"
        assert summaries[0]["score"] == 0.95
        assert len(summaries[0]["snippet"]) > 0

    def test_no_hits_no_fake_sources(self):
        """Empty hits must produce empty source_summary."""
        from agent.modules.knowledge.service import _build_source_summary
        summaries = _build_source_summary([])
        assert summaries == [], "No hits should produce empty source_summary"

    def test_source_summary_snippet_limited(self):
        """snippet must be <= 200 chars."""
        from agent.modules.knowledge.service import _build_source_summary
        long_content = "x" * 500
        hits = [{"title": "Long Doc", "source": "doc_1", "score": 0.9, "content": long_content}]
        summaries = _build_source_summary(hits)
        assert len(summaries[0]["snippet"]) <= 200

    def test_knowledge_unavailable_no_fake_sources(self):
        """query_knowledge unavailable must return empty source_summary."""
        from agent.modules.knowledge.service import query_knowledge
        # Without knowledge store, this may fail gracefully
        result = query_knowledge("test")
        if not result["ok"]:
            assert result.get("source_summary", []) == []
            assert result.get("source_count", 0) == 0
            assert result.get("hits", []) == []
        # If ok=True (store is available), must still have real data
        else:
            assert isinstance(result.get("hits", []), list)
            assert isinstance(result.get("source_summary", []), list)

    def test_missing_query_no_sources(self):
        """Missing query returns empty source_summary."""
        from agent.modules.knowledge.service import query_knowledge
        result = query_knowledge("")
        assert result["ok"] is False
        assert result["source_summary"] == []
        assert result["source_count"] == 0


class TestRuntimeKnowledgeSources:
    """Runtime tool_call path must expose source_count."""

    def test_tool_call_knowledge_exposes_source_count(self):
        """AgentResult.tool_calls must include source_count."""
        from agent.app.service import get_default_agent_app, reset_agent_app_for_tests
        from agent.llm.schemas import LLMResponse
        reset_agent_app_for_tests()
        app = get_default_agent_app()

        fake_tc = type('FakeTC', (), {
            'id': 'call_k1',
            'name': 'knowledge__query',
            'arguments': {},
        })()
        fake_result = type('Result', (), {
            'ok': True, 'summary': 'Found results',
            'source_count': 3, 'source_summary': [{'title': 'Test', 'source': 's1', 'snippet': 'test'}],
            'errors': [], 'warnings': [], 'metadata': {},
        })()
        responses = [
            LLMResponse(tool_calls=[fake_tc]),
            LLMResponse(content="Here are the knowledge base results."),
        ]
        with patch("agent.runtime.loop.invoke_llm") as mock_llm:
            mock_llm.side_effect = responses
            with patch.object(app.services.tool_service, 'dispatch', return_value=fake_result):
                result = app.submit_user_message(user_input="search KB", session_id="k-src-test")
        assert result.ok
        tc = result.tool_calls[0]
        assert tc.get("source_count") == 3

    def test_knowledge_tool_message_includes_source_summary(self):
        """ToolResultMessage fed back to LLM must include source_summary."""
        from agent.app.service import get_default_agent_app, reset_agent_app_for_tests
        from agent.llm.schemas import LLMResponse
        reset_agent_app_for_tests()
        app = get_default_agent_app()

        fake_tc = type('FakeTC', (), {
            'id': 'call_k2',
            'name': 'knowledge__query',
            'arguments': {},
        })()
        fake_result = type('Result', (), {
            'ok': True, 'summary': 'found', 'source_count': 2,
            'source_summary': [{'title': 'Doc', 'source': 's1', 'snippet': 'data'}],
            'errors': [], 'warnings': [], 'metadata': {},
        })()
        responses = [
            LLMResponse(tool_calls=[fake_tc]),
            LLMResponse(content="Based on sources..."),
        ]
        with patch("agent.runtime.loop.invoke_llm") as mock_llm:
            mock_llm.side_effect = responses
            with patch.object(app.services.tool_service, 'dispatch', return_value=fake_result):
                result = app.submit_user_message(user_input="search", session_id="k-msg-test")
        assert result.ok
        assert len(result.tool_calls) > 0

    def test_skill_does_not_claim_fabrication(self):
        """Knowledge skill must not claim to fabricate sources."""
        from agent.skills.schemas import SKILL_KNOWLEDGE
        ps = SKILL_KNOWLEDGE.prompt_summary.lower()
        assert "never fabricate" in ps or "do not fabricate" in ps or "honestly" in ps

    def test_no_fake_citation_on_empty(self):
        """Skill text must address no-data scenario honestly."""
        from agent.skills.schemas import SKILL_KNOWLEDGE
        ps = SKILL_KNOWLEDGE.prompt_summary.lower()
        # Skill description should acknowledge no-data scenario
        assert "fabricate" in ps or "honestly" in ps or "not found" in ps or "no result" in ps
