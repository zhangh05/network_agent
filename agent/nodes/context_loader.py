# agent/nodes/context_loader.py
"""Context loader — loads workspace, memory hits, registry info."""

import json
import os

from agent.state import NetworkAgentState

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_context(state: NetworkAgentState) -> NetworkAgentState:
    """Load context: memory hits, module/skill registries."""

    # Load memory hits
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        hits = store.search(state.user_input, limit=5)
        state.memory_hits = [h if isinstance(h, dict) else h.as_dict() for h in hits]
    except Exception:
        pass

    # Load module registry
    try:
        with open(os.path.join(ROOT, "modules", "registry.json"), encoding="utf-8") as f:
            modules = json.load(f)
        state.context["modules"] = {
            m["module_name"]: m["status"] for m in modules.get("modules", [])
        }
    except Exception:
        pass

    # Load skill registry
    try:
        with open(os.path.join(ROOT, "skills", "registry.json"), encoding="utf-8") as f:
            skills = json.load(f)
        state.context["skills"] = {
            s["skill_name"]: s.get("enabled", False) for s in skills.get("skills", [])
        }
    except Exception:
        pass

    return state
