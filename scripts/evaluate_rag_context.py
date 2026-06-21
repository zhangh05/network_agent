#!/usr/bin/env python3
"""Evaluate unified RAG context assembly without calling an LLM."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TMP_ROOT = Path(tempfile.mkdtemp(prefix="rag_context_eval_"))
os.environ["WS_ROOT"] = str(TMP_ROOT)

try:
    import workspace.manager as wm
    wm.WS_ROOT = TMP_ROOT
except Exception:
    pass

# Patch ContextStore and UnifiedRetriever to use temp directory
try:
    import context.context_store as _cs
    _cs._BASE = TMP_ROOT
    _cs._stores.clear()
except Exception:
    pass
try:
    import context.unified_retriever as _ur
    _ur._retrievers.clear()
except Exception:
    pass


def seed(workspace_id: str) -> None:
    from agent.modules.knowledge.service import import_file
    from memory.writer import write_user_preference

    doc = (
        "# OSPF Runbook\n\n"
        "FULL to INIT usually means one-way Hello, area mismatch, "
        "authentication mismatch, MTU issues, or ACL blocking protocol 89.\n"
    )
    out = import_file(
        workspace_id=workspace_id,
        source=doc.encode("utf-8"),
        title="OSPF Runbook",
        source_type="project_doc",
        scope="workspace",
        tags=["ospf", "runbook"],
    )
    if not out.get("ok"):
        raise RuntimeError(out)
    mid = write_user_preference(
        title="OSPF answer style",
        content="When answering OSPF troubleshooting questions, start with the shortest command sequence.",
        tags=["ospf", "style"],
        workspace_id=workspace_id,
    )
    if not mid:
        raise RuntimeError("memory seed failed")


def evaluate() -> dict:
    workspace_id = "rag_eval_ws"
    seed(workspace_id)

    from agent.core.turn_context import TurnContext
    from agent.runtime.cognition.evidence_pipeline import EvidencePipeline

    ctx = TurnContext(
        workspace_id=workspace_id,
        user_input="OSPF FULL 变 INIT 怎么排查",
        scene_decision=SimpleNamespace(
            is_simple_chat=False,
            is_knowledge_task=True,
            needs_knowledge=True,
            is_factual_query=True,
            needs_memory=True,
            is_memory_task=False,
            user_input="OSPF FULL 变 INIT 怎么排查",
        ),
        metadata={},
    )
    evidence = EvidencePipeline().build(ctx)
    safe = evidence.to_safe_context()

    k_hits = safe.get("knowledge_hits") or []
    m_hits = safe.get("memory_hits") or []
    text = json.dumps(safe, ensure_ascii=False)
    metrics = {
        "source_count": len(k_hits) + len(m_hits),
        "knowledge_hit_count": len(k_hits),
        "memory_hit_count": len(m_hits),
        "citation_count": len(safe.get("citations") or []),
        "has_ospf_evidence": "FULL to INIT" in text or "one-way Hello" in text,
        "has_memory_evidence": "shortest command sequence" in text,
        "leaks_sensitive_keys": any(k in text for k in (
            "source_config",
            "deployable_config",
            "password",
            '"token"',
            "access_token",
            "/Users/",
        )),
    }
    ok = (
        metrics["source_count"] >= 2
        and metrics["knowledge_hit_count"] >= 1
        and metrics["memory_hit_count"] >= 1
        and metrics["citation_count"] >= 1
        and metrics["has_ospf_evidence"]
        and metrics["has_memory_evidence"]
        and not metrics["leaks_sensitive_keys"]
    )
    return {"ok": ok, "workspace_id": workspace_id, "metrics": metrics}


def main() -> int:
    result = evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
