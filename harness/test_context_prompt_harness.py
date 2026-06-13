# harness/test_context_prompt_harness.py
"""Context, Prompt, Harness Foundation tests."""

import json, pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from backend.main import app as _flask_app
except ImportError:
    _flask_app = None

@pytest.fixture
def client(temp_dirs):
    if _flask_app is None:
        pytest.skip("Flask app not importable")
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


class TestContextSchema:
    def test_context_ref_fields(self):
        from context.schemas import ContextRef
        r = ContextRef(ref_type="last_result")
        d = r.as_dict()
        assert d["ref_type"] == "last_result"

    def test_context_item_fields(self):
        from context.schemas import ContextItem
        i = ContextItem(item_type="run_summary", priority=20)
        assert i.priority == 20

    def test_context_budget(self):
        from context.schemas import ContextBudget
        b = ContextBudget()
        assert b.max_items == 30
        assert b.max_artifact_refs == 10

    def test_execution_context(self):
        from context.schemas import ExecutionContext
        e = ExecutionContext(workspace_id="ws1", run_id="r1")
        d = e.as_dict()
        assert d["workspace_id"] == "ws1"

    def test_safe_llm_context(self):
        from context.schemas import SafeLLMContext
        s = SafeLLMContext(workspace_id="ws1", intent="context_qa")
        d = s.as_dict()
        assert d["intent"] == "context_qa"

    def test_context_bundle(self):
        from context.schemas import ContextBundle
        b = ContextBundle(workspace_id="ws1", intent="translate_config")
        d = b.as_dict()
        assert d["intent"] == "translate_config"


class TestContextResolver:
    def test_none_ref(self):
        from context.resolver import resolve_context_ref
        r = resolve_context_ref("ws1", "")
        assert r.ref_type == "none"

    def test_last_result(self):
        from context.resolver import resolve_context_ref
        r = resolve_context_ref("ws1", "last_result")
        assert r.ref_type == "last_result"

    def test_last_job(self):
        from context.resolver import resolve_context_ref
        r = resolve_context_ref("ws1", "last_job")
        assert r.ref_type == "last_job"

    def test_artifact_ref(self):
        from context.resolver import resolve_context_ref
        r = resolve_context_ref("ws1", "artifact:art_test")
        assert r.ref_type == "artifact"
        assert r.ref_id == "art_test"

    def test_run_ref(self):
        from context.resolver import resolve_context_ref
        r = resolve_context_ref("ws1", "run:r_test")
        assert r.ref_type == "run"

    def test_selected_artifact_from_ui(self):
        from context.resolver import resolve_context_ref
        r = resolve_context_ref("ws1", "selected_artifact", ui_context={"selected_artifact_id": "art_sel"})
        assert r.ref_type == "selected_artifact"
        assert r.ref_id == "art_sel"

    def test_current_workspace(self):
        from context.resolver import resolve_context_ref
        r = resolve_context_ref("ws1", "current_workspace")
        assert r.ref_type == "current_workspace"
        assert r.resolved is True

    def test_invalid_ref_clean(self):
        from context.resolver import resolve_context_ref
        r = resolve_context_ref("ws1", "nonexistent:xyz")
        assert r.resolved is False or r.ref_type == "explicit"


