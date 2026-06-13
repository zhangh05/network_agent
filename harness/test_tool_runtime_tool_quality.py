"""Tool quality gates.

These tests protect the LLM-facing tool layer from regressing into empty
placeholders. A tool may fail because inputs are missing or external state is
unavailable, but it must fail loudly and usefully.
"""

from tool_runtime.schemas import ToolInvocation


def _sample_args(spec):
    args = {"workspace_id": "default"}
    props = spec.input_schema.get("properties", {})
    for name in spec.input_schema.get("required", []):
        if name in ("query",):
            args[name] = "ospf neighbor"
        elif name == "location":
            args[name] = "Hangzhou"
        elif name == "url":
            args[name] = "https://example.com/page"
        elif name == "content":
            args[name] = "useful generated content"
        elif name == "summary":
            args[name] = "safe summary"
        elif name == "text":
            args[name] = "alpha beta beta"
        elif name == "text_a":
            args[name] = "alpha"
        elif name == "text_b":
            args[name] = "beta"
        elif name == "rows":
            args[name] = [["a", "b"]]
        elif name == "mermaid":
            args[name] = "flowchart TD\nA[Start] --> B[Done]"
        elif name == "filename":
            args[name] = "tool-quality.txt"
        elif name == "filepath":
            args[name] = "missing.txt"
        elif name == "artifact_id":
            args[name] = "art_missing"
        elif name == "source_id":
            args[name] = "ks_missing"
        elif name == "chunk_id":
            args[name] = "chunk_missing"
        elif name == "session_id":
            args[name] = "session_missing"
        elif name == "run_id":
            args[name] = "run_missing"
        elif name == "tags":
            args[name] = ["qa"]
        elif name == "command_id":
            args[name] = "system.platform_info"
        elif name == "script_id":
            args[name] = "win.platform_info"
        else:
            args[name] = "sample"

    if "rows" in props and "rows" not in args:
        args["rows"] = [["a", "b"]]
    if "headers" in props:
        args["headers"] = ["A", "B"]
    if spec.tool_id == "weather.forecast":
        args["days"] = 2
    return args


def test_all_general_tools_return_useful_contract(monkeypatch, tmp_path, temp_dirs):
    from tool_runtime.general_tools import register_all_general_tools
    from tool_runtime.registry import ToolRegistry

    monkeypatch.setattr("tool_runtime.general_tools.ROOT", tmp_path)
    monkeypatch.setattr("tool_runtime.general_tools.WS_ROOT", tmp_path / "workspaces")

    class FakeResponse:
        status_code = 200
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def __init__(self, url):
            self.url = url
            self.text = (
                '<html><head><title>Example</title></head><body>'
                '<a class="result__a" href="https://example.com/doc">Example Doc</a>'
                '<a class="result__snippet">Useful public snippet.</a>'
                '<a href="https://example.com/next">Next</a>'
                '<p>Readable page body with useful details.</p>'
                '</body></html>'
            )
            self.content = self.text.encode()

        def json(self):
            if "geocoding-api.open-meteo.com" in self.url:
                return {"results": [{"name": "杭州", "country": "中国", "latitude": 30.25, "longitude": 120.16}]}
            if "api.open-meteo.com" in self.url:
                return {
                    "timezone": "Asia/Shanghai",
                    "current": {
                        "time": "2026-06-13T18:00",
                        "temperature_2m": 27,
                        "relative_humidity_2m": 80,
                        "precipitation": 0,
                        "weather_code": 2,
                        "wind_speed_10m": 9,
                        "wind_direction_10m": 90,
                    },
                    "current_units": {
                        "temperature_2m": "°C",
                        "relative_humidity_2m": "%",
                        "precipitation": "mm",
                        "wind_speed_10m": "km/h",
                        "wind_direction_10m": "°",
                    },
                    "daily": {
                        "time": ["2026-06-13", "2026-06-14"],
                        "weather_code": [2, 61],
                        "temperature_2m_max": [31, 29],
                        "temperature_2m_min": [24, 23],
                        "precipitation_probability_max": [20, 65],
                        "precipitation_sum": [0, 4.2],
                        "wind_speed_10m_max": [16, 20],
                    },
                    "daily_units": {
                        "temperature_2m_max": "°C",
                        "temperature_2m_min": "°C",
                        "precipitation_probability_max": "%",
                        "precipitation_sum": "mm",
                        "wind_speed_10m_max": "km/h",
                    },
                }
            return {"RelatedTopics": []}

    monkeypatch.setattr("requests.get", lambda url, **kwargs: FakeResponse(url))

    registry = register_all_general_tools(ToolRegistry())
    non_payload = {
        "ok", "tool_id", "status", "summary", "warnings", "errors",
        "next_actions", "metadata", "source_type", "provider", "query",
        "filters",
    }

    for spec in registry._specs.values():
        handler = registry.get_handler(spec.tool_id)
        out = handler(ToolInvocation(
            tool_id=spec.tool_id,
            arguments=_sample_args(spec),
            workspace_id="default",
            dry_run=True,
        ))

        assert isinstance(out, dict), spec.tool_id
        assert out.get("tool_id") == spec.tool_id
        assert out.get("status"), spec.tool_id
        assert out.get("summary"), spec.tool_id
        if out.get("ok"):
            payload_keys = [
                k for k, v in out.items()
                if k not in non_payload and v not in (None, "", [], {})
            ]
            assert payload_keys or "tool_returned_no_payload" in out.get("warnings", []), spec.tool_id
        else:
            assert out.get("errors"), spec.tool_id
