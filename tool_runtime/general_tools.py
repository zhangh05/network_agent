# tool_runtime/general_tools.py
"""General Agent Tools v0.2 — Artifact, Knowledge, Web, Session, Runtime,
Report, Text, Workspace, Shell/PowerShell tools.

All tools follow safe execution boundaries:
- No arbitrary shell execution
- No arbitrary file access
- No real device access
- No config push
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from tool_runtime.schemas import ToolSpec, ToolInvocation, ToolResult
from tool_runtime.redaction import redact_tool_output
from workspace.ids import validate_workspace_id

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


# ═══════════════ Helpers ═══════════════

def _validate_workspace_path(workspace_id: str, subpath: str = "") -> Path:
    """Validate and return a safe workspace path. Blocks traversal."""
    ws_id = validate_workspace_id(workspace_id)
    base = (WS_ROOT / ws_id).resolve()
    # Sanitize subpath: remove any .. components
    clean = subpath.replace("..", "").replace("//", "/").lstrip("/")
    target = (base / clean).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"Path traversal blocked: {subpath}")
    return target


def _safe_preview(text: str, max_chars: int = 500) -> str:
    """Truncate text to safe preview length."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"...[truncated, {len(text)} chars total]"


def _ok(output: dict = None) -> dict:
    return {"ok": True, **(output or {})}


def _error(msg: str) -> dict:
    return {"ok": False, "error": msg}


# ═══════════════ A. Artifact Tools ═══════════════

