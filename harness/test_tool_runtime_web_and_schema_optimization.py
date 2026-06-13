"""Tool runtime optimization coverage for web search and LLM-facing schemas."""

from tool_runtime.schemas import ToolInvocation


def test_tool_catalog_exposes_input_schema_to_llm_adapter():
    from agent.llm.tool_adapter import tool_spec_to_openai_function
    from tool_runtime.integration import get_default_tool_runtime_client

    client = get_default_tool_runtime_client()
    web = client.get_tool("web.search")

    assert web["input_schema"]["required"] == ["query"]
    assert "top_k" in web["input_schema"]["properties"]
    assert "domains" in web["input_schema"]["properties"]

    fn = tool_spec_to_openai_function(web)
    params = fn["function"]["parameters"]
    assert fn["function"]["name"] == "web__search"
    assert params["required"] == ["query"]
    assert "query" in params["properties"]
    assert "top_k" in params["properties"]


def test_all_enabled_tools_have_llm_visible_schema_contract():
    from tool_runtime.integration import get_default_tool_runtime_client

    tools = get_default_tool_runtime_client().list_tools()
    enabled = [t for t in tools if t.get("enabled", True)]

    assert enabled
    for tool in enabled:
        schema = tool.get("input_schema")
        assert isinstance(schema, dict), f"{tool['tool_id']} missing input_schema"
        assert schema.get("type") == "object", f"{tool['tool_id']} schema must be object"
        assert isinstance(schema.get("properties", {}), dict), tool["tool_id"]
        assert isinstance(schema.get("required", []), list), tool["tool_id"]


def test_web_search_returns_citation_ready_results(monkeypatch):
    from tool_runtime.general_tools import handle_web_search

    html = """
    <html><body>
      <a rel="nofollow" class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.cisco.com%2Fc%2Fen%2Fsupport%2Fdocs%2Fip%2Fborder-gateway-protocol-bgp%2F.html">Cisco BGP Configuration Guide</a>
      <a class="result__snippet">Official Cisco BGP documentation and configuration examples.</a>
      <a rel="nofollow" class="result__a"
         href="https://example.com/bgp">Example BGP note</a>
      <a class="result__snippet">Public note about BGP.</a>
    </body></html>
    """

    class FakeResponse:
        status_code = 200
        text = html

        def json(self):
            return {"RelatedTopics": []}

    def fake_get(url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)
    out = handle_web_search(ToolInvocation(
        tool_id="web.search",
        arguments={
            "query": "BGP configuration",
            "domains": ["cisco.com"],
            "top_k": 3,
            "language": "en-US",
        },
    ))

    assert out["ok"] is True
    assert out["provider"] == "duckduckgo_html"
    assert out["count"] == 1
    result = out["results"][0]
    assert result["domain"] == "cisco.com"
    assert result["source_quality"] == "official_or_primary"
    assert result["citation"] == "[1] cisco.com"
    assert "duckduckgo.com/l" not in result["url"]
    assert "results_markdown" in out
    assert "web.fetch_summary" in " ".join(out["next_actions"])


def test_web_search_no_results_guides_agent(monkeypatch):
    from tool_runtime.general_tools import handle_web_search

    class FakeResponse:
        status_code = 200
        text = "<html></html>"

        def json(self):
            return {"RelatedTopics": []}

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeResponse())
    out = handle_web_search(ToolInvocation(
        tool_id="web.search",
        arguments={"query": "latest ospf obscure vendor thing", "site": "cisco.com"},
    ))

    assert out["ok"] is False
    assert out["status"] == "no_results"
    assert out["warnings"] == ["web_search_no_results"]
    assert out["next_actions"]
    assert out["filters"]["domains"] == ["cisco.com"]


def test_official_doc_search_uses_domain_limited_web_search(monkeypatch):
    from tool_runtime.general_tools import handle_web_official_doc_search

    calls = []

    def fake_web_search(inv):
        calls.append(dict(inv.arguments))
        return {
            "ok": True,
            "summary": "Found 1 public web result(s)",
            "results": [{
                "title": "Cisco OSPF Configuration Guide",
                "url": "https://www.cisco.com/c/en/us/support/docs/ip/open-shortest-path-first-ospf/",
                "domain": "cisco.com",
                "citation": "[1] cisco.com",
                "source_quality": "official_or_primary",
            }],
            "count": 1,
            "results_markdown": "[1] Cisco OSPF Configuration Guide: https://www.cisco.com/",
            "next_actions": ["Use citations."],
        }

    monkeypatch.setattr("tool_runtime.general_tools.handle_web_search", fake_web_search)

    out = handle_web_official_doc_search(ToolInvocation(
        tool_id="web.official_doc_search",
        arguments={"query": "OSPF neighbor state", "vendor": "cisco"},
    ))

    assert out["ok"] is True
    assert calls[0]["domains"] == ["cisco.com"]
    assert out["tool_id"] == "web.official_doc_search"
    assert out["source_type"] == "official_doc_search"
    assert out["official_domains"] == ["cisco.com"]
    assert "web.fetch_summary" in " ".join(out["next_actions"])


