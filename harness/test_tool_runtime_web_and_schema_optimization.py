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