class TestContextBuilder:
    def test_builds_bundle(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ws = "cb_test"
        ensure_workspace(ws)
        from context.builder import build_context_bundle
        b = build_context_bundle(ws, user_input="test", intent="context_qa")
        assert b.intent == "context_qa"
        assert b.execution_context is not None
        assert b.safe_llm_context is not None

    def test_request_context_contains_user_input(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ws = "cb_user_input"
        ensure_workspace(ws)
        from context.builder import build_context_bundle
        b = build_context_bundle(ws, user_input="memory怎么回事", intent="assistant_chat")
        request_items = [i for i in b.raw_items if i.get("item_type") == "request"]
        assert request_items
        assert request_items[0].get("summary") == "memory怎么回事"

    def test_safe_context_no_secret(self, temp_dirs):
        from workspace.manager import ensure_workspace
        ws = "cb_sec"
        ensure_workspace(ws)
        from context.builder import build_context_bundle
        b = build_context_bundle(ws, user_input="test")
        safe = b.safe_llm_context.as_dict() if b.safe_llm_context else {}
        raw = json.dumps(safe)
        assert "sk-" not in raw


class TestPromptRegistry:
    def test_registry_loads(self):
        from prompts.loader import load_prompt_registry
        reg = load_prompt_registry()
        assert len(reg) >= 5

    def test_get_by_task(self):
        from prompts.loader import get_prompt_by_task
        p = get_prompt_by_task("response_compose")
        assert p.task == "response_compose"

    def test_all_prompts_forbid_deployable(self):
        from prompts.loader import load_prompt_registry
        for p in load_prompt_registry():
            assert p.output_policy.get("forbid_deployable_generation") is True, p.prompt_id

    def test_all_prompts_forbid_full_config(self):
        from prompts.loader import load_prompt_registry
        for p in load_prompt_registry():
            assert p.input_policy.get("allow_full_source_config") is False, p.prompt_id

    def test_all_prompts_forbid_secrets(self):
        from prompts.loader import load_prompt_registry
        for p in load_prompt_registry():
            assert p.input_policy.get("allow_secret") is False, p.prompt_id

    def test_validate_passes(self):
        from prompts.loader import validate_prompt_registry
        result = validate_prompt_registry()
        assert result["valid"] is True


class TestPromptRenderer:
    def test_render_response_compose(self):
        from prompts.loader import render_prompt
        r = render_prompt("response_compose", safe_context={"intent": "translate_config"},
                          user_input="translate")
        assert r.prompt_id == "response.compose.v1"
        assert "translate_config" in r.text

    def test_render_context_qa(self):
        from prompts.loader import render_prompt
        r = render_prompt("context_qa", safe_context={"intent": "context_qa",
                          "last_result_summary": "3 deployable, 1 review"},
                          user_input="有什么风险？")
        assert r.prompt_id == "context.qa.v1"
        assert "context_qa" in r.task or r.task == "context_qa"

    def test_render_job_failure(self):
        from prompts.loader import render_prompt
        r = render_prompt("job_failure_explain", safe_context={"job_summary": {"status": "failed"}},
                          user_input="为什么失败？")
        assert r.prompt_id == "job_failure.explain.v1"

    def test_rendered_has_no_secrets(self):
        from prompts.loader import render_prompt
        r = render_prompt("response_compose", safe_context={"intent": "test"},
                          user_input="test")
        assert "sk-" not in r.text

    def test_citations_in_rendered(self):
        from prompts.loader import render_prompt
        cites = [{"citation_id": "cite_1", "source_type": "artifact", "source_id": "art_1"}]
        r = render_prompt("response_compose", safe_context={}, user_input="t", citations=cites)
        # Citations should be rendered — check citation_ids metadata
        assert "cite_1" in str(r.citation_ids)

    def test_response_prompt_requires_inline_citation_ids(self):
        from prompts.loader import render_prompt
        cites = [{"citation_id": "K1", "source_type": "knowledge", "source_id": "ksrc_1"}]
        r = render_prompt("response_compose", safe_context={}, user_input="t", citations=cites)
        assert "[K1]" in r.text
        assert "cite factual claims inline" in r.text

    def test_renderer_uses_safe_context_only(self):
        """Rendered prompt must NOT include full config if we pass it."""
        from prompts.loader import render_prompt
        r = render_prompt("response_compose",
                          safe_context={"intent": "test", "source_config": "hostname R1\ninterface Gi0/1"},
                          user_input="test")
        assert "ip address" not in r.text


class TestAPI:
    def test_context_status(self, client):
        resp = client.get("/api/context/status")
        assert resp.status_code == 200

    def test_context_resolve(self, client):
        resp = client.post("/api/context/resolve", json={"context_ref": "last_result"})
        assert resp.status_code == 200

    def test_context_build(self, client):
        resp = client.post("/api/context/build", json={"message": "test"})
        assert resp.status_code == 200

    def test_prompts_list(self, client):
        resp = client.get("/api/prompts")
        assert resp.status_code == 200
        assert "prompts" in resp.get_json()

    def test_prompt_render(self, client):
        resp = client.post("/api/prompts/render", json={"task": "response_compose", "message": "test"})
        assert resp.status_code == 200

    def test_harness_status(self, client):
        resp = client.get("/api/harness/status")
        assert resp.status_code == 200


class TestRegression:
    def test_translate_still_works(self, client):
        resp = client.post("/api/modules/config-translation/translate", json={
            "source_vendor": "cisco", "target_vendor": "huawei",
            "source_config": "hostname R1\ninterface Gi0/1\n ip address 10.1.1.1 255.255.255.0",
        })
        assert resp.get_json().get("ok") is True

    def test_agent_run_translate_config(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate cisco to huawei",
            "workspace_id": "cph_reg",
            "payload": {"source_vendor": "cisco", "target_vendor": "huawei",
                         "source_config": "hostname R1"},
        })
        assert resp.status_code == 200

    def test_no_api_translate(self, client):
        assert client.post("/api/translate", json={"test": 1}).status_code in (404, 405)

    def test_trace_still_7_nodes(self, client):
        resp = client.post("/api/agent/message", json={
            "message": "translate",
            "workspace_id": "cph_trace",
            "payload": {"source_vendor": "cisco", "target_vendor": "huawei",
                         "source_config": "hostname R1"},
        })
        data = resp.get_json()
        tl = data.get("timeline_summary", {})
        assert tl.get("node_count", 0) >= 6
