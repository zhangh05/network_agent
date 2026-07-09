from types import SimpleNamespace

import pytest

from core.context.fragments.context_bundle import ContextBundleFragment
from core.context.fragments.memory import MemoryHitsFragment
from core.context.fragments.workspace import WorkspaceStateFragment
from core.tools.general_tools.shared import _summarize
from observability.timeline import add_event


def test_context_fragments_do_not_fallback_to_default_workspace():
    state = SimpleNamespace(
        workspace_id="",
        context={},
        user_input="hello",
        intent="chat",
        payload={},
        request_id="run-test",
        trace_id="trace-test",
    )

    for fragment in (WorkspaceStateFragment(), MemoryHitsFragment(), ContextBundleFragment()):
        data = fragment.build(state)
        assert data["ok"] is False
        assert data["error"] == "workspace_id_required"


def test_trace_event_requires_explicit_workspace_id():
    state = SimpleNamespace(request_id="run-test", workspace_id="", trace_events=[])

    with pytest.raises(ValueError, match="workspace_id is required"):
        add_event(state, "stage", "planner")


def test_tool_summary_fallback_is_not_completed_spam():
    assert _summarize({}) == "Tool completed without structured output."
    assert _summarize({}) != "Completed."