def test_web_save_to_artifact_returns_persisted_artifact_id(monkeypatch, temp_dirs):
    from artifacts.store import get_artifact
    from tool_runtime.general_tools import handle_web_save_to_artifact

    class FakeResponse:
        status_code = 200
        text = "<html><head><title>Doc</title></head><body>Useful vendor text.</body></html>"
        content = text.encode()
        encoding = "utf-8"
        apparent_encoding = "utf-8"

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeResponse())

    out = handle_web_save_to_artifact(ToolInvocation(
        tool_id="web.save_to_artifact",
        arguments={"workspace_id": "default", "url": "https://example.com/doc", "title": "Vendor Doc"},
    ))

    assert out["ok"] is True
    assert out["artifact_id"].startswith("art_")
    assert get_artifact("default", out["artifact_id"]) is not None


def test_web_fetch_summary_rejects_empty_readable_body(monkeypatch):
    from tool_runtime.general_tools import handle_web_fetch_summary

    class FakeResponse:
        status_code = 200
        text = "<html><head><title>Empty</title></head><script>var x = 1</script></html>"
        content = text.encode()
        encoding = "utf-8"
        apparent_encoding = "utf-8"

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeResponse())

    out = handle_web_fetch_summary(ToolInvocation(
        tool_id="web.fetch_summary",
        arguments={"url": "https://example.com/empty"},
    ))

    assert out["ok"] is False
    assert out["status"] == "empty_readable_text"
    assert out["warnings"] == ["web_fetch_empty_readable_text"]
    assert out["next_actions"]


def test_save_result_and_report_return_real_artifact_ids(temp_dirs):
    from artifacts.store import get_artifact
    from tool_runtime.general_tools import handle_artifact_save_result, handle_report_save_artifact

    saved = handle_artifact_save_result(ToolInvocation(
        tool_id="artifact.save_result",
        arguments={"workspace_id": "default", "content": "useful content", "title": "Useful"},
    ))
    report = handle_report_save_artifact(ToolInvocation(
        tool_id="report.save_artifact",
        arguments={"workspace_id": "default", "content": "report content", "title": "Report"},
    ))

    assert saved["ok"] is True
    assert report["ok"] is True
    assert get_artifact("default", saved["artifact_id"]) is not None
    assert get_artifact("default", report["artifact_id"]) is not None


def test_tool_message_payload_includes_citation_ready_web_fields():
    from agent.protocol.tool_result import ToolResult
    from agent.runtime.loop import _build_tool_message_payload

    result = ToolResult.from_legacy_dict("web.search", "call_web", {
        "ok": True,
        "summary": "Found 1 public web result(s)",
        "results_markdown": "[1] Cisco: https://www.cisco.com/ — Official docs",
        "answer_hint": "优先引用 official_or_primary 结果。",
        "next_actions": ["如果需要正文细节，再调用 web.fetch_summary。"],
        "results": [{
            "title": "Cisco docs",
            "url": "https://www.cisco.com/",
            "domain": "cisco.com",
            "snippet": "Official docs",
            "citation": "[1] cisco.com",
            "source_quality": "official_or_primary",
        }],
    })

    payload = _build_tool_message_payload(result)

    assert payload["results_markdown"].startswith("[1] Cisco")
    assert "official_or_primary" in payload["answer_hint"]
    assert payload["next_actions"]
    assert payload["results"][0]["citation"] == "[1] cisco.com"


def test_tool_message_payload_includes_standard_data_source_summary():
    from agent.protocol.tool_result import ToolResult
    from agent.runtime.loop import _build_tool_message_payload

    result = ToolResult(
        call_id="call_k",
        tool_id="knowledge.search",
        ok=True,
        summary="Found 1 chunk",
        data={
            "source_summary": [{
                "title": "OSPF guide",
                "source": "knowledge",
                "snippet": "OSPF neighbors use Hello packets.",
            }],
        },
    )

    payload = _build_tool_message_payload(result)

    assert payload["source_summary"][0]["title"] == "OSPF guide"
    assert "Hello" in payload["source_summary"][0]["snippet"]


def test_result_helper_preserves_caller_ok_flag():
    from tool_runtime.general_tools import _result

    assert _result(True, {"ok": False, "summary": "fallback"})["ok"] is True
    assert _result(False, {"ok": True, "summary": "blocked"})["ok"] is False


def test_official_doc_search_fallback_index_counts_as_success(monkeypatch):
    from tool_runtime.general_tools import handle_web_official_doc_search

    def fake_web_search(inv):
        return {
            "ok": False,
            "summary": "搜索服务未返回结果",
            "results": [],
            "count": 0,
            "next_actions": [],
        }

    monkeypatch.setattr("tool_runtime.general_tools.handle_web_search", fake_web_search)

    out = handle_web_official_doc_search(ToolInvocation(
        tool_id="web.official_doc_search",
        arguments={"query": "OSPF neighbor", "vendor": "cisco"},
    ))

    assert out["ok"] is True
    assert out["status"] == "fallback_doc_index"
    assert out["count"] == 1
    assert out["results"][0]["source_quality"] == "official_or_primary"
    assert out["results"][0]["citation"] == "[1] cisco.com"
    assert out["results"][0]["url"].startswith("https://www.cisco.com/")
