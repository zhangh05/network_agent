"""Bridge durable memory into the knowledge retrieval index.

Memory remains the source of truth for user preferences, decisions, and
workspace facts. This module writes a safe, searchable projection into the
knowledge chunk store so RuntimeLoop can retrieve memory through the same RAG
path as uploaded documents.
"""

from __future__ import annotations

from typing import Optional

from memory.redaction import redact_text


def index_memory_record(record) -> dict:
    """Create or return a RAG projection for a memory record.

    The operation is intentionally best-effort for callers: it returns a result
    dict instead of raising. The memory JSONL store stays authoritative.
    """
    data = record.as_dict() if hasattr(record, "as_dict") else dict(record or {})
    memory_id = str(data.get("memory_id", "") or "")
    workspace_id = str(data.get("project_id", "") or "default")
    if not memory_id:
        return {"ok": False, "error": "missing_memory_id"}

    existing = _find_projection(workspace_id, memory_id)
    if existing:
        return {
            "ok": True,
            "memory_id": memory_id,
            "source_id": existing.get("source_id", ""),
            "summary": "memory projection already indexed",
        }

    title = _memory_title(data)
    body = _memory_markdown(data)
    try:
        from agent.modules.knowledge.service import import_file
        result = import_file(
            workspace_id=workspace_id,
            source=body.encode("utf-8"),
            title=title,
            source_type="memory",
            scope=_knowledge_scope(data.get("scope", "")),
            language="zh",
            tags=_memory_tags(data),
            metadata={
                "hidden": True,
                "origin": "memory",
                "memory_id": memory_id,
                "memory_type": data.get("memory_type", ""),
                "memory_scope": data.get("scope", ""),
                "memory_confidence": data.get("confidence", ""),
                "memory_source": data.get("source", ""),
            },
        )
    except Exception as exc:
        return {
            "ok": False,
            "memory_id": memory_id,
            "error": f"memory_index_failed: {str(exc)[:160]}",
        }
    if not result.get("ok"):
        return {
            "ok": False,
            "memory_id": memory_id,
            "error": (result.get("errors") or [result.get("summary", "index_failed")])[0],
            "summary": result.get("summary", ""),
        }
    return {
        "ok": True,
        "memory_id": memory_id,
        "source_id": result.get("source_id", ""),
        "summary": result.get("summary", ""),
    }


def index_memory_by_id(memory_id: str) -> dict:
    from memory.store import get_store

    record = get_store().get(memory_id)
    if record is None:
        return {"ok": False, "memory_id": memory_id, "error": "memory_not_found"}
    return index_memory_record(record)


def delete_memory_projection(memory_id: str, workspace_id: str = "") -> dict:
    """Soft-delete knowledge sources generated for a memory record."""
    memory_id = str(memory_id or "")
    if not memory_id:
        return {"ok": False, "error": "missing_memory_id", "deleted_count": 0}
    workspace_ids = [workspace_id] if workspace_id else _candidate_workspaces()
    deleted = []
    for ws_id in workspace_ids:
        for source in _find_projections(ws_id, memory_id):
            try:
                from agent.modules.knowledge.service import delete_source
                result = delete_source(ws_id, source.get("source_id", ""))
            except Exception:
                result = {"ok": False}
            if result.get("ok"):
                deleted.append(source.get("source_id", ""))
    return {
        "ok": True,
        "memory_id": memory_id,
        "deleted_count": len(deleted),
        "deleted_source_ids": deleted,
    }


def _find_projection(workspace_id: str, memory_id: str) -> Optional[dict]:
    matches = _find_projections(workspace_id, memory_id)
    return matches[0] if matches else None


def _find_projections(workspace_id: str, memory_id: str) -> list:
    try:
        from agent.modules.knowledge.service import list_sources
        result = list_sources(workspace_id, include_disabled=True)
    except Exception:
        return []
    out = []
    for source in result.get("sources", []):
        meta = source.get("metadata", {}) or {}
        if meta.get("origin") == "memory" and meta.get("memory_id") == memory_id:
            out.append(source)
    return out


def _candidate_workspaces() -> list:
    try:
        import workspace.manager as wm
        root = wm.WS_ROOT
        if not root.exists():
            return ["default"]
        names = [
            p.name for p in root.iterdir()
            if p.is_dir() and (p / "sys" / "knowledge").exists()
        ]
        return names or ["default"]
    except Exception:
        return ["default"]


def _memory_title(data: dict) -> str:
    title = str(data.get("title", "") or data.get("summary", "") or "记忆").strip()
    if title.startswith("记忆:"):
        return title[:180]
    return f"记忆: {title[:170]}"


def _memory_markdown(data: dict) -> str:
    title = redact_text(str(data.get("title", "") or "记忆"))
    summary = redact_text(str(data.get("summary", "") or ""))
    content = redact_text(str(data.get("content", "") or ""))
    memory_type = str(data.get("memory_type", "") or "knowledge_note")
    scope = str(data.get("scope", "") or "project")
    confidence = str(data.get("confidence", "") or "system_generated")
    tags = ", ".join(_memory_tags(data))
    parts = [
        f"# {title}",
        "",
        f"- 类型: {memory_type}",
        f"- 范围: {scope}",
        f"- 可信度: {confidence}",
    ]
    if tags:
        parts.append(f"- 标签: {tags}")
    if summary:
        parts.extend(["", "## 摘要", summary])
    if content:
        parts.extend(["", "## 内容", content])
    return "\n".join(parts).strip() + "\n"


def _memory_tags(data: dict) -> list:
    raw = list(data.get("tags") or [])
    base = ["memory", str(data.get("memory_type", "") or "knowledge_note"),
            str(data.get("scope", "") or "project")]
    out = []
    seen = set()
    for tag in base + raw:
        tag = str(tag or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _knowledge_scope(memory_scope: str) -> str:
    if memory_scope == "long_term":
        return "global"
    if memory_scope == "short_term":
        return "session"
    return "workspace"
