#!/usr/bin/env python3
"""Evaluate unified RAG context assembly without calling an LLM."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


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
        project_id=workspace_id,
    )
    if not mid:
        raise RuntimeError("memory seed failed")


def evaluate() -> dict:
    workspace_id = "rag_eval_ws"
    seed(workspace_id)
    from context.builder import build_context_bundle

    bundle = build_context_bundle(workspace_id, user_input="OSPF FULL 变 INIT 怎么排查")
    safe = bundle.safe_llm_context.as_dict()
    sources = safe.get("context_sources") or []
    hits = safe.get("knowledge_hits") or []
    text = json.dumps(safe, ensure_ascii=False)
    metrics = {
        "source_count": len(sources),
        "knowledge_hit_count": sum(1 for s in sources if s.get("evidence_type") == "knowledge"),
        "memory_hit_count": sum(1 for s in sources if s.get("evidence_type") == "memory"),
        "citation_count": len(safe.get("citations") or []),
        "has_ospf_evidence": "FULL to INIT" in text or "one-way Hello" in text,
        "has_memory_evidence": "shortest command sequence" in text,
        "leaks_sensitive_keys": any(k in text for k in ("source_config", "deployable_config", "password", "token", "/Users/")),
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
