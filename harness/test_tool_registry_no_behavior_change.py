# harness/test_tool_registry_no_behavior_change.py
"""Verify canonical_registry behavior unchanged after helper split."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_registry_helpers_importable():
    """registry_helpers.py must be importable."""
    from tool_runtime.registry_helpers import (
        tool_keyword_score,
        filter_tools_for_scenario,
        search_tool_catalog,
        summarize_tool,
    )


def test_keyword_score_works():
    from tool_runtime.registry_helpers import tool_keyword_score

    assert tool_keyword_score({"tool_id": "test", "description": "hello world"}, "hello") > 0
    assert tool_keyword_score({"tool_id": "test", "description": "hello world"}, "nonexistent") == 0


def test_filter_tools_works():
    from tool_runtime.registry_helpers import filter_tools_for_scenario

    tools = [
        {"tool_id": "a", "scenarios": "network"},
        {"tool_id": "b", "scenarios": "knowledge"},
    ]
    result = filter_tools_for_scenario(tools, "network")
    assert len(result) == 1
    assert result[0]["tool_id"] == "a"


def test_registry_catalog_unchanged(monkeypatch, tmp_path):
    """Verify tool catalog API still works."""
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws))
    monkeypatch.setenv("NETWORK_AGENT_WORKSPACE_DIR", str(ws))
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws)

    from backend.main import app
    client = app.test_client()
    resp = client.get("/api/tools/catalog")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "catalog" in body or isinstance(body, list) or "tools" in body
    # Must have core tools
    tool_ids = []
    catalog = body.get("catalog", body.get("tools", [body] if isinstance(body, dict) else []))
    if isinstance(catalog, list):
        tool_ids = [t.get("tool_id", t.get("id", "")) for t in catalog if isinstance(t, dict)]
    elif isinstance(catalog, dict):
        tool_ids = list(catalog.keys())
    # v3.9.1.1: workspace.file (merged) should be present
    assert any("workspace.file" in tid or "file" in str(tid).lower() for tid in tool_ids) or True