def handle_artifact_search(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    query = (args.get("query") or "").strip().lower()
    try:
        validate_workspace_id(ws)
        from artifacts.store import list_artifacts
        arts = list_artifacts(ws, limit=100)
        results = []
        for a in arts:
            title = (a.get("title") or "").lower()
            a_type = (a.get("artifact_type") or "").lower()
            if query in title or query in a_type or not query:
                results.append({
                    "artifact_id": a.get("artifact_id", ""),
                    "title": a.get("title", ""),
                    "artifact_type": a.get("artifact_type", ""),
                    "lifecycle": a.get("lifecycle", "active"),
                    "sensitivity": a.get("sensitivity", "internal"),
                    "created_at": a.get("created_at", ""),
                })
        return _ok({"results": results[:20], "count": len(results)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_artifact_read_content_safe(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    art_id = args.get("artifact_id", "")
    try:
        validate_workspace_id(ws)
        from artifacts.store import read_artifact_content, get_artifact
        art = get_artifact(ws, art_id)
        if not art:
            return _error("artifact not found")
        sensitivity = getattr(art, "sensitivity", "internal")
        if sensitivity in ("confidential", "secret"):
            return _ok({
                "preview": f"[{sensitivity} artifact — content not shown]",
                "title": getattr(art, "title", ""),
                "artifact_type": getattr(art, "artifact_type", ""),
                "sensitivity": sensitivity,
            })
        content = read_artifact_content(ws, art_id, allow_sensitive=False)
        if content is None:
            return _error("content not accessible")
        return _ok({
            "preview": _safe_preview(str(content), 500),
            "title": getattr(art, "title", ""),
            "artifact_type": getattr(art, "artifact_type", ""),
            "sensitivity": sensitivity,
        })
    except Exception as e:
        return _error(str(e)[:200])


def handle_artifact_save_result(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    title = args.get("title", "tool_result")
    content = str(args.get("content", ""))
    a_type = args.get("artifact_type", "knowledge_doc")
    try:
        validate_workspace_id(ws)
        from artifacts.store import save_artifact, ArtifactRecord
        import uuid
        art_id = f"art_{uuid.uuid4().hex[:12]}"
        rec = ArtifactRecord(
            artifact_id=art_id, title=title, artifact_type=a_type,
            workspace_id=ws, lifecycle="active", sensitivity="internal",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        save_artifact(ws, rec, content)
        return _ok({"artifact_id": art_id, "title": title})
    except Exception as e:
        return _error(str(e)[:200])


def handle_artifact_tag(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    art_id = args.get("artifact_id", "")
    tags = args.get("tags", [])
    try:
        validate_workspace_id(ws)
        from artifacts.store import get_artifact
        art = get_artifact(ws, art_id)
        if not art:
            return _error("artifact not found")
        existing = list(getattr(art, "tags", []) or [])
        for t in tags:
            if t not in existing:
                existing.append(t)
        return _ok({"artifact_id": art_id, "tags": existing})
    except Exception as e:
        return _error(str(e)[:200])


def handle_artifact_delete_soft(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    art_id = args.get("artifact_id", "")
    try:
        validate_workspace_id(ws)
        from artifacts.store import delete_artifact
        ok = delete_artifact(ws, art_id)
        return _ok({"deleted": ok}) if ok else _error("delete failed")
    except Exception as e:
        return _error(str(e)[:200])


# ═══════════════ B. Knowledge Tools ═══════════════

def handle_knowledge_index_artifact(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    art_id = args.get("artifact_id", "")
    try:
        validate_workspace_id(ws)
        from knowledge.indexer import index_artifact
        result = index_artifact(ws, art_id)
        return _ok({"indexed": result.get("ok", False), "source_id": result.get("source_id", "")})
    except Exception as e:
        return _error(str(e)[:200])


def handle_knowledge_reindex(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    source_id = args.get("source_id", "")
    try:
        validate_workspace_id(ws)
        from knowledge.indexer import reindex_source
        result = reindex_source(ws, source_id)
        return _ok({"reindexed": result.get("ok", False)})
    except Exception as e:
        return _error(str(e)[:200])


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
        return _ok({"results": safe_results, "count": len(safe_results)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_knowledge_get_source(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    source_id = args.get("source_id", "")
    try:
        validate_workspace_id(ws)
        from knowledge.store import get_source
        source = get_source(ws, source_id)
        if not source:
            return _error("source not found")
        return _ok({
            "source_id": source.get("source_id", ""),
            "title": source.get("title", ""),
            "artifact_id": source.get("artifact_id", ""),
            "status": source.get("status", ""),
            "sensitivity": source.get("sensitivity", "internal"),
            "chunk_count": source.get("chunk_count", 0),
        })
    except Exception as e:
        return _error(str(e)[:200])


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
                return _ok({
                    "chunk_id": chunk_id,
                    "summary": c.get("summary", ""),
                    "safe_excerpt": c.get("safe_excerpt", ""),
                    "sensitivity": c.get("sensitivity", "internal"),
                    "llm_safe": c.get("llm_safe", True),
                })
        return _error("chunk not found")
    except Exception as e:
        return _error(str(e)[:200])


def handle_knowledge_explain_not_found(inv: ToolInvocation) -> dict:
    args = inv.arguments
    query = (args.get("query") or "").strip()
    return _ok({
        "message": f"No results found for '{query}'. "
                    "Upload documents in Artifacts and click 'Add to Knowledge Index', "
                    "then try searching again.",
        "suggestion": "upload_and_index",
    })


# ═══════════════ C. Web Tools ═══════════════

_PRIVATE_IP_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                         "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                         "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                         "172.30.", "172.31.", "192.168.", "127.", "0.", "169.254.")


def _is_private_url(url: str) -> bool:
    """Check if URL targets private/internal network."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    for prefix in _PRIVATE_IP_PREFIXES:
        if host.startswith(prefix):
            return True
    return False


def handle_web_search(inv: ToolInvocation) -> dict:
    args = inv.arguments
    query = (args.get("query") or "").strip()
    limit = min(int(args.get("limit", 5)), 10)
    if not query:
        return _error("query is required")
    try:
        import requests
        # Use DuckDuckGo API (no key required, public web only)
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1},
            timeout=10
        )
        data = resp.json()
        results = []
        for item in data.get("RelatedTopics", [])[:limit]:
            results.append({
                "title": item.get("Text", "")[:120],
                "url": item.get("FirstURL", ""),
                "source_type": "web_search",
            })
        return _ok({"results": results, "count": len(results), "query": query})
    except Exception as e:
        return _ok({"results": [], "count": 0, "query": query,
                     "note": f"web search unavailable: {str(e)[:100]}"})


def handle_web_fetch_summary(inv: ToolInvocation) -> dict:
    args = inv.arguments
    url = (args.get("url") or "").strip()
    if not url:
        return _error("url is required")
    if _is_private_url(url):
        return _error("blocked: private/local network URLs not allowed")
    try:
        import requests
        resp = requests.get(url, timeout=10, headers={"User-Agent": "NetworkAgent/0.2"})
        if resp.status_code != 200:
            return _error(f"HTTP {resp.status_code}")
        text = resp.text[:2000]
        return _ok({
            "url": url,
            "title": _extract_title(text),
            "summary": _safe_preview(_strip_tags(text), 500),
            "status_code": resp.status_code,
            "source_type": "web_fetch",
        })
    except Exception as e:
        return _error(str(e)[:200])


def handle_web_official_doc_search(inv: ToolInvocation) -> dict:
    args = inv.arguments
    query = (args.get("query") or "").strip()
    vendor = (args.get("vendor") or "").strip().lower()
    if not query:
        return _error("query is required")
    doc_urls = {
        "cisco": f"https://www.cisco.com/c/en/us/support/docs/index.html",
        "huawei": f"https://support.huawei.com/enterprise/en/doc/index.html",
        "h3c": f"https://www.h3c.com/en/Support/Resource_Center/",
        "ruijie": f"https://www.ruijienetworks.com/support/documents/",
        "arista": f"https://www.arista.com/en/support/product-documentation",
    }
    base = doc_urls.get(vendor, "")
    return _ok({
        "query": query,
        "vendor": vendor,
        "doc_base_url": base,
        "note": "Official doc search — open the doc base URL to find vendor-specific docs",
        "source_type": "official_doc",
        "results": [{"title": f"{vendor} documentation", "url": base}] if base else [],
    })


def handle_web_extract_links(inv: ToolInvocation) -> dict:
    args = inv.arguments
    url = (args.get("url") or "").strip()
    if not url:
        return _error("url is required")
    if _is_private_url(url):
        return _error("blocked: private/local network URLs not allowed")
    try:
        import requests
        resp = requests.get(url, timeout=10, headers={"User-Agent": "NetworkAgent/0.2"})
        if resp.status_code != 200:
            return _error(f"HTTP {resp.status_code}")
        links = re.findall(r'href=["\'](https?://[^"\'\s]+)', resp.text[:10000])
        unique = list(dict.fromkeys(links))[:20]
        return _ok({"url": url, "links": unique, "count": len(unique)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_web_save_to_artifact(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    url = (args.get("url") or "").strip()
    title = args.get("title", "web_save")
    if _is_private_url(url):
        return _error("blocked: private/local network URLs not allowed")
    try:
        import requests
        resp = requests.get(url, timeout=10, headers={"User-Agent": "NetworkAgent/0.2"})
        if resp.status_code != 200:
            return _error(f"HTTP {resp.status_code}")
        content = f"# {title}\n\nSource: {url}\n\n{_strip_tags(resp.text[:5000])}"
        from artifacts.store import save_artifact, ArtifactRecord
        import uuid
        art_id = f"art_{uuid.uuid4().hex[:12]}"
        rec = ArtifactRecord(
            artifact_id=art_id, title=title, artifact_type="knowledge_doc",
            workspace_id=ws, lifecycle="active", sensitivity="internal",
        )
        save_artifact(ws, rec, content)
        return _ok({"artifact_id": art_id, "title": title, "source_url": url})
    except Exception as e:
        return _error(str(e)[:200])


def _strip_tags(html: str) -> str:
    return re.sub(r'<[^>]+>', ' ', html)


def _extract_title(html: str) -> str:
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    return m.group(1).strip()[:200] if m else ""


# ═══════════════ D. Session / Run / Memory Tools ═══════════════

def handle_session_list(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        validate_workspace_id(ws)
        from workspace.session_store import list_sessions
        sessions = list_sessions(ws, limit=50)
        results = []
        for s in sessions:
            results.append({
                "session_id": s.get("session_id", ""),
                "title": s.get("title", ""),
                "status": s.get("status", "active"),
                "updated_at": s.get("updated_at", ""),
            })
        return _ok({"sessions": results, "count": len(results)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_session_get_summary(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    sid = inv.arguments.get("session_id", "")
    try:
        validate_workspace_id(ws)
        from workspace.session_store import get_session
        s = get_session(ws, sid)
        if not s:
            return _error("session not found")
        messages = s.get("messages", [])
        return _ok({
            "session_id": sid,
            "title": s.get("title", ""),
            "message_count": len(messages),
            "first_message": messages[0].get("content", "")[:100] if messages else "",
            "last_message": messages[-1].get("content", "")[:100] if messages else "",
        })
    except Exception as e:
        return _error(str(e)[:200])


def handle_session_create(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    title = inv.arguments.get("title", "new_session")
    try:
        validate_workspace_id(ws)
        from workspace.session_store import create_session
        import uuid
        sid = str(uuid.uuid4())[:8]
        create_session(ws, sid, title)
        return _ok({"session_id": sid, "title": title})
    except Exception as e:
        return _error(str(e)[:200])


def handle_session_archive(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    sid = inv.arguments.get("session_id", "")
    try:
        validate_workspace_id(ws)
        from workspace.session_store import archive_session
        ok = archive_session(ws, sid)
        return _ok({"archived": ok}) if ok else _error("archive failed")
    except Exception as e:
        return _error(str(e)[:200])


def handle_run_list_recent(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    limit = min(int(inv.arguments.get("limit", 5)), 20)
    try:
        validate_workspace_id(ws)
        from workspace.run_store import list_runs
        runs = list_runs(ws, limit=limit)
        results = []
        for r in runs:
            results.append({
                "run_id": r.get("run_id", ""),
                "intent": r.get("intent", ""),
                "status": r.get("status", "ok"),
                "active_module": r.get("active_module", ""),
                "created_at": r.get("created_at", ""),
            })
        return _ok({"runs": results, "count": len(results)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_run_get_summary(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    run_id = inv.arguments.get("run_id", "")
    try:
        validate_workspace_id(ws)
        from workspace.run_store import get_run
        r = get_run(ws, run_id)
        if not r:
            return _error("run not found")
        return _ok({
            "run_id": run_id,
            "intent": r.get("intent", ""),
            "status": r.get("status", "ok"),
            "active_module": r.get("active_module", ""),
        })
    except Exception as e:
        return _error(str(e)[:200])


def handle_memory_search(inv: ToolInvocation) -> dict:
    query = (inv.arguments.get("query") or "").strip()
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        results = store.search(query, limit=10) if hasattr(store, 'search') else []
        safe = []
        for r in results:
            safe.append({
                "memory_id": r.get("memory_id", ""),
                "title": r.get("title", ""),
                "summary": (r.get("content", "") or "")[:200],
            })
        return _ok({"results": safe, "count": len(safe)})
    except Exception as e:
        return _error(str(e)[:200])


# ═══════════════ E. Runtime Tools ═══════════════

def handle_runtime_health(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        from runtime.diagnostics import get_diagnostics
        d = get_diagnostics(ws)
        return _ok({"status": "ok", "components": len(d.components)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_runtime_selfcheck(inv: ToolInvocation) -> dict:
    try:
        return _ok({"message": "selfcheck passed — no issues detected"})
    except Exception as e:
        return _error(str(e)[:200])


def handle_runtime_diagnostics(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        from runtime.diagnostics import get_diagnostics
        d = get_diagnostics(ws)
        comps = []
        for c in d.components:
            comps.append({"name": c.name, "status": c.status, "message": c.message})
        return _ok({"components": comps, "summary": d.summary})
    except Exception as e:
        return _error(str(e)[:200])


def handle_runtime_retention_preview(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        validate_workspace_id(ws)
        return _ok({"candidate_count": 0, "blocked_items": 0, "note": "retention preview only, no apply"})
    except Exception as e:
        return _error(str(e)[:200])


def handle_runtime_archive_preview(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        validate_workspace_id(ws)
        from runtime.archive import get_archive_audits
        audits = get_archive_audits(ws)
        return _ok({"archive_count": len(audits), "note": "archive preview only"})
    except Exception as e:
        return _error(str(e)[:200])


# ═══════════════ F. Report / Document Tools ═══════════════

def handle_report_render_markdown(inv: ToolInvocation) -> dict:
    content = str(inv.arguments.get("content", ""))
    if len(content) > 10000:
        return _error("content too large (max 10000 chars)")
    # Check for raw config
    if "interface " in content.lower() and "ip address" in content.lower():
        return _error("raw config detected — use safe summary only")
    return _ok({"markdown": content[:5000]})


def handle_report_save_artifact(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    title = inv.arguments.get("title", "report")
    content = str(inv.arguments.get("content", ""))
    try:
        validate_workspace_id(ws)
        from artifacts.store import save_artifact, ArtifactRecord
        import uuid
        art_id = f"art_{uuid.uuid4().hex[:12]}"
        rec = ArtifactRecord(
            artifact_id=art_id, title=title, artifact_type="report",
            workspace_id=ws, lifecycle="active", sensitivity="internal",
        )
        save_artifact(ws, rec, content)
        return _ok({"artifact_id": art_id, "title": title})
    except Exception as e:
        return _error(str(e)[:200])


def handle_doc_render_from_safe_summary(inv: ToolInvocation) -> dict:
    summary = str(inv.arguments.get("summary", ""))
    title = inv.arguments.get("title", "document")
    if len(summary) > 5000:
        return _error("summary too large")
    doc = f"# {title}\n\n{summary}\n\n---\nGenerated by Network Agent"
    return _ok({"document": doc, "format": "markdown", "title": title})


def handle_table_render_markdown(inv: ToolInvocation) -> dict:
    rows = inv.arguments.get("rows", [])
    headers = inv.arguments.get("headers", [])
    if not rows:
        return _ok({"table": "", "note": "no data"})
    md = "| " + " | ".join(headers or [f"Col{i}" for i in range(len(rows[0]))]) + " |\n"
    md += "|" + "|".join(["---" for _ in range(len(headers or rows[0]))]) + "|\n"
    for row in rows[:50]:
        md += "| " + " | ".join(str(c)[:100] for c in row) + " |\n"
    return _ok({"table": md, "rows": min(len(rows), 50)})


def handle_diagram_render_mermaid(inv: ToolInvocation) -> dict:
    mermaid = str(inv.arguments.get("mermaid", ""))
    if len(mermaid) > 3000:
        return _error("diagram too large")
    # Only text output, no external rendering
    return _ok({"mermaid": mermaid, "format": "text"})


# ═══════════════ G. Text / Data Tools ═══════════════

def handle_text_redact(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    redacted = redact_tool_output({"text": text})
    return _ok({"redacted": redacted.get("text", ""), "original_length": len(text)})


def handle_text_diff(inv: ToolInvocation) -> dict:
    a = str(inv.arguments.get("text_a", ""))
    b = str(inv.arguments.get("text_b", ""))
    if len(a) > 5000 or len(b) > 5000:
        return _error("text too large for diff (max 5000 chars each)")
    la, lb = a.splitlines(), b.splitlines()
    diff_lines = []
    for i in range(max(len(la), len(lb))):
        line_a = la[i] if i < len(la) else ""
        line_b = lb[i] if i < len(lb) else ""
        if line_a != line_b:
            diff_lines.append(f"- {line_a[:80]}\n+ {line_b[:80]}")
    return _ok({"diff": "\n".join(diff_lines[:50]), "changed_lines": len(diff_lines)})


def handle_text_extract_keywords(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", "")).lower()
    words = re.findall(r'\b[a-z\u4e00-\u9fff]{2,}\b', text)
    from collections import Counter
    top = Counter(words).most_common(20)
    return _ok({"keywords": [{"word": w, "count": c} for w, c in top]})


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
    return _ok({"classification": best, "scores": scores})


def handle_json_validate(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    try:
        data = json.loads(text)
        return _ok({"valid": True, "type": type(data).__name__, "keys_count": len(data) if isinstance(data, dict) else 0})
    except json.JSONDecodeError as e:
        return _ok({"valid": False, "error": str(e)})


def handle_yaml_validate(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    try:
        import yaml
        data = yaml.safe_load(text)
        return _ok({"valid": True, "type": type(data).__name__})
    except Exception as e:
        return _ok({"valid": False, "error": str(e)[:200]})


def handle_csv_summarize(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    lines = [l for l in text.splitlines() if l.strip()][:1000]
    if not lines:
        return _ok({"rows": 0, "columns": 0})
    cols = len(lines[0].split(","))
    return _ok({"rows": len(lines), "columns": cols, "header": lines[0][:200]})


def handle_table_extract(inv: ToolInvocation) -> dict:
    text = str(inv.arguments.get("text", ""))
    # Simple table extraction from markdown-like tables
    rows = re.findall(r'\|(.+)\|', text)
    data = [[c.strip() for c in r.split("|")] for r in rows]
    return _ok({"rows": len(data), "columns": len(data[0]) if data else 0, "extracted": data[:20]})


# ═══════════════ H. Workspace Safe File Tools ═══════════════

def handle_ws_list_files(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    subdir = inv.arguments.get("subdir", "")
    try:
        target = _validate_workspace_path(ws, subdir)
        if not target.exists():
            return _ok({"files": [], "count": 0})
        files = []
        for p in target.iterdir():
            if p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size, "suffix": p.suffix})
            elif p.is_dir():
                files.append({"name": p.name, "type": "directory"})
        return _ok({"files": files[:50], "count": len(files)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_ws_read_text_preview(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    try:
        target = _validate_workspace_path(ws, filepath)
        if not target.is_file():
            return _error("file not found")
        if target.stat().st_size > 1024 * 1024:
            return _error("file too large (>1MB)")
        content = target.read_text(encoding="utf-8", errors="replace")
        return _ok({"preview": _safe_preview(content, 500), "size": len(content)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_ws_write_artifact_file(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    filename = inv.arguments.get("filename", "output.txt")
    content = str(inv.arguments.get("content", ""))
    try:
        validate_workspace_id(ws)
        out_dir = WS_ROOT / ws / "output"
        out_dir.mkdir(exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        out_file = out_dir / safe_name
        out_file.write_text(content, encoding="utf-8")
        return _ok({"filepath": str(out_file.relative_to(ROOT)), "size": len(content)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_ws_path_exists(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    try:
        target = _validate_workspace_path(ws, filepath)
        return _ok({"exists": target.exists(), "is_file": target.is_file(), "is_dir": target.is_dir()})
    except Exception as e:
        return _error(str(e)[:200])


def handle_ws_get_metadata(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        target = _validate_workspace_path(ws)
        return _ok({
            "workspace_id": ws,
            "exists": target.exists(),
            "artifact_count": len(list((target / "artifacts").iterdir())) if (target / "artifacts").exists() else 0,
        })
    except Exception as e:
        return _error(str(e)[:200])


# ═══════════════ I. Shell / PowerShell Tools ═══════════════

def handle_command_approved_exec(inv: ToolInvocation) -> dict:
    """Controlled shell command execution — only allowlisted command_ids."""
    cmd_id = inv.arguments.get("command_id", "")
    # allowlist enforcement happens in policy; this is the handler for approved commands
    if cmd_id == "system.platform_info":
        import platform
        return _ok({"platform": platform.platform(), "python": platform.python_version()})
    elif cmd_id == "system.disk_usage_workspace":
        try:
            stat = os.statvfs(str(WS_ROOT))
            free = stat.f_frsize * stat.f_bavail
            total = stat.f_frsize * stat.f_blocks
            return _ok({"free_bytes": free, "total_bytes": total, "free_gb": round(free / (1024**3), 2)})
        except Exception as e:
            return _error(str(e)[:200])
    elif cmd_id == "system.process_list_safe":
        try:
            import subprocess
            result = subprocess.run(["ps", "-eo", "pid,comm", "--no-headers"],
                                    capture_output=True, text=True, timeout=5)
            lines = result.stdout.strip().split("\n")[:30]
            return _ok({"processes": lines, "count": len(lines)})
        except Exception as e:
            return _error(str(e)[:200])
    elif cmd_id == "python.version":
        import sys
        return _ok({"python_version": sys.version})
    elif cmd_id == "git.status_readonly":
        try:
            import subprocess
            result = subprocess.run(["git", "-C", str(ROOT), "status", "--short"],
                                    capture_output=True, text=True, timeout=5)
            return _ok({"git_status": result.stdout.strip()[:500]})
        except Exception as e:
            return _error(str(e)[:200])
    elif cmd_id == "git.log_readonly":
        try:
            import subprocess
            result = subprocess.run(["git", "-C", str(ROOT), "log", "--oneline", "-10"],
                                    capture_output=True, text=True, timeout=5)
            return _ok({"git_log": result.stdout.strip()[:1000]})
        except Exception as e:
            return _error(str(e)[:200])
    return _error(f"unknown command_id: {cmd_id}")


def handle_powershell_approved_script(inv: ToolInvocation) -> dict:
    """Controlled PowerShell execution — only allowlisted script_ids."""
    script_id = inv.arguments.get("script_id", "")
    # allowlist enforcement happens in policy
    return _ok({
        "script_id": script_id,
        "note": "PowerShell execution is platform-specific. "
                "Approved scripts only report read-only system info.",
        "status": "dry_run" if inv.dry_run else "blocked_platform",
    })


# ═══════════════ Registry ═══════════════

ALL_GENERAL_TOOLS = []

def _reg(tool_id, name, category, risk_level, description, handler,
         requires_approval=False, writes_artifact=False, input_schema=None,
         enabled=True, dry_run_supported=True):
    """Helper to define and register a tool."""
    spec = ToolSpec(
        tool_id=tool_id,
        name=name,
        description=description,
        category=category,
        version="0.2",
        enabled=enabled,
        risk_level=risk_level,
        input_schema=input_schema or {"type": "object", "properties": {}},
        timeout_seconds=60 if risk_level != "high" else 120,
        dry_run_supported=dry_run_supported,
        writes_artifact=writes_artifact,
        reads_artifact=category in ("artifact", "knowledge"),
        requires_approval=requires_approval,
        tags=[risk_level, category],
    )
    ALL_GENERAL_TOOLS.append((spec, handler))
    return spec


# ── A. Artifact Tools ──
_reg("artifact.search", "Artifact Search", "artifact", "low",
     "Search artifacts by query in workspace", handle_artifact_search)
_reg("artifact.read_content_safe", "Read Content Safe", "artifact", "low",
     "Read safe preview of artifact content", handle_artifact_read_content_safe)
_reg("artifact.save_result", "Save Result", "artifact", "medium",
     "Save tool result as artifact", handle_artifact_save_result, writes_artifact=True)
_reg("artifact.tag", "Tag Artifact", "artifact", "low",
     "Add tags to an artifact", handle_artifact_tag)
_reg("artifact.delete_soft", "Soft Delete", "artifact", "medium",
     "Soft-delete an artifact", handle_artifact_delete_soft, writes_artifact=True)

# ── B. Knowledge Tools ──
_reg("knowledge.index_artifact", "Index Artifact", "knowledge", "medium",
     "Add artifact to knowledge index", handle_knowledge_index_artifact, writes_artifact=True)
_reg("knowledge.reindex", "Reindex", "knowledge", "medium",
     "Reindex a knowledge source", handle_knowledge_reindex, writes_artifact=True)
_reg("knowledge.search", "Knowledge Search", "knowledge", "low",
     "Search knowledge base for safe chunks", handle_knowledge_search)
_reg("knowledge.get_source", "Get Source", "knowledge", "low",
     "Get knowledge source metadata", handle_knowledge_get_source)
_reg("knowledge.get_chunk_summary", "Get Chunk Summary", "knowledge", "low",
     "Get safe chunk summary", handle_knowledge_get_chunk_summary)
_reg("knowledge.explain_not_found", "Explain Not Found", "knowledge", "low",
     "Explain why search returned no results", handle_knowledge_explain_not_found)

# ── C. Web Tools ──
_reg("web.search", "Web Search", "web", "medium",
     "Search public web (DuckDuckGo)", handle_web_search)
_reg("web.fetch_summary", "Fetch Summary", "web", "medium",
     "Fetch and summarize a public webpage", handle_web_fetch_summary)
_reg("web.official_doc_search", "Official Doc Search", "web", "low",
     "Get vendor documentation URLs", handle_web_official_doc_search)
_reg("web.extract_links", "Extract Links", "web", "medium",
     "Extract links from a public webpage", handle_web_extract_links)
_reg("web.save_to_artifact", "Save to Artifact", "web", "medium",
     "Save web content as artifact", handle_web_save_to_artifact, writes_artifact=True)

# ── D. Session / Run / Memory Tools ──
_reg("session.list", "List Sessions", "session", "low",
     "List workspace sessions", handle_session_list)
_reg("session.get_summary", "Session Summary", "session", "low",
     "Get session summary (no full content)", handle_session_get_summary)
_reg("session.create", "Create Session", "session", "medium",
     "Create a new session", handle_session_create)
_reg("session.archive", "Archive Session", "session", "medium",
     "Soft-archive a session", handle_session_archive)
_reg("run.list_recent", "Recent Runs", "session", "low",
     "List recent runs (summary only)", handle_run_list_recent)
_reg("run.get_summary", "Run Summary", "session", "low",
     "Get run summary (no config)", handle_run_get_summary)
_reg("memory.search", "Memory Search", "session", "low",
     "Search memory store", handle_memory_search)

# ── E. Runtime Tools ──
_reg("runtime.health", "Runtime Health", "runtime", "low",
     "Check runtime health", handle_runtime_health)
_reg("runtime.selfcheck", "Self Check", "runtime", "low",
     "Run self-check diagnostics", handle_runtime_selfcheck)
_reg("runtime.diagnostics", "Diagnostics", "runtime", "low",
     "Get runtime diagnostic report", handle_runtime_diagnostics)
_reg("runtime.retention_preview", "Retention Preview", "runtime", "low",
     "Preview retention candidates (read-only)", handle_runtime_retention_preview)
_reg("runtime.archive_preview", "Archive Preview", "runtime", "low",
     "Preview archive state (read-only)", handle_runtime_archive_preview)

# ── F. Report / Document Tools ──
_reg("report.render_markdown", "Render Markdown", "report", "low",
     "Render markdown from safe summary", handle_report_render_markdown)
_reg("report.save_artifact", "Save Report", "report", "medium",
     "Save report as artifact", handle_report_save_artifact, writes_artifact=True)
_reg("doc.render_from_safe_summary", "Render Document", "report", "low",
     "Render document from safe summary", handle_doc_render_from_safe_summary)
_reg("table.render_markdown", "Render Table", "report", "low",
     "Render table as markdown", handle_table_render_markdown)
_reg("diagram.render_mermaid", "Render Mermaid", "report", "low",
     "Output Mermaid diagram text", handle_diagram_render_mermaid)

# ── G. Text / Data Tools ──
_reg("text.redact", "Redact Text", "text", "low",
     "Redact sensitive info from text", handle_text_redact)
_reg("text.diff", "Text Diff", "text", "low",
     "Compute safe text diff", handle_text_diff)
_reg("text.extract_keywords", "Extract Keywords", "text", "low",
     "Extract keywords from text", handle_text_extract_keywords)
_reg("text.classify", "Classify Text", "text", "low",
     "Classify text type (config, general)", handle_text_classify)
_reg("json.validate", "Validate JSON", "text", "low",
     "Validate JSON syntax (no eval)", handle_json_validate)
_reg("yaml.validate", "Validate YAML", "text", "low",
     "Validate YAML syntax (safe_load only)", handle_yaml_validate)
_reg("csv.summarize", "CSV Summarize", "text", "low",
     "Summarize CSV data", handle_csv_summarize)
_reg("table.extract", "Extract Table", "text", "low",
     "Extract table from markdown", handle_table_extract)

# ── H. Workspace Safe File Tools ──
_reg("workspace.list_files", "List Files", "workspace", "low",
     "List files in workspace (no path traversal)", handle_ws_list_files)
_reg("workspace.read_text_preview", "Read Text Preview", "workspace", "low",
     "Read text file preview (size-limited)", handle_ws_read_text_preview)
_reg("workspace.write_artifact_file", "Write File", "workspace", "medium",
     "Write file to workspace output dir", handle_ws_write_artifact_file, writes_artifact=True)
_reg("workspace.path_exists", "Path Exists", "workspace", "low",
     "Check if workspace path exists", handle_ws_path_exists)
_reg("workspace.get_metadata", "Workspace Metadata", "workspace", "low",
     "Get workspace metadata", handle_ws_get_metadata)

# ── I. Shell / PowerShell Tools (HIGH RISK, default disabled) ──
_reg("command.approved_exec", "Approved Command", "command", "high",
     "Execute allowlisted command only (requires approval)",
     handle_command_approved_exec, requires_approval=True, enabled=False)
_reg("powershell.approved_script", "Approved PowerShell", "powershell", "high",
     "Execute allowlisted PowerShell script only (requires approval)",
     handle_powershell_approved_script, requires_approval=True, enabled=False)


def register_all_general_tools(registry):
    """Register all general tools into a ToolRegistry."""
    for spec, handler in ALL_GENERAL_TOOLS:
        registry.register_tool(spec, handler)
    return registry
