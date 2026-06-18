"""Test frontend-backend contract alignment.

v1.0.3: verifies:
- AgentResult fields match frontend ToolCallResult / AgentResult interfaces
- SessionMessage message_id format (<run_id>:<role>)
- /api/capabilities projection from CapabilityRegistry
"""

import json
import re
import pytest
from pathlib import Path

from workspace.message_store import USER_MSG_ID, ASSISTANT_MSG_ID


WS_ID = "test_febe_align"


@pytest.fixture(autouse=True)
def clean_ws():
    from workspace.manager import ensure_workspace
    ensure_workspace(WS_ID)
    yield


# ── ToolCallResult contract ──


def test_tool_call_standard_fields():
    """The 10 standard tool_call fields from _to_standard_tool_call()."""
    from agent.runtime.tool_result_utils import to_standard_tool_call
    from agent.protocol.tool_result import ToolResult

    tr = ToolResult(
        call_id="call_001",
        tool_id="test.tool",
        ok=True,
        summary="all good",
        artifacts=[{"artifact_id": "a1", "artifact_type": "config", "title": "test config"}],
        source_count=3,
        manual_review_count=0,
        errors=[],
        warnings=[],
        metadata={"extra": "info"},
    )

    tc = to_standard_tool_call("call_001", "test.tool", tr)

    # All 11 standard fields must be present
    required = {
        "call_id", "tool_id", "ok", "summary", "artifacts",
        "source_count", "manual_review_count", "errors", "warnings", "metadata",
        "result",
    }
    assert required == set(tc.keys()), f"Missing fields: {required - set(tc.keys())}, extra: {set(tc.keys()) - required}"

    assert tc["call_id"] == "call_001"
    assert tc["tool_id"] == "test.tool"
    assert tc["ok"] is True
    assert tc["summary"] == "all good"
    assert len(tc["artifacts"]) == 1
    assert tc["source_count"] == 3
    assert tc["manual_review_count"] == 0
    assert tc["errors"] == []
    assert tc["warnings"] == []
    assert tc["metadata"] == {"extra": "info"}


def test_tool_call_dict_compat():
    """Retired dict-shaped results also produce the 10 standard fields."""
    from agent.runtime.tool_result_utils import to_standard_tool_call

    retired = {
        "ok": False,
        "summary": "something went wrong",
        "errors": ["bad arg"],
    }
    tc = to_standard_tool_call("call_002", "test.fail", retired)

    assert tc["ok"] is False
    assert tc["summary"] == "something went wrong"
    assert tc["errors"] == ["bad arg"]
    # All fields present even for retired
    assert "artifacts" in tc
    assert "source_count" in tc
    assert "metadata" in tc


# ── SessionMessage contract ──


def test_message_id_format():
    """message_id uses colon format, not underscore."""
    mid = USER_MSG_ID.format(run_id="r001")
    assert mid == "r001:user"
    mid = ASSISTANT_MSG_ID.format(run_id="r001")
    assert mid == "r001:assistant"


def test_message_id_no_random_prefix():
    """Frontend MUST NOT fabricate random IDs; message_id is deterministic."""
    mid1 = USER_MSG_ID.format(run_id="r001")
    mid2 = USER_MSG_ID.format(run_id="r001")
    assert mid1 == mid2  # Same run_id always produces same message_id

    mid3 = USER_MSG_ID.format(run_id="r002")
    assert mid1 != mid3  # Different run_id produces different message_id


# ── Capability API projection ──


def test_capabilities_api_projection():
    """handle_capabilities() returns data from CapabilityRegistry."""
    from backend.api.modules import handle_capabilities
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context():
        resp = handle_capabilities()

    data = resp.get_json()
    assert "capabilities" in data
    assert "enabled" in data

    caps = data["capabilities"]
    assert len(caps) == 7, f"Expected 7 capabilities, got {len(caps)}"

    for c in caps:
        assert "capability_id" in c
        assert "status" in c
        assert c["status"] in ("enabled", "planned", "disabled")

    enabled_ids = data["enabled"]
    assert len(enabled_ids) == 4
    assert "config_translation" in enabled_ids
    assert "knowledge" in enabled_ids
    assert "artifact" in enabled_ids
    assert "review" in enabled_ids


def test_capabilities_api_no_planned_callable():
    """Planned capabilities must never be listed as enabled."""
    from backend.api.modules import handle_capabilities
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context():
        resp = handle_capabilities()

    data = resp.get_json()
    enabled = set(data["enabled"])
    planned_ids = {"topology", "inspection", "cmdb"}
    assert not (enabled & planned_ids), f"Planned capabilities leaked into enabled: {enabled & planned_ids}"


