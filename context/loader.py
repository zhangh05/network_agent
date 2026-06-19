# context/loader.py
"""Context loader — loads raw ContextItems from all sources.

v4.0.0: Memory and knowledge retrieval moved to runtime/memory and
runtime/knowledge modules. Loader handles workspace/artifact/job/report only.
"""

from context.schemas import ContextItem, ContextRef


def load_context_items(workspace_id: str, context_ref=None, intent: str = "",
                       payload: dict = None, capability_id: str = "",
                       user_input: str = "",
                       include_memory=True, include_workspace=True,
                       include_artifacts=True, include_jobs=True,
                       include_reports=True, include_trace=True,
                       include_knowledge=True) -> list:
    items = []

    # 1. Request item (P0)
    msg = user_input or (payload or {}).get("message", "")
    items.append(ContextItem(
        item_type="request", source="request", priority=0,
        title="User request", summary=msg[:200],
        content={"intent": intent, "payload_keys": list((payload or {}).keys())},
        sensitivity="internal", scope="request",
        token_estimate=len(msg) // 4,
    ))

    # 2. Explicit context_ref item (P1)
    if context_ref and hasattr(context_ref, 'resolved') and context_ref.resolved:
        items.append(ContextItem(
            item_type=f"ref:{context_ref.ref_type}", source="request", priority=10,
            title=f"Context: {context_ref.ref_type}", summary=f"Resolved ref: {context_ref.ref_id}",
            source_id=context_ref.ref_id, sensitivity="internal", scope="request",
        ))

    # 3. Workspace state (P3)
    if include_workspace:
        try:
            from workspace.manager import get_workspace_state
            ws = get_workspace_state(workspace_id)
            safe_ws = {k: v for k, v in ws.items()
                       if k not in ("source_config", "deployable_config")
                       and "path" not in k.lower()}
            items.append(ContextItem(
                item_type="workspace_state", source="workspace", priority=30,
                title="Workspace state", summary=ws.get("last_result_summary", "")[:200],
                content=safe_ws, sensitivity="internal", scope="workspace",
                token_estimate=len(str(safe_ws)) // 4,
            ))
        except Exception:
            pass

    # 6. Artifact refs (P4 or P2 if explicit)
    if include_artifacts:
        try:
            from artifacts.store import list_artifacts
            arts = list_artifacts(workspace_id, limit=10)
            for a in arts:
                priority = 20 if context_ref and context_ref.ref_id == a.get("artifact_id") else 40
                items.append(ContextItem(
                    item_type="artifact_summary", source="artifact", priority=priority,
                    title=a.get("title", ""), summary=a.get("summary", "")[:200],
                    content={"artifact_id": a.get("artifact_id"), "artifact_type": a.get("artifact_type"),
                             "sensitivity": a.get("sensitivity"), "scope": a.get("scope")},
                    sensitivity=a.get("sensitivity", "internal"), scope="workspace",
                    source_id=a.get("artifact_id", ""),
                    token_estimate=len(str(a)) // 4,
                ))
        except Exception:
            pass

    # 7. Job summary (P4 or P2)
    if include_jobs:
        try:
            from jobs.store import list_jobs
            jobs = list_jobs(ws_id=workspace_id, limit=5)
            for j in jobs:
                priority = 20 if context_ref and context_ref.ref_id == j.get("job_id") else 40
                items.append(ContextItem(
                    item_type="job_summary", source="job", priority=priority,
                    title=j.get("title", ""), summary=f"Status: {j.get('status','')}",
                    content={"job_id": j.get("job_id"), "job_type": j.get("job_type"),
                             "status": j.get("status"), "progress": j.get("progress", {})},
                    sensitivity="internal", scope="workspace",
                    source_id=j.get("job_id", ""),
                    token_estimate=len(str(j)) // 4,
                ))
        except Exception:
            pass

    # 8. Report summary (P4)
    if include_reports:
        try:
            from artifacts.store import list_artifacts
            reports = list_artifacts(workspace_id, artifact_type="report", limit=5)
            for r in reports:
                items.append(ContextItem(
                    item_type="report_summary", source="report", priority=40,
                    title=r.get("title", ""), summary=r.get("summary", "")[:200],
                    content={"artifact_id": r.get("artifact_id"), "format": r.get("metadata", {}).get("format", "")},
                    sensitivity=r.get("sensitivity", "internal"), scope="workspace",
                    source_id=r.get("artifact_id", ""),
                    token_estimate=len(str(r)) // 4,
                ))
        except Exception:
            pass

    return items
