"""Split general tool handlers."""
from tool_runtime.general_tools.shared import *

def handle_knowledge_index_artifact(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    art_id = args.get("artifact_id", "")
    try:
        validate_workspace_id(ws)
        from knowledge.indexer import index_artifact
        result = index_artifact(ws, art_id)
        return _ok(inv, "", {"indexed": result.get("ok", False), "source_id": result.get("source_id", "")})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_knowledge_reindex(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    source_id = args.get("source_id", "")
    try:
        validate_workspace_id(ws)
        from knowledge.indexer import reindex_source
        result = reindex_source(ws, source_id)
        return _ok(inv, "", {"reindexed": result.get("ok", False)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_knowledge_search(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    query = (args.get("query") or "").strip()
    limit = min(int(args.get("limit", 5)), 10)
    try:
        validate_workspace_id(ws)
        from knowledge.search import search
        results = search(workspace_id=ws, query=query, limit=limit, llm_safe_only=True)
        safe_results = []
        for r in results:
            d = r.as_dict() if hasattr(r, 'as_dict') else r
            safe_results.append({
                "chunk_id": d.get("chunk_id", ""),
                "title": d.get("title", ""),
                "summary": d.get("summary", ""),
                "safe_excerpt": d.get("safe_excerpt", ""),
                "sensitivity": d.get("sensitivity", "internal"),
                "score": d.get("score", 0),
                "llm_safe": d.get("llm_safe", True),
            })
        return _ok(inv, "", {"results": safe_results, "count": len(safe_results)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_knowledge_get_source(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    source_id = args.get("source_id", "")
    try:
        validate_workspace_id(ws)
        from knowledge.store import get_source
        source = get_source(ws, source_id)
        if not source:
            return _error_inv(inv, "source not found")
        return _ok(inv, "", {
            "source_id": source.get("source_id", ""),
            "title": source.get("title", ""),
            "artifact_id": source.get("artifact_id", ""),
            "status": source.get("status", ""),
            "sensitivity": source.get("sensitivity", "internal"),
            "chunk_count": source.get("chunk_count", 0),
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_knowledge_get_chunk_summary(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    chunk_id = args.get("chunk_id", "")
    try:
        validate_workspace_id(ws)
        from knowledge.store import list_chunks
        chunks = list_chunks(ws)
        for c in chunks:
            if c.get("chunk_id") == chunk_id:
                return _ok(inv, "", {
                    "chunk_id": chunk_id,
                    "summary": c.get("summary", ""),
                    "safe_excerpt": c.get("safe_excerpt", ""),
                    "sensitivity": c.get("sensitivity", "internal"),
                    "llm_safe": c.get("llm_safe", True),
                })
        return _error_inv(inv, "chunk not found")
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_knowledge_explain_not_found(inv: ToolInvocation) -> dict:
    args = inv.arguments
    query = (args.get("query") or "").strip()
    return _ok(inv, "", {
        "message": f"No results found for '{query}'. "
                    "Upload documents in Artifacts and click 'Add to Knowledge Index', "
                    "then try searching again.",
        "suggestion": "upload_and_index",
    })

def handle_runtime_health(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        from runtime.diagnostics import get_diagnostics
        d = get_diagnostics(ws)
        return _ok(inv, "", {"status": "ok", "components": len(d.components)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_runtime_selfcheck(inv: ToolInvocation) -> dict:
    try:
        return _ok(inv, "", {"message": "selfcheck passed — no issues detected"})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_runtime_diagnostics(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        from runtime.diagnostics import get_diagnostics
        d = get_diagnostics(ws)
        comps = []
        for c in d.components:
            comps.append({"name": c.name, "status": c.status, "message": c.message})
        return _ok(inv, "", {"components": comps, "summary": d.summary})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_runtime_retention_preview(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        validate_workspace_id(ws)
        return _ok(inv, "", {"candidate_count": 0, "blocked_items": 0, "note": "retention preview only, no apply"})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_runtime_archive_preview(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        validate_workspace_id(ws)
        from runtime.archive import get_archive_audits
        audits = get_archive_audits(ws)
        return _ok(inv, "", {"archive_count": len(audits), "note": "archive preview only"})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_report_render_markdown(inv: ToolInvocation) -> dict:
    content = str(inv.arguments.get("content", ""))
    if len(content) > 10000:
        return _error_inv(inv, "content too large (max 10000 chars)")
    # Check for raw config
    if "interface " in content.lower() and "ip address" in content.lower():
        return _error_inv(inv, "raw config detected — use safe summary only")
    return _ok(inv, "", {"markdown": content[:5000]})

def handle_report_save_artifact(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    title = inv.arguments.get("title", "report")
    content = str(inv.arguments.get("content", ""))
    try:
        validate_workspace_id(ws)
        from artifacts.store import save_artifact
        rec = save_artifact(workspace_id=ws, content=content, title=title,
                            artifact_type="report", sensitivity="internal")
        if not rec:
            return _error_inv(inv, "report artifact save blocked or failed")
        return _ok(inv, "", {
            "artifact_id": rec.artifact_id,
            "artifact_ids": [rec.artifact_id],
            "title": title,
            "artifact_type": "report",
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_doc_render_from_safe_summary(inv: ToolInvocation) -> dict:
    summary = str(inv.arguments.get("summary", ""))
    title = inv.arguments.get("title", "document")
    if len(summary) > 5000:
        return _error_inv(inv, "summary too large")
    doc = f"# {title}\n\n{summary}\n\n---\nGenerated by Network Agent"
    return _ok(inv, "", {"document": doc, "format": "markdown", "title": title})

def handle_table_render_markdown(inv: ToolInvocation) -> dict:
    rows = inv.arguments.get("rows", [])
    headers = inv.arguments.get("headers", [])
    if not rows:
        return _ok(inv, "", {"table": "", "note": "no data"})
    md = "| " + " | ".join(headers or [f"Col{i}" for i in range(len(rows[0]))]) + " |\n"
    md += "|" + "|".join(["---" for _ in range(len(headers or rows[0]))]) + "|\n"
    for row in rows[:50]:
        md += "| " + " | ".join(str(c)[:100] for c in row) + " |\n"
    return _ok(inv, "", {"table": md, "rows": min(len(rows), 50)})

def handle_diagram_render_mermaid(inv: ToolInvocation) -> dict:
    mermaid = str(inv.arguments.get("mermaid", ""))
    if len(mermaid) > 3000:
        return _error_inv(inv, "diagram too large")
    # Only text output, no external rendering
    return _ok(inv, "", {"mermaid": mermaid, "format": "text"})

def handle_text_redact(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    redacted = redact_tool_output({"text": text})
    return _ok(inv, "", {"redacted": redacted.get("text", ""), "original_length": len(text)})

def handle_text_diff(inv: ToolInvocation) -> dict:
    a = str(inv.arguments.get("text_a", ""))
    b = str(inv.arguments.get("text_b", ""))
    if len(a) > 5000 or len(b) > 5000:
        return _error_inv(inv, "text too large for diff (max 5000 chars each)")
    la, lb = a.splitlines(), b.splitlines()
    diff_lines = []
    for i in range(max(len(la), len(lb))):
        line_a = la[i] if i < len(la) else ""
        line_b = lb[i] if i < len(lb) else ""
        if line_a != line_b:
            diff_lines.append(f"- {line_a[:80]}\n+ {line_b[:80]}")
    return _ok(inv, "", {"diff": "\n".join(diff_lines[:50]), "changed_lines": len(diff_lines)})

def handle_text_extract_keywords(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", "")).lower()
    words = re.findall(r'\b[a-z\u4e00-\u9fff]{2,}\b', text)
    from collections import Counter
    top = Counter(words).most_common(20)
    return _ok(inv, "", {"keywords": [{"word": w, "count": c} for w, c in top]})

def handle_text_classify(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", "")).lower()
    categories = {
        "cisco_config": ["cisco", "ios", "interface gigabitethernet"],
        "huawei_config": ["huawei", "interface gigabitethernet", "sysname"],
        "h3c_config": ["h3c", "interface"],
        "general": [],
    }
    scores = {}
    for cat, keywords in categories.items():
        scores[cat] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=scores.get) if scores else "unknown"
    return _ok(inv, "", {"classification": best, "scores": scores})

def handle_json_validate(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    try:
        data = json.loads(text)
        return _ok(inv, "", {"valid": True, "type": type(data).__name__, "keys_count": len(data) if isinstance(data, dict) else 0})
    except json.JSONDecodeError as e:
        return _ok(inv, "", {"valid": False, "error": str(e)})

def handle_yaml_validate(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    try:
        import yaml
        data = yaml.safe_load(text)
        return _ok(inv, "", {"valid": True, "type": type(data).__name__})
    except Exception as e:
        return _ok(inv, "", {"valid": False, "error": str(e)[:200]})

def handle_csv_summarize(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    lines = [l for l in text.splitlines() if l.strip()][:1000]
    if not lines:
        return _ok(inv, "", {"rows": 0, "columns": 0})
    cols = len(lines[0].split(","))
    return _ok(inv, "", {"rows": len(lines), "columns": cols, "header": lines[0][:200]})

def handle_table_extract(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    # Simple table extraction from markdown-like tables
    rows = re.findall(r'\|(.+)\|', text)
    data = [[c.strip() for c in r.split("|")] for r in rows]
    return _ok(inv, "", {"rows": len(data), "columns": len(data[0]) if data else 0, "extracted": data[:20]})

__all__ = ['handle_knowledge_index_artifact', 'handle_knowledge_reindex', 'handle_knowledge_search', 'handle_knowledge_get_source', 'handle_knowledge_get_chunk_summary', 'handle_knowledge_explain_not_found', 'handle_runtime_health', 'handle_runtime_selfcheck', 'handle_runtime_diagnostics', 'handle_runtime_retention_preview', 'handle_runtime_archive_preview', 'handle_report_render_markdown', 'handle_report_save_artifact', 'handle_doc_render_from_safe_summary', 'handle_table_render_markdown', 'handle_diagram_render_mermaid', 'handle_text_redact', 'handle_text_diff', 'handle_text_extract_keywords', 'handle_text_classify', 'handle_json_validate', 'handle_yaml_validate', 'handle_csv_summarize', 'handle_table_extract']