# ── AgentResult metadata contract ──


def test_agent_result_metadata_has_selected_skills():
    """v1.0.3: AgentResult.metadata includes selected_skills."""
    # This is validated through the enrich_metadata helper
    from agent.runtime.tool_result_utils import enrich_metadata
    from types import SimpleNamespace

    ctx = SimpleNamespace(
        metadata={"selected_skills": ["config_translation"], "visible_tools": ["test.tool"]}
    )

    base = {"model": "test", "steps": 1}
    enriched = enrich_metadata(base, ctx)
    assert enriched["selected_skills"] == ["config_translation"]
    assert enriched["visible_tools"] == ["test.tool"]
    assert enriched["model"] == "test"


def test_agent_result_metadata_no_overwrite():
    """enrich_metadata does NOT overwrite existing keys."""
    from agent.runtime.tool_result_utils import enrich_metadata
    from types import SimpleNamespace

    ctx = SimpleNamespace(
        metadata={"selected_skills": ["ctx_value"], "visible_tools": ["ctx_tool"]}
    )

    base = {"selected_skills": ["base_value"], "visible_tools": ["base_tool"], "model": "x"}
    enriched = enrich_metadata(base, ctx)
    # Base keys take precedence
    assert enriched["selected_skills"] == ["base_value"]
    assert enriched["visible_tools"] == ["base_tool"]


# ── Workspace knowledge path ──


def test_workspace_counts_artifact_subdirs():
    """_count_artifacts counts records in the latest files/* layout only."""
    from workspace.manager import _count_artifacts
    count = _count_artifacts(WS_ID)
    assert count == 0  # Empty workspace has 0 artifacts


def _normalise_backend_route(path: str) -> str:
    path = re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", "{param}", path)
    return path.removeprefix("/api")


def _normalise_frontend_url(path: str) -> str:
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{encodeURIComponent\([^}]+\)\}", "{param}", path)
    path = re.sub(r"\$\{[^}]+\}", "{param}", path)
    return path


def _frontend_url_references() -> list[tuple[str, str, str, int]]:
    """Return (method, url, file, line) for frontend API URL literals."""
    root = Path(__file__).resolve().parents[1]
    files = list((root / "frontend" / "src").rglob("*.ts")) + list((root / "frontend" / "src").rglob("*.tsx"))
    url_pat = re.compile(r"url:\s*(`[^`]+`|'[^']+'|\"[^\"]+\")")
    refs: list[tuple[str, str, str, int]] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in url_pat.finditer(text):
            raw = match.group(1)[1:-1]
            if not raw.startswith("/") or raw.startswith("http"):
                continue
            window = text[max(0, match.start() - 260):match.start() + 140]
            method_matches = list(re.finditer(r"method:\s*['\"]([A-Z]+)['\"]", window))
            method = method_matches[-1].group(1) if method_matches else "GET"
            refs.append((method, raw, str(path.relative_to(root)), text.count("\n", 0, match.start()) + 1))
    return refs


def test_frontend_url_literals_match_backend_routes():
    """Every frontend API URL literal must map to a real Flask route + method."""
    from backend.main import app as flask_app

    backend: dict[str, set[str]] = {}
    for rule in flask_app.url_map.iter_rules():
        route = str(rule.rule)
        if not route.startswith("/api/"):
            continue
        methods = {m for m in rule.methods if m not in {"HEAD", "OPTIONS"}}
        backend.setdefault(_normalise_backend_route(route), set()).update(methods)

    missing: list[str] = []
    for method, raw_url, file, line in _frontend_url_references():
        url = _normalise_frontend_url(raw_url)
        methods = backend.get(url)
        if not methods or method not in methods:
            missing.append(
                f"{method} {raw_url} at {file}:{line} backend_methods={sorted(methods or [])}"
            )

    assert not missing, "Frontend API endpoints missing backend routes:\n" + "\n".join(missing)


# ── CapabilityRegistry → Runtime Summary alignment ──


def test_runtime_summary_uses_capability_registry():
    """/api/runtime/summary reads from CapabilityRegistry."""
    from backend.api.runtime_routes import register_runtime_routes
    from flask import Flask

    app = Flask(__name__)
    register_runtime_routes(app)

    with app.test_client() as client:
        resp = client.get("/api/runtime/summary")
        data = resp.get_json()

        assert data["capabilities"]["total"] == 7
        assert data["capabilities"]["enabled"] == 4
        assert data["capabilities"]["planned"] == 3
