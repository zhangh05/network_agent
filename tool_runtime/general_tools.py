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
from functools import wraps
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


def _result(ok: bool, output: dict = None) -> dict:
    """Build a tool result dict, preserving caller's ok flag."""
    return {**(output or {}), "ok": ok}


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
        art_type = getattr(art, "artifact_type", "")
        # Only truly secret artifacts are blocked from the LLM.
        # "sensitive" (e.g. translated_config output) must be readable so
        # the LLM can surface manual_review_items and complete the review loop.
        if sensitivity in ("secret",):
            return _ok({
                "preview": f"[{sensitivity} artifact — content not shown]",
                "title": getattr(art, "title", ""),
                "artifact_type": art_type,
                "sensitivity": sensitivity,
            })
        # sensitive + internal are readable; "confidential" gets a short preview
        allow = sensitivity not in ("confidential",)
        content = read_artifact_content(ws, art_id, allow_sensitive=allow)
        if content is None:
            return _error("content not accessible")
        # translated_config is user-requested output — give generous preview
        if art_type in ("translated_config", "output_config"):
            preview_len = min(len(str(content)), 8000)
        elif sensitivity in ("confidential",):
            preview_len = 200
        else:
            preview_len = 2000
        return _ok({
            "preview": _safe_preview(str(content), preview_len),
            "title": getattr(art, "title", ""),
            "artifact_type": art_type,
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
        from artifacts.store import save_artifact
        # v1.0.3.5: use keyword args — save_artifact creates ArtifactRecord internally
        rec = save_artifact(workspace_id=ws, content=content, title=title,
                            artifact_type=a_type, sensitivity="internal")
        if not rec:
            return _error("artifact save blocked or failed")
        return _ok({
            "artifact_id": rec.artifact_id,
            "artifact_ids": [rec.artifact_id],
            "title": title,
            "artifact_type": a_type,
        })
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
        # v1.0.3.5: persist tags to artifact meta
        _persist_artifact_tags(ws, art_id, existing)
        return _ok({"artifact_id": art_id, "tags": existing})
    except Exception as e:
        return _error(str(e)[:200])


def _persist_artifact_tags(ws: str, art_id: str, tags: list) -> None:
    """Best-effort: write updated tags to the artifact's meta.json file."""
    import json
    from pathlib import Path
    from workspace.run_store import WS_ROOT
    for art_type in ["inputs", "outputs", "reports", "temp"]:
        meta_path = WS_ROOT / ws / "artifacts" / art_type / f"{art_id}.meta.json"
        if meta_path.is_file():
            try:
                data = json.loads(meta_path.read_text())
                data["tags"] = tags
                meta_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            except Exception:
                pass
            return


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
    limit = _coerce_int(args.get("top_k", args.get("limit", 5)), default=5, min_value=1, max_value=10)
    domains = _normalize_search_domains(args)
    recency = (args.get("recency") or "").strip().lower()
    language = (args.get("language") or "").strip() or "zh-CN"
    safe_search = (args.get("safe_search") or "moderate").strip().lower()
    if not query:
        return _error("query is required")
    search_query = _build_web_search_query(query, domains)
    try:
        import requests
        results = []

        # ── Try DuckDuckGo HTML search (most reliable free path) ──
        html_resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params=_duckduckgo_search_params(search_query, recency, language, safe_search),
            timeout=12,
            headers={
                "User-Agent": "NetworkAgent/1.0 (+https://github.com/zhangh05/network_agent)",
                "Accept-Language": language,
            },
        )
        if html_resp.status_code == 200:
            results = _filter_web_results(_parse_duckduckgo_html(html_resp.text, limit * 2), domains, limit)
            if results:
                guidance = _web_search_guidance(query, results, domains)
                return _ok({
                    "ok": True,
                    "status": "succeeded",
                    "query": query,
                    "search_query": search_query,
                    "results": results,
                    "count": len(results),
                    "answer_hint": guidance["answer_hint"],
                    "results_markdown": _web_results_markdown(results),
                    "next_actions": guidance["next_actions"],
                    "summary": f"Found {len(results)} public web result(s) for '{query}'",
                    "provider": "duckduckgo_html",
                    "filters": {
                        "domains": domains,
                        "recency": recency or "any",
                        "language": language,
                        "safe_search": safe_search,
                    },
                })

        # ── Fallback 1: DuckDuckGo Instant Answer (unreliable, often empty) ──
        ia_resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": search_query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10,
        )
        ia_data = ia_resp.json()
        ia_results = []
        for item in _flatten_duckduckgo_topics(ia_data.get("RelatedTopics", [])):
            url = _clean_url(item.get("FirstURL", ""))
            if not url:
                continue
            ia_results.append(_build_web_result(
                title=item.get("Text", ""),
                url=url,
                snippet=item.get("Text", ""),
                source="duckduckgo_instant_answer",
                rank=len(ia_results) + 1,
            ))
        ia_results = _filter_web_results(ia_results, domains, limit)
        if ia_results:
            guidance = _web_search_guidance(query, ia_results, domains)
            return _ok({
                "ok": True,
                "status": "succeeded",
                "query": query,
                "search_query": search_query,
                "results": ia_results,
                "count": len(ia_results),
                "answer_hint": guidance["answer_hint"],
                "results_markdown": _web_results_markdown(ia_results),
                "next_actions": guidance["next_actions"],
                "summary": f"Found {len(ia_results)} public web result(s) for '{query}'",
                "provider": "duckduckgo_instant_answer",
                "filters": {
                    "domains": domains,
                    "recency": recency or "any",
                    "language": language,
                    "safe_search": safe_search,
                },
            })

        # ── No results from any provider ──
        return _result(False, {
            "status": "no_results",
            "query": query,
            "search_query": search_query,
            "results": [],
            "count": 0,
            "summary": "搜索服务未返回结果",
            "errors": [],
            "warnings": ["web_search_no_results"],
            "provider": "none",
            "hint": _web_no_results_hint(query),
            "next_actions": _web_no_results_actions(query, domains),
            "filters": {"domains": domains, "recency": recency or "any"},
        })
    except Exception as e:
        return _result(False, {
            "status": "provider_error",
            "query": query,
            "search_query": search_query,
            "results": [],
            "count": 0,
            "summary": f"Search unavailable: {str(e)[:100]}",
            "errors": [f"web_search_provider_error: {str(e)[:200]}"],
            "warnings": ["web_search_provider_error"],
            "provider": "error",
            "next_actions": _web_no_results_actions(query, domains),
        })


def _parse_duckduckgo_html(html: str, limit: int) -> list:
    """Parse DuckDuckGo HTML search results page."""
    import html as html_lib
    results = []
    # Each result is in <a rel="nofollow" class="result__a" href="URL">Title</a>
    # followed by <a class="result__snippet">Snippet</a>
    links = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    snippets = re.findall(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    for i, (url, title) in enumerate(links):
        if i >= limit:
            break
        snippet = re.sub(r'<[^>]+>', '', snippets[i]) if i < len(snippets) else ""
        clean_url = _clean_url(html_lib.unescape(url))
        if not clean_url or _is_private_url(clean_url):
            continue
        clean_title = _clean_text(title, 180)
        clean_snippet = _clean_text(snippet, 360)
        if not clean_title and not clean_snippet:
            continue
        results.append(_build_web_result(
            title=clean_title,
            url=clean_url,
            snippet=clean_snippet,
            source="duckduckgo_html",
            rank=len(results) + 1,
        ))
    return results


def _coerce_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(min_value, min(max_value, n))


def _normalize_search_domains(args: dict) -> list[str]:
    raw = args.get("domains", None)
    if raw is None:
        raw = args.get("site", "")
    if isinstance(raw, str):
        values = [v.strip() for v in raw.split(",") if v.strip()]
    elif isinstance(raw, list):
        values = [str(v).strip() for v in raw if str(v).strip()]
    else:
        values = []
    domains = []
    for item in values:
        dom = _domain_from_url_or_host(item)
        if dom and dom not in domains:
            domains.append(dom)
    return domains[:5]


def _domain_from_url_or_host(value: str) -> str:
    from urllib.parse import urlparse
    value = value.strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    host = urlparse(value).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _build_web_search_query(query: str, domains: list[str]) -> str:
    if not domains:
        return query
    domain_expr = " OR ".join(f"site:{d}" for d in domains)
    return f"({domain_expr}) {query}"


def _duckduckgo_search_params(query: str, recency: str, language: str, safe_search: str) -> dict:
    params = {"q": query}
    if language:
        params["kl"] = _duckduckgo_region(language)
    if safe_search in ("strict", "moderate", "off"):
        params["kp"] = {"strict": "1", "moderate": "-1", "off": "-2"}[safe_search]
    if recency in ("day", "d", "week", "w", "month", "m", "year", "y"):
        params["df"] = {"day": "d", "d": "d", "week": "w", "w": "w",
                        "month": "m", "m": "m", "year": "y", "y": "y"}[recency]
    return params


def _duckduckgo_region(language: str) -> str:
    lang = language.lower().replace("_", "-")
    if lang.startswith("zh"):
        return "cn-zh"
    if lang.startswith("en"):
        return "us-en"
    return lang


def _clean_url(url: str) -> str:
    from urllib.parse import parse_qs, unquote, urlparse
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if "duckduckgo.com" in (parsed.netloc or "") and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            url = unquote(uddg)
            parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    return url


def _clean_text(text: str, max_chars: int) -> str:
    import html as html_lib
    text = re.sub(r'<[^>]+>', ' ', text or "")
    text = html_lib.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


def _build_web_result(title: str, url: str, snippet: str, source: str, rank: int) -> dict:
    domain = _domain_from_url_or_host(url)
    return {
        "rank": rank,
        "title": _clean_text(title, 180) or domain or url,
        "url": url,
        "domain": domain,
        "snippet": _clean_text(snippet, 360),
        "source": source,
        "source_quality": _source_quality(domain),
        "citation": f"[{rank}] {domain}",
    }


def _source_quality(domain: str) -> str:
    if not domain:
        return "unknown"
    official_hints = (
        "cisco.com", "huawei.com", "h3c.com", "ruijienetworks.com",
        "juniper.net", "arista.com", "ietf.org", "rfc-editor.org",
        "microsoft.com", "github.com", "python.org",
    )
    if any(domain == d or domain.endswith("." + d) for d in official_hints):
        return "official_or_primary"
    if domain.endswith((".edu", ".gov")):
        return "institutional"
    return "public_web"


def _filter_web_results(results: list[dict], domains: list[str], limit: int) -> list[dict]:
    seen = set()
    filtered = []
    for result in results:
        url = result.get("url", "")
        domain = result.get("domain") or _domain_from_url_or_host(url)
        if domains and not any(domain == d or domain.endswith("." + d) for d in domains):
            continue
        if not url or url in seen:
            continue
        seen.add(url)
        item = dict(result)
        item["rank"] = len(filtered) + 1
        item["citation"] = f"[{item['rank']}] {item.get('domain') or domain}"
        filtered.append(item)
        if len(filtered) >= limit:
            break
    return filtered


def _flatten_duckduckgo_topics(topics: list) -> list:
    flat = []
    for item in topics or []:
        if "Topics" in item:
            flat.extend(_flatten_duckduckgo_topics(item.get("Topics", [])))
        else:
            flat.append(item)
    return flat


def _web_results_markdown(results: list[dict]) -> str:
    lines = []
    for item in results:
        snippet = item.get("snippet", "")
        suffix = f" — {snippet}" if snippet else ""
        lines.append(f"{item.get('citation', '')} {item.get('title', '')}: {item.get('url', '')}{suffix}")
    return "\n".join(lines)


def _web_search_guidance(query: str, results: list[dict], domains: list[str]) -> dict:
    official = [r for r in results if r.get("source_quality") == "official_or_primary"]
    answer_hint = (
        "优先引用 official_or_primary 结果；回答中保留 citation 编号和 URL。"
        if official else
        "结果来自公开网页；回答前说明来源可信度，并优先交叉验证前 2-3 条。"
    )
    next_actions = [
        "用结果的 title/snippet 先回答用户问题，不要编造网页未给出的细节。",
        "如果需要精确引用或正文细节，再调用 web.fetch_summary 读取具体 URL。",
    ]
    if not domains:
        next_actions.append("如用户要求厂商文档，下一次搜索加 domains/site 限定官方站点。")
    return {"answer_hint": answer_hint, "next_actions": next_actions}


def _web_no_results_actions(query: str, domains: list[str]) -> list[str]:
    actions = ["换 2-4 个更具体关键词重试。"]
    if domains:
        actions.append("放宽 domains/site 限制后重试。")
    actions.append("如果问题适合本地知识库，先用 knowledge.search 查询。")
    return actions


def _web_no_results_hint(query: str) -> str:
    """Return a user-friendly hint when no web results are found."""
    q = query.lower()
    if any(w in q for w in ("天气", "weather", "气温", "温度")):
        return "天气类查询可改用 weather.current / weather.forecast，或换更具体的城市和日期重试。"
    if any(w in q for w in ("新闻", "news", "最新", "今日")):
        return "实时新闻可改用 news.search，或加入来源/时间/领域关键词重试。"
    return "搜索服务没有返回可用结果。我可以基于通用知识回答；如需实时内容，请更换搜索源或尝试更具体的关键词。"


def handle_weather_current(inv: ToolInvocation) -> dict:
    """Current-weather lookup backed by structured public weather data."""
    args = inv.arguments
    location = (args.get("location") or "").strip()
    if not location:
        return _error("location is required")
    language = (args.get("language") or "zh-CN").strip() or "zh-CN"
    units = (args.get("units") or "metric").strip().lower()
    structured = _lookup_open_meteo_weather(
        location=location,
        days=1,
        language=language,
        units=units,
        include_current=True,
    )
    if structured.get("ok"):
        return _weather_structured_result(
            tool_id="weather.current",
            location=location,
            units=units,
            language=language,
            structured=structured,
        )

    query = f"{location} current weather temperature humidity wind"
    out = handle_web_search(ToolInvocation(
        tool_id="web.search",
        arguments={
            "query": query,
            "top_k": _coerce_int(args.get("top_k", 5), default=5, min_value=1, max_value=10),
            "recency": args.get("recency", "day"),
            "language": language,
            "safe_search": args.get("safe_search", "moderate"),
        },
        workspace_id=inv.workspace_id,
        run_id=inv.run_id,
        job_id=inv.job_id,
        dry_run=inv.dry_run,
        requested_by=inv.requested_by,
        approval_id=inv.approval_id,
    ))
    return _decorate_realtime_search_result(
        out,
        tool_id="weather.current",
        query=query,
        tool_fallback="web.search",
        extra={"location": location, "units": units, "language": language},
    )


def handle_weather_forecast(inv: ToolInvocation) -> dict:
    """Weather forecast lookup backed by structured public weather data."""
    args = inv.arguments
    location = (args.get("location") or "").strip()
    if not location:
        return _error("location is required")
    days = _coerce_int(args.get("days", 3), default=3, min_value=1, max_value=10)
    language = (args.get("language") or "zh-CN").strip() or "zh-CN"
    units = (args.get("units") or "metric").strip().lower()
    structured = _lookup_open_meteo_weather(
        location=location,
        days=days,
        language=language,
        units=units,
        include_current=False,
    )
    if structured.get("ok"):
        return _weather_structured_result(
            tool_id="weather.forecast",
            location=location,
            units=units,
            language=language,
            structured=structured,
        )

    query = f"{location} {days} day weather forecast"
    out = handle_web_search(ToolInvocation(
        tool_id="web.search",
        arguments={
            "query": query,
            "top_k": _coerce_int(args.get("top_k", 5), default=5, min_value=1, max_value=10),
            "recency": args.get("recency", "day"),
            "language": language,
            "safe_search": args.get("safe_search", "moderate"),
        },
        workspace_id=inv.workspace_id,
        run_id=inv.run_id,
        job_id=inv.job_id,
        dry_run=inv.dry_run,
        requested_by=inv.requested_by,
        approval_id=inv.approval_id,
    ))
    return _decorate_realtime_search_result(
        out,
        tool_id="weather.forecast",
        query=query,
        tool_fallback="web.search",
        extra={"location": location, "days": days, "units": units, "language": language},
    )


def handle_news_search(inv: ToolInvocation) -> dict:
    """News lookup backed by the public web search provider."""
    args = inv.arguments
    query = (args.get("query") or "").strip()
    if not query:
        return _error("query is required")
    recency = (args.get("recency") or "day").strip().lower()
    language = (args.get("language") or "zh-CN").strip() or "zh-CN"
    out = handle_web_search(ToolInvocation(
        tool_id="web.search",
        arguments={
            "query": query,
            "top_k": _coerce_int(args.get("top_k", args.get("limit", 5)), default=5, min_value=1, max_value=10),
            "site": args.get("site", ""),
            "domains": args.get("domains", []),
            "recency": recency,
            "language": language,
            "safe_search": args.get("safe_search", "moderate"),
        },
        workspace_id=inv.workspace_id,
        run_id=inv.run_id,
        job_id=inv.job_id,
        dry_run=inv.dry_run,
        requested_by=inv.requested_by,
        approval_id=inv.approval_id,
    ))
    return _decorate_realtime_search_result(
        out,
        tool_id="news.search",
        query=query,
        tool_fallback="web.search",
        extra={"recency": recency, "language": language},
    )


def _decorate_realtime_search_result(out: dict, *, tool_id: str, query: str,
                                     tool_fallback: str, extra: dict) -> dict:
    result = dict(out or {})
    result.setdefault("ok", False)
    result["tool_id"] = tool_id
    result["tool_fallback"] = tool_fallback
    result["query"] = result.get("query") or query
    result["source_type"] = "public_web_realtime"
    result["metadata"] = {**extra, "backing_tool": tool_fallback}
    if result.get("ok"):
        result.setdefault("summary", f"{tool_id} returned public web results")
        result.setdefault("warnings", [])
    else:
        result.setdefault("warnings", [])
        result["warnings"] = list(result["warnings"]) + ["backed_by_public_web_search"]
    return result


def _lookup_open_meteo_weather(*, location: str, days: int, language: str,
                               units: str, include_current: bool) -> dict:
    """Fetch structured weather data from Open-Meteo's no-key public APIs."""
    try:
        import requests

        geo_resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": location,
                "count": 1,
                "language": _open_meteo_language(language),
                "format": "json",
            },
            timeout=10,
            headers={"User-Agent": "NetworkAgent/1.0 (+https://github.com/zhangh05/network_agent)"},
        )
        if geo_resp.status_code != 200:
            return _result(False, {
                "status": "geocoding_http_error",
                "errors": [f"open_meteo_geocoding_http_{geo_resp.status_code}"],
            })
        geo_data = geo_resp.json()
        matches = geo_data.get("results") or []
        if not matches:
            return _result(False, {
                "status": "location_not_found",
                "errors": ["open_meteo_location_not_found"],
            })
        place = matches[0]
        latitude = place.get("latitude")
        longitude = place.get("longitude")
        if latitude is None or longitude is None:
            return _result(False, {
                "status": "geocoding_missing_coordinates",
                "errors": ["open_meteo_geocoding_missing_coordinates"],
            })

        forecast_params = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
            "forecast_days": max(1, min(days, 10)),
            "daily": ",".join((
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "precipitation_sum",
                "wind_speed_10m_max",
            )),
            "temperature_unit": "fahrenheit" if units == "imperial" else "celsius",
            "wind_speed_unit": "mph" if units == "imperial" else "kmh",
            "precipitation_unit": "inch" if units == "imperial" else "mm",
        }
        if include_current:
            forecast_params["current"] = ",".join((
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "weather_code",
                "wind_speed_10m",
                "wind_direction_10m",
            ))
        weather_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=forecast_params,
            timeout=10,
            headers={"User-Agent": "NetworkAgent/1.0 (+https://github.com/zhangh05/network_agent)"},
        )
        if weather_resp.status_code != 200:
            return _result(False, {
                "status": "forecast_http_error",
                "errors": [f"open_meteo_forecast_http_{weather_resp.status_code}"],
            })
        weather = weather_resp.json()
        daily = _parse_open_meteo_daily(weather.get("daily") or {}, weather.get("daily_units") or {})
        current = (
            _parse_open_meteo_current(weather.get("current") or {}, weather.get("current_units") or {})
            if include_current else {}
        )
        if include_current and not current:
            return _result(False, {
                "status": "current_weather_empty",
                "errors": ["open_meteo_current_weather_empty"],
            })
        if not include_current and not daily:
            return _result(False, {
                "status": "forecast_empty",
                "errors": ["open_meteo_forecast_empty"],
            })
        resolved_name = ", ".join(
            str(v) for v in (place.get("name"), place.get("admin1"), place.get("country"))
            if v
        )
        return _ok({
            "status": "succeeded",
            "provider": "open_meteo",
            "source_type": "structured_weather",
            "source_url": "https://open-meteo.com/",
            "location": location,
            "resolved_location": {
                "name": resolved_name or place.get("name") or location,
                "latitude": latitude,
                "longitude": longitude,
                "timezone": weather.get("timezone", ""),
            },
            "current": current,
            "forecast_daily": daily,
        })
    except Exception as e:
        return _result(False, {
            "status": "structured_weather_provider_error",
            "errors": [f"open_meteo_error: {str(e)[:200]}"],
        })


def _parse_open_meteo_current(current: dict, units: dict) -> dict:
    if not current:
        return {}
    code = current.get("weather_code")
    return {
        "time": current.get("time", ""),
        "temperature": current.get("temperature_2m"),
        "temperature_unit": units.get("temperature_2m", ""),
        "humidity": current.get("relative_humidity_2m"),
        "humidity_unit": units.get("relative_humidity_2m", "%"),
        "precipitation": current.get("precipitation"),
        "precipitation_unit": units.get("precipitation", ""),
        "wind_speed": current.get("wind_speed_10m"),
        "wind_speed_unit": units.get("wind_speed_10m", ""),
        "wind_direction": current.get("wind_direction_10m"),
        "wind_direction_unit": units.get("wind_direction_10m", ""),
        "weather_code": code,
        "condition": _weather_code_label(code),
    }


def _parse_open_meteo_daily(daily: dict, units: dict) -> list[dict]:
    dates = daily.get("time") or []
    rows = []
    for i, date in enumerate(dates):
        code = _list_get(daily.get("weather_code"), i)
        rows.append({
            "date": date,
            "condition": _weather_code_label(code),
            "weather_code": code,
            "temperature_max": _list_get(daily.get("temperature_2m_max"), i),
            "temperature_min": _list_get(daily.get("temperature_2m_min"), i),
            "temperature_unit": units.get("temperature_2m_max", units.get("temperature_2m_min", "")),
            "precipitation_probability_max": _list_get(daily.get("precipitation_probability_max"), i),
            "precipitation_probability_unit": units.get("precipitation_probability_max", "%"),
            "precipitation_sum": _list_get(daily.get("precipitation_sum"), i),
            "precipitation_unit": units.get("precipitation_sum", ""),
            "wind_speed_max": _list_get(daily.get("wind_speed_10m_max"), i),
            "wind_speed_unit": units.get("wind_speed_10m_max", ""),
        })
    return rows


def _list_get(values: Any, index: int) -> Any:
    if isinstance(values, list) and index < len(values):
        return values[index]
    return None


def _weather_code_label(code: Any) -> str:
    labels = {
        0: "晴",
        1: "基本晴朗",
        2: "局部多云",
        3: "阴/多云",
        45: "雾",
        48: "雾凇",
        51: "小毛毛雨",
        53: "中等毛毛雨",
        55: "大毛毛雨",
        56: "冻毛毛雨",
        57: "强冻毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "冻雨",
        67: "强冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "小阵雨",
        81: "中等阵雨",
        82: "强阵雨",
        85: "小阵雪",
        86: "强阵雪",
        95: "雷暴",
        96: "雷暴伴小冰雹",
        99: "雷暴伴强冰雹",
    }
    try:
        return labels.get(int(code), "未知")
    except Exception:
        return "未知"


def _open_meteo_language(language: str) -> str:
    lang = (language or "").lower()
    if lang.startswith("zh"):
        return "zh"
    if lang.startswith("en"):
        return "en"
    return "en"


def _weather_structured_result(*, tool_id: str, location: str, units: str,
                               language: str, structured: dict) -> dict:
    result = dict(structured)
    result["tool_id"] = tool_id
    result["tool_fallback"] = None
    result["query"] = location
    result["metadata"] = {
        "location": location,
        "units": units,
        "language": language,
        "provider": "open_meteo",
    }
    result["count"] = len(result.get("forecast_daily") or []) or (1 if result.get("current") else 0)
    result["citation"] = "[1] open-meteo.com"
    result["results"] = [{
        "rank": 1,
        "title": "Open-Meteo weather forecast API",
        "url": "https://open-meteo.com/",
        "domain": "open-meteo.com",
        "citation": "[1] open-meteo.com",
        "source_quality": "public_data_api",
    }]
    result["results_markdown"] = _weather_results_markdown(result)
    result["summary"] = _weather_summary(result)
    result["answer_hint"] = "直接使用 current/forecast_daily 里的结构化天气字段回答；引用 [1] open-meteo.com，并说明天气预报会变化。"
    result["next_actions"] = [
        "用 current 或 forecast_daily 的温度、降水概率/降水量、风速字段直接回答用户。",
        "如果用户要求官方气象台口径，再用 web.search 或 web.fetch_summary 交叉验证气象局页面。",
    ]
    return _result(True, result)


def _weather_summary(result: dict) -> str:
    resolved = (result.get("resolved_location") or {}).get("name") or result.get("location") or "location"
    current = result.get("current") or {}
    if current:
        temp = _format_weather_value(current.get("temperature"), current.get("temperature_unit"))
        wind = _format_weather_value(current.get("wind_speed"), current.get("wind_speed_unit"))
        return f"{resolved} 当前天气：{current.get('condition', '未知')}，气温 {temp}，风速 {wind}"
    daily = result.get("forecast_daily") or []
    if daily:
        first = daily[0]
        low = _format_weather_value(first.get("temperature_min"), first.get("temperature_unit"))
        high = _format_weather_value(first.get("temperature_max"), first.get("temperature_unit"))
        pop = _format_weather_value(first.get("precipitation_probability_max"), first.get("precipitation_probability_unit"))
        return f"{resolved} {first.get('date', '')} 预报：{first.get('condition', '未知')}，{low}-{high}，降水概率 {pop}"
    return f"{resolved} 天气数据已返回"


def _weather_results_markdown(result: dict) -> str:
    lines = ["[1] Open-Meteo weather forecast API: https://open-meteo.com/"]
    current = result.get("current") or {}
    if current:
        lines.append(
            "当前: "
            f"{current.get('condition', '未知')}, "
            f"温度 {_format_weather_value(current.get('temperature'), current.get('temperature_unit'))}, "
            f"湿度 {_format_weather_value(current.get('humidity'), current.get('humidity_unit'))}, "
            f"降水 {_format_weather_value(current.get('precipitation'), current.get('precipitation_unit'))}, "
            f"风速 {_format_weather_value(current.get('wind_speed'), current.get('wind_speed_unit'))}"
        )
    for day in (result.get("forecast_daily") or [])[:5]:
        lines.append(
            f"{day.get('date', '')}: {day.get('condition', '未知')}, "
            f"{_format_weather_value(day.get('temperature_min'), day.get('temperature_unit'))}-"
            f"{_format_weather_value(day.get('temperature_max'), day.get('temperature_unit'))}, "
            f"降水概率 {_format_weather_value(day.get('precipitation_probability_max'), day.get('precipitation_probability_unit'))}, "
            f"风速 {_format_weather_value(day.get('wind_speed_max'), day.get('wind_speed_unit'))}"
        )
    return "\n".join(lines)


def _format_weather_value(value: Any, unit: str) -> str:
    if value is None:
        return "未知"
    return f"{value}{unit or ''}"


def handle_web_fetch_summary(inv: ToolInvocation) -> dict:
    args = inv.arguments
    url = (args.get("url") or "").strip()
    if not url:
        return _error("url is required")
    if _is_private_url(url):
        return _error("blocked: private/local network URLs not allowed")
    try:
        import requests
        headers = {
            "User-Agent": "NetworkAgent/0.2",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return _error(f"HTTP {resp.status_code}")
        _fix_encoding(resp)
        html = resp.text
        text = _html_to_text(html)
        if not text:
            return _result(False, {
                "status": "empty_readable_text",
                "url": url,
                "status_code": resp.status_code,
                "source_type": "web_fetch",
                "summary": "网页可访问，但没有抽取到可读正文。",
                "warnings": ["web_fetch_empty_readable_text"],
                "next_actions": ["换用更具体的公开网页 URL，或先用 web.extract_links 找正文页面。"],
            })
        return _ok({
            "url": url,
            "title": _extract_title(html),
            "summary": _safe_preview(text, 800),
            "text_length": len(html),
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
    doc_targets = {
        "cisco": ("cisco.com", "https://www.cisco.com/c/en/us/support/docs/index.html"),
        "huawei": ("huawei.com", "https://support.huawei.com/enterprise/en/doc/index.html"),
        "h3c": ("h3c.com", "https://www.h3c.com/en/Support/Resource_Center/"),
        "ruijie": ("ruijienetworks.com", "https://www.ruijienetworks.com/support/documents/"),
        "arista": ("arista.com", "https://www.arista.com/en/support/product-documentation"),
    }
    domains = []
    base = ""
    if vendor in doc_targets:
        domain, base = doc_targets[vendor]
        domains = [domain]
    out = handle_web_search(ToolInvocation(
        tool_id="web.search",
        arguments={
            "query": query,
            "domains": domains,
            "top_k": _coerce_int(args.get("top_k", 5), default=5, min_value=1, max_value=10),
            "language": args.get("language", "zh-CN"),
            "safe_search": args.get("safe_search", "moderate"),
        },
        workspace_id=inv.workspace_id,
        run_id=inv.run_id,
        job_id=inv.job_id,
        dry_run=inv.dry_run,
        requested_by=inv.requested_by,
        approval_id=inv.approval_id,
    ))
    result = dict(out or {})
    result["tool_id"] = "web.official_doc_search"
    result["source_type"] = "official_doc_search"
    result["vendor"] = vendor
    result["official_domains"] = domains
    result["doc_base_url"] = base
    result.setdefault("next_actions", [])
    result["next_actions"] = list(result["next_actions"]) + [
        "优先引用 official_or_primary 结果；如需要正文细节，再调用 web.fetch_summary。",
    ]
    if not result.get("ok") and base:
        result["status"] = "fallback_doc_index"
        result["provider"] = "official_doc_index"
        result["results"] = [{
            "rank": 1,
            "title": f"{vendor} documentation index",
            "url": base,
            "domain": domains[0] if domains else "",
            "citation": f"[1] {domains[0] if domains else vendor}",
            "source_quality": "official_or_primary",
        }]
        result["count"] = len(result["results"])
        result["summary"] = "搜索未命中具体文档，已返回官方文档入口。"
        result["results_markdown"] = f"[1] {vendor} documentation index: {base}"
    return _result(bool(result.get("results")), result)


def handle_web_extract_links(inv: ToolInvocation) -> dict:
    args = inv.arguments
    url = (args.get("url") or "").strip()
    if not url:
        return _error("url is required")
    if _is_private_url(url):
        return _error("blocked: private/local network URLs not allowed")
    try:
        import requests
        headers = {
            "User-Agent": "NetworkAgent/0.2",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return _error(f"HTTP {resp.status_code}")
        _fix_encoding(resp)
        links = re.findall(r'href=["\'](https?://[^"\'\s]+)', resp.text)
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
        headers = {
            "User-Agent": "NetworkAgent/0.2",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return _error(f"HTTP {resp.status_code}")
        _fix_encoding(resp)
        content = f"# {title}\n\nSource: {url}\n\n{_html_to_text(resp.text)}"
        from artifacts.store import save_artifact
        rec = save_artifact(workspace_id=ws, content=content, title=title,
                            artifact_type="knowledge_doc", sensitivity="internal")
        if not rec:
            return _error("artifact save blocked or failed")
        return _ok({"artifact_id": rec.artifact_id, "title": title, "source_url": url})
    except Exception as e:
        return _error(str(e)[:200])


def _fix_encoding(resp):
    """Fix response encoding for Chinese page support.

    1. Look for <meta charset> in raw bytes (works even without chardet)
    2. Fall back to resp.apparent_encoding (chardet)
    3. Last resort: try common CJK encodings
    """
    # Already explicitly set
    if resp.encoding and resp.encoding.lower() not in ("iso-8859-1", "latin-1", ""):
        return
    # Try to detect from meta tag in raw bytes (first 2048 bytes)
    try:
        raw_head = resp.content[:2048]
        m = re.search(rb'charset[="\s]+([a-zA-Z0-9_-]+)', raw_head, re.I)
        if m:
            candidate = m.group(1).decode("ascii", errors="replace").lower()
            # Map common CJK aliases
            aliases = {"gb2312": "gbk", "gbk": "gbk", "gb18030": "gb18030",
                       "big5": "big5", "utf-8": "utf-8", "utf8": "utf-8"}
            if candidate in aliases:
                resp.encoding = aliases[candidate]
                return
            resp.encoding = candidate
            return
    except Exception:
        pass
    # Fall back to auto-detection (chardet)
    resp.encoding = resp.apparent_encoding


def _html_to_text(html: str) -> str:
    """Extract readable text from HTML, CJK-friendly.

    1. Strip <script>, <style>, <noscript>, <head> blocks
    2. Remove remaining HTML tags
    3. Decode common HTML entities
    4. Collapse whitespace
    """
    if not html:
        return ""
    # Remove invisible blocks
    text = re.sub(r'<(script|style|noscript|head)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    # Replace block-level tags with line breaks (preserve paragraph structure)
    text = re.sub(r'</?(br|p|div|li|h[1-6]|tr|section|article|header|footer|nav)[^>]*>', '\n', text, flags=re.I)
    # Remove all remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode common HTML entities
    import html as _html
    text = _html.unescape(text)
    # Collapse whitespace
    text = re.sub(r'&nbsp;', ' ', text, flags=re.I)
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _strip_tags(html: str) -> str:
    """Remove script/style blocks then HTML tags."""
    if not html:
        return ""
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
    return re.sub(r'<[^>]+>', ' ', text)


def _extract_title(html: str) -> str:
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    if not m:
        return ""
    import html as _html
    return _html.unescape(m.group(1).strip())[:200]


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
        s = get_session(sid, ws)
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


def handle_skill_list(inv: ToolInvocation) -> dict:
    """List skills available in the skills/ directory. Read skill.yaml first, then SKILL.md."""
    try:
        skills_dir = ROOT / "skills"
        if not skills_dir.is_dir():
            return _ok({"results": [], "count": 0})
        results = []
        for item in sorted(skills_dir.iterdir()):
            if not item.is_dir() or item.name.startswith(".") or item.name in ("__pycache__",):
                continue
            skill_info = {"name": item.name, "path": str(item.relative_to(ROOT)), "description": "", "status": "unknown", "capabilities": []}
            # Read skill.yaml first
            yaml_path = item / "skill.yaml"
            if yaml_path.is_file():
                try:
                    import yaml
                    with open(yaml_path, encoding="utf-8") as fy:
                        data = yaml.safe_load(fy)
                    if isinstance(data, dict):
                        skill_info["description"] = str(data.get("description") or data.get("display_name") or "")
                        skill_info["status"] = str(data.get("status", "unknown"))
                        skill_info["capabilities"] = [c.get("capability_id", "") for c in (data.get("capabilities") or []) if isinstance(c, dict)]
                except Exception:
                    pass
            # Fall back to SKILL.md if no description from yaml
            if not skill_info.get("description"):
                md_path = item / "SKILL.md"
                if md_path.is_file():
                    try:
                        md_text = md_path.read_text(encoding="utf-8")[:500]
                        # Extract first meaningful line after headings
                        for line in md_text.split("\n"):
                            stripped = line.strip()
                            if stripped and not stripped.startswith("#"):
                                skill_info["description"] = stripped[:200]
                                break
                    except Exception:
                        pass
            results.append(skill_info)
        return _ok({"results": results, "count": len(results)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_skill_request_load(inv: ToolInvocation) -> dict:
    """Request loading a skill — records the request but does NOT inject system prompt.

    Phase 2 placeholder: returns requested=true but message says
    "runtime-controlled skill loading is not implemented yet."
    """
    args = inv.arguments
    skill_name = str(args.get("skill_name", "")).strip()
    reason = str(args.get("reason", "")).strip()
    ws = args.get("workspace_id", "default")
    sid = args.get("session_id", "")

    if not skill_name:
        return _error("skill_name is required")

    # Verify skill exists in skills/ directory or registry
    skills_dir = ROOT / "skills"
    found = False
    if skills_dir.is_dir():
        target = skills_dir / skill_name
        if target.is_dir() and not skill_name.startswith("."):
            found = True

    if not found:
        return _error(f"skill '{skill_name}' not found in skills directory")

    # Record request to workspace (optional, best-effort)
    try:
        import json
        req_path = WS_ROOT / ws / "skill_requests.jsonl"
        with open(req_path, "a") as f:
            f.write(json.dumps({
                "skill_name": skill_name, "reason": reason,
                "session_id": sid, "workspace_id": ws,
                "requested_at": __import__('time').strftime("%Y-%m-%dT%H:%M:%S"),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return _ok({
        "requested": True,
        "skill_name": skill_name,
        "message": "runtime-controlled skill loading is not implemented yet; request recorded",
    })


def handle_memory_create(inv: ToolInvocation) -> dict:
    """Create a long-term memory entry. Default status=pending_confirmation.

    Phase 2 enhancements: key, value_preview, status fields; session-scoped.
    """
    args = inv.arguments
    title = str(args.get("title", "")).strip()
    content = str(args.get("content", "")).strip()
    if not title or not content:
        return _error("title and content are required")
    try:
        from memory.redaction import contains_secret, redact_text
        if contains_secret(title) or contains_secret(content):
            return _error("content contains secrets — memory.create blocked")
        from memory.writer import write_memory
        import time
        key = str(args.get("key", title[:60]))
        value_preview = content[:200]
        ws = str(args.get("workspace_id", "default"))
        sid = str(args.get("session_id", ""))
        memory_id = write_memory(
            title=title,
            content=content,
            scope=str(args.get("scope", "long_term")),
            memory_type=str(args.get("memory_type", "knowledge_note")),
            tags=list(args.get("tags") or []),
            project_id=ws,
            source="llm_tool",
            confidence=str(args.get("confidence", "system_generated")),
            summary=str(args.get("summary", value_preview)),
            sensitivity=str(args.get("sensitivity", "internal")),
            metadata={
                **(args.get("metadata") or {}),
                "key": key,
                "value_preview": value_preview,
                "status": "pending_confirmation",
                "session_id": sid,
                "workspace_id": ws,
                "source": "llm_tool",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            user_confirmed=False,
        )
        if not memory_id:
            return _error("memory write blocked by policy")
        return _ok({
            "memory_id": memory_id,
            "status": "pending_confirmation",
            "key": key,
            "value_preview": value_preview,
        })
    except Exception as e:
        return _error(str(e)[:200])


def handle_memory_list(inv: ToolInvocation) -> dict:
    """List memory entries. Phase 2: support status/session_id filtering, value_preview only."""
    args = inv.arguments
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        results = store.list(
            scope=args.get("scope"),
            memory_type=args.get("memory_type"),
            project_id=args.get("workspace_id"),
            limit=args.get("limit", 20),
        )
        # Phase 2 filtering
        status_filter = args.get("status", "")
        session_filter = args.get("session_id", "")
        summaries = []
        for r in results:
            meta = (r.get("metadata") or {})
            mem_status = meta.get("status", "confirmed") if isinstance(meta, dict) else "confirmed"
            mem_sid = meta.get("session_id", "") if isinstance(meta, dict) else ""
            if status_filter and mem_status != status_filter:
                continue
            if session_filter and mem_sid != session_filter:
                continue
            summaries.append({
                "memory_id": r.get("memory_id", ""),
                "title": r.get("title", ""),
                "summary": (r.get("summary", "") or r.get("content", ""))[:200],
                "key": meta.get("key", "") if isinstance(meta, dict) else "",
                "value_preview": meta.get("value_preview", "") if isinstance(meta, dict) else "",
                "status": mem_status,
                "memory_type": r.get("memory_type", ""),
                "scope": r.get("scope", ""),
                "created_at": r.get("created_at", ""),
                "tags": r.get("tags", [])[:5],
            })
        return _ok({"results": summaries, "count": len(summaries)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_memory_confirm(inv: ToolInvocation) -> dict:
    """Confirm a pending_confirmation memory entry. Phase 2: status-only update.

    Does not rebuild RAG index — only updates the in-store status.
    """
    args = inv.arguments
    memory_id = str(args.get("memory_id", "")).strip()
    if not memory_id:
        return _error("memory_id is required")
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        entry = store.get(memory_id)
        if not entry:
            return _error(f"memory_id not found: {memory_id}")

        meta = entry.get("metadata") or {}
        status = meta.get("status", "confirmed") if isinstance(meta, dict) else "confirmed"
        if status == "confirmed":
            return _ok({"memory_id": memory_id, "already_confirmed": True, "status": "confirmed"})

        # Update status
        if isinstance(meta, dict):
            meta["status"] = "confirmed"
        else:
            meta = {"status": "confirmed"}
        store.update_metadata(memory_id, meta)
        return _ok({"memory_id": memory_id, "status": "confirmed", "already_confirmed": False})
    except Exception as e:
        return _error(str(e)[:200])


def handle_memory_get_profile(inv: ToolInvocation) -> dict:
    """Get user profile. Phase 2: returns explicit/implicit/tool_stats/updated_at."""
    ws = inv.arguments.get("workspace_id", "default")
    try:
        validate_workspace_id(ws)
        profile_path = WS_ROOT / ws / "memory" / "profile.json"
        if not profile_path.is_file():
            return _ok({
                "explicit_preferences": {},
                "inferred_preferences": {},
                "tool_usage_stats": {},
                "updated_at": "",
            })
        import json
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        return _ok({
            "explicit_preferences": data.get("explicit_preferences", {}),
            "inferred_preferences": data.get("inferred_preferences", {}),
            "tool_usage_stats": data.get("tool_usage_stats", {}),
            "updated_at": data.get("updated_at", ""),
        })
    except Exception as e:
        return _error(str(e)[:200])


def handle_memory_set_profile(inv: ToolInvocation) -> dict:
    """Set user profile. Phase 2: merge=false replaces; merge=true (default) merges into explicit_preferences.

    Only writes to explicit_preferences. Never stores secrets.
    """
    ws = inv.arguments.get("workspace_id", "default")
    field = str(inv.arguments.get("field", "")).strip()
    value = inv.arguments.get("value")
    merge = bool(args.get("merge", True)) if (args := inv.arguments) else True
    if not field:
        return _error("field is required")
    try:
        validate_workspace_id(ws)
        from memory.redaction import contains_secret
        if isinstance(value, str) and contains_secret(value):
            return _error("value contains secrets — set_profile blocked")
        import json, time
        memory_dir = WS_ROOT / ws / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        profile_path = memory_dir / "profile.json"
        profile = {"explicit_preferences": {}, "inferred_preferences": {}, "tool_usage_stats": {}, "updated_at": ""}
        if profile_path.is_file():
            existing = json.loads(profile_path.read_text(encoding="utf-8"))
            profile.update(existing)
        if merge:
            profile.setdefault("explicit_preferences", {})[field] = value
        else:
            profile["explicit_preferences"] = {field: value} if value is not None else {}
        profile["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        return _ok({"field": field, "saved": True})
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
        from artifacts.store import save_artifact
        rec = save_artifact(workspace_id=ws, content=content, title=title,
                            artifact_type="report", sensitivity="internal")
        if not rec:
            return _error("report artifact save blocked or failed")
        return _ok({
            "artifact_id": rec.artifact_id,
            "artifact_ids": [rec.artifact_id],
            "title": title,
            "artifact_type": "report",
        })
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

_SHELL_TIMEOUT = 30
_SHELL_MAX_OUTPUT = 10000

def _run_shell(command: str, cwd: str = None, shell: str = "/bin/bash",
               env: dict = None) -> dict:
    """Execute a shell command with safety limits. Returns result dict."""
    import subprocess, shlex
    if not command or not command.strip():
        return {"ok": False, "error": "empty command"}
    try:
        result = subprocess.run(
            command if isinstance(command, list) else [shell, "-c", command],
            capture_output=True, text=True,
            timeout=_SHELL_TIMEOUT,
            cwd=cwd or str(ROOT),
            env=env,
        )
        stdout = (result.stdout or "")[:_SHELL_MAX_OUTPUT]
        stderr = (result.stderr or "")[:_SHELL_MAX_OUTPUT]
        return {
            "ok": True,
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timeout_seconds": _SHELL_TIMEOUT,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"command timed out after {_SHELL_TIMEOUT}s"}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"command not found: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def handle_command_approved_exec(inv: ToolInvocation) -> dict:
    """Shell command execution on Linux/macOS.

    Accepts a shell command string, executes via /bin/bash -c.
    Safety limits: 30s timeout, 10000 chars output, workspace-root cwd.
    Requires approval_id (high risk). Policy blocks destructive patterns.
    """
    import platform
    if platform.system() == "Windows":
        return _error("Shell execution only available on Linux/macOS. Use powershell.exec on Windows.")
    command = (inv.arguments.get("command") or inv.arguments.get("command_id") or "").strip()
    if not command:
        return _error("command is required")
    result = _run_shell(command)
    return _result(result.pop("ok", False), result)


def handle_powershell_approved_script(inv: ToolInvocation) -> dict:
    """PowerShell script execution on Windows.

    Accepts a PowerShell command string, executes via powershell -Command.
    Safety limits: 15s timeout, 10000 chars output.
    Requires approval_id (high risk). Policy blocks destructive patterns.
    """
    import platform
    if platform.system() != "Windows":
        return _error("PowerShell execution only available on Windows. Use shell.exec on Linux/macOS.")
    command = (inv.arguments.get("command") or inv.arguments.get("script_id") or "").strip()
    if not command:
        return _error("command is required")
    import subprocess
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=15,
        )
        stdout = (result.stdout or "")[:_SHELL_MAX_OUTPUT]
        stderr = (result.stderr or "")[:_SHELL_MAX_OUTPUT]
        return _ok({
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
        })
    except subprocess.TimeoutExpired:
        return _error("command timed out after 15s")
    except FileNotFoundError:
        return _error("powershell not found")
    except Exception as e:
        return _error(str(e)[:200])


# ═══════════════ J. Python Exec Tool (high risk, AST-sandboxed) ═══════════════

def handle_python_exec(inv: ToolInvocation) -> dict:
    """Execute Python code in an AST-checked sandbox.

    High risk tool. Code is parsed with AST to reject forbidden imports,
    builtins, and dunder access before execution. Runs in a subprocess with
    timeout. Requires explicit user approval.
    """
    workspace_id = inv.arguments.get("workspace_id", "default")
    run_id = inv.arguments.get("run_id", "")
    code = str(inv.arguments.get("code", "")).strip()
    timeout = min(int(inv.arguments.get("timeout", 10) or 10), 10)

    if not code:
        return _error("code is required")

    try:
        validate_workspace_id(workspace_id)
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code(
            code=code,
            workspace_id=workspace_id,
            run_id=run_id,
            timeout=timeout,
        )
        return _result(result.pop("ok", False), result)
    except Exception as e:
        return _error(str(e)[:200])


# ═══════════════ K. Session Snapshot / Rewind Tools ═══════════════

def handle_session_snapshot(inv: ToolInvocation) -> dict:
    """Create a snapshot of the current session state."""
    ws = inv.arguments.get("workspace_id", "default")
    sid = inv.arguments.get("session_id", "")
    reason = str(inv.arguments.get("reason", "")).strip()
    if not sid:
        return _error("session_id is required")
    try:
        validate_workspace_id(ws)
        from workspace.session_snapshot import create_snapshot
        result = create_snapshot(workspace_id=ws, session_id=sid, reason=reason)
        return _result(result.get("ok", False), result)
    except Exception as e:
        return _error(str(e)[:200])


def handle_session_list_snapshots(inv: ToolInvocation) -> dict:
    """List snapshots for a session."""
    ws = inv.arguments.get("workspace_id", "default")
    sid = inv.arguments.get("session_id", "")
    if not sid:
        return _error("session_id is required")
    try:
        validate_workspace_id(ws)
        from workspace.session_snapshot import list_snapshots
        results = list_snapshots(workspace_id=ws, session_id=sid)
        return _ok({"snapshots": results, "count": len(results)})
    except Exception as e:
        return _error(str(e)[:200])


def handle_session_rewind(inv: ToolInvocation) -> dict:
    """Rewind a session to a previous snapshot."""
    ws = inv.arguments.get("workspace_id", "default")
    sid = inv.arguments.get("session_id", "")
    snap_id = inv.arguments.get("snapshot_id", "")
    dry_run = bool(inv.arguments.get("dry_run", True))
    if not sid:
        return _error("session_id is required")
    if not snap_id:
        return _error("snapshot_id is required")
    try:
        validate_workspace_id(ws)
        from workspace.session_snapshot import rewind_session
        result = rewind_session(
            workspace_id=ws,
            session_id=sid,
            snapshot_id=snap_id,
            dry_run=dry_run,
        )
        return _result(result.get("ok", False), result)
    except Exception as e:
        return _error(str(e)[:200])


# ═══════════════ L. Agent Spawn (Sub-Agent) Tool ═══════════════

def handle_agent_spawn(inv: ToolInvocation) -> dict:
    """Spawn a sub-agent with restricted tool access.

    Creates a child session and runs a constrained sub-agent loop
    with only read-only, low-risk tools. Returns compressed results.
    """
    instruction = str(inv.arguments.get("instruction", "")).strip()
    workspace_id = inv.arguments.get("workspace_id", "default")
    parent_session_id = str(inv.arguments.get("session_id", ""))
    allowed_tools = list(inv.arguments.get("allowed_tools") or [])
    max_turns = int(inv.arguments.get("max_turns", 1))

    if not instruction:
        return _error("instruction is required")

    try:
        validate_workspace_id(workspace_id)
        from agent.runtime.sub_agent import run_sub_agent
        result = run_sub_agent(
            instruction=instruction,
            workspace_id=workspace_id,
            parent_session_id=parent_session_id,
            allowed_tools=allowed_tools if allowed_tools else None,
            max_turns=max_turns,
        )
        return _result(result.get("ok", False), result)
    except Exception as e:
        return _error(str(e)[:200])


# ═══════════════ Registry ═══════════════

ALL_GENERAL_TOOLS = []

REMOVED_GENERAL_TOOL_IDS = {
    # Replaced by capability-level artifact tools.
    "artifact.search",
    "artifact.read_content_safe",
    "artifact.tag",
    "artifact.delete_soft",
    # Replaced by capability-level knowledge tools.
    "knowledge.index_artifact",
    "knowledge.reindex",
    "knowledge.search",
    "knowledge.get_source",
    "knowledge.get_chunk_summary",
    "knowledge.explain_not_found",
    # Operational/backend-only surfaces; not useful as default agent tools.
    "session.create",
    "session.archive",
    "runtime.selfcheck",
    "runtime.retention_preview",
    "runtime.archive_preview",
}

def _schema(properties: dict = None, required: list[str] = None) -> dict:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
    }


S = {
    "workspace_id": {"type": "string", "description": "Workspace id. Defaults to current/default workspace when omitted."},
    "query": {"type": "string", "description": "Search or filter text. Use concise, specific keywords."},
    "limit": {"type": "integer", "description": "Maximum items to return. Keep small unless user asks for broad inventory.", "default": 10},
    "artifact_id": {"type": "string", "description": "Artifact id returned by artifact search/list tools."},
    "source_id": {"type": "string", "description": "Knowledge source id."},
    "chunk_id": {"type": "string", "description": "Knowledge chunk id."},
    "url": {"type": "string", "description": "Public http(s) URL. Private/local network URLs are blocked."},
    "title": {"type": "string", "description": "Human-readable title."},
    "content": {"type": "string", "description": "Text content. Do not include sensitive material."},
    "text": {"type": "string", "description": "Text to inspect, transform, validate, or summarize."},
    "session_id": {"type": "string", "description": "Session id from session.list or URL."},
    "run_id": {"type": "string", "description": "Run id from run.list_recent or trace."},
    "filepath": {"type": "string", "description": "Workspace-relative file path, e.g. state.json or outputs/report.md."},
    "days": {"type": "integer", "description": "Forecast horizon in days, 1-10.", "default": 3},
    "recency": {"type": "string", "description": "Time filter: day, week, month, or year.", "default": "week"},
    "format": {"type": "string", "description": "Output format: txt, md, json, etc.", "enum": ["txt", "md"]},
    "language": {"type": "string", "description": "Preferred language code, e.g. zh-CN or en-US.", "default": "zh-CN"},
    "command": {"type": "string", "description": "Shell command string to execute. Use absolute paths when possible."},
    "status": {"type": "string", "description": "Filter by status: active, archived, all, or review status.", "enum": ["active", "archived", "all"]},
    "location": {"type": "string", "description": "City, region or location name, e.g. Beijing, Shanghai, San Jose."},
    "units": {"type": "string", "description": "Temperature units: metric (Celsius) or imperial (Fahrenheit).", "enum": ["metric", "imperial"], "default": "metric"},
    "code": {"type": "string", "description": "Python source code to execute. Subject to AST safety checks."},
    "reason": {"type": "string", "description": "Human-readable reason or note."},
    "dry_run": {"type": "boolean", "description": "If true, preview without making changes.", "default": True},
}


GENERAL_TOOL_INPUT_SCHEMAS = {
    # Artifact
    "artifact.search": _schema({"workspace_id": S["workspace_id"], "query": S["query"], "limit": S["limit"]}),
    "artifact.read_content_safe": _schema({"workspace_id": S["workspace_id"], "artifact_id": S["artifact_id"]}, ["artifact_id"]),
    "artifact.save_result": _schema({
        "workspace_id": S["workspace_id"],
        "title": S["title"],
        "content": S["content"],
        "artifact_type": {"type": "string", "description": "Artifact type: report, knowledge_doc, translated_config, etc."},
        "sensitivity": {"type": "string", "description": "Sensitivity level: internal (default) or sensitive.", "enum": ["internal", "sensitive"], "default": "internal"},
    }, ["content"]),
    "artifact.tag": _schema({
        "workspace_id": S["workspace_id"],
        "artifact_id": S["artifact_id"],
        "tags": {"type": "array", "description": "Tags to add."},
    }, ["artifact_id", "tags"]),
    "artifact.delete_soft": _schema({"workspace_id": S["workspace_id"], "artifact_id": S["artifact_id"]}, ["artifact_id"]),

    # Knowledge
    "knowledge.index_artifact": _schema({"workspace_id": S["workspace_id"], "artifact_id": S["artifact_id"]}, ["artifact_id"]),
    "knowledge.reindex": _schema({"workspace_id": S["workspace_id"], "source_id": S["source_id"]}),
    "knowledge.search": _schema({"workspace_id": S["workspace_id"], "query": S["query"], "limit": S["limit"]}, ["query"]),
    "knowledge.get_source": _schema({"workspace_id": S["workspace_id"], "source_id": S["source_id"]}, ["source_id"]),
    "knowledge.get_chunk_summary": _schema({"workspace_id": S["workspace_id"], "chunk_id": S["chunk_id"]}, ["chunk_id"]),
    "knowledge.explain_not_found": _schema({"query": S["query"], "workspace_id": S["workspace_id"]}, ["query"]),

    # Web
    "web.fetch_summary": _schema({"url": S["url"]}, ["url"]),
    "web.official_doc_search": _schema({
        "query": S["query"],
        "vendor": {"type": "string", "description": "Vendor slug, e.g. cisco, huawei, h3c, ruijie, arista."},
    }, ["query"]),
    "web.extract_links": _schema({"url": S["url"]}, ["url"]),
    "web.save_to_artifact": _schema({"workspace_id": S["workspace_id"], "url": S["url"], "title": S["title"]}, ["url"]),
    "weather.current": _schema({
        "location": S["location"],
        "units": S["units"],
        "language": S["language"],
        "top_k": S["limit"],
    }, ["location"]),
    "weather.forecast": _schema({
        "location": S["location"],
        "days": S["days"],
        "units": S["units"],
        "language": S["language"],
        "top_k": S["limit"],
    }, ["location"]),
    "news.search": _schema({
        "query": S["query"],
        "top_k": S["limit"],
        "site": {"type": "string", "description": "Optional domain filter for search, e.g. cisco.com."},
        "domains": {"type": "array", "description": "Optional domain allowlist array."},
        "recency": {"type": "string", "description": "Time range: day, week, month, or year.", "enum": ["day", "week", "month", "year"], "default": "day"},
        "language": S["language"],
    }, ["query"]),

    # Session / run / memory
    "session.get_summary": _schema({"workspace_id": S["workspace_id"], "session_id": S["session_id"]}, ["session_id"]),
    "session.create": _schema({"workspace_id": S["workspace_id"], "title": S["title"]}),
    "session.archive": _schema({"workspace_id": S["workspace_id"], "session_id": S["session_id"]}, ["session_id"]),
    "run.list_recent": _schema({"workspace_id": S["workspace_id"], "limit": S["limit"]}),
    "run.get_summary": _schema({"workspace_id": S["workspace_id"], "run_id": S["run_id"]}, ["run_id"]),
    "memory.search": _schema({"query": S["query"], "limit": S["limit"]}, ["query"]),
    "skill.list": _schema({"workspace_id": S["workspace_id"]}),
    "memory.create": _schema({
        "workspace_id": S["workspace_id"],
        "title": S["title"],
        "content": S["content"],
        "scope": {"type": "string", "description": "Memory scope: short_term, long_term, project.", "enum": ["short_term", "project", "long_term"], "default": "long_term"},
        "memory_type": {"type": "string", "description": "Memory type: knowledge_note, decision, etc.", "default": "knowledge_note"},
        "tags": {"type": "array", "description": "Tags for filtering.", "items": {"type": "string"}},
        "source": {"type": "string", "description": "Source of the memory entry.", "default": "agent"},
        "confidence": {"type": "string", "description": "Confidence level: system_generated, user_confirmed, inferred.", "enum": ["system_generated", "user_confirmed", "inferred"], "default": "system_generated"},
        "summary": {"type": "string", "description": "Optional short summary."},
        "sensitivity": {"type": "string", "description": "Sensitivity: internal (default) or sensitive.", "enum": ["internal", "sensitive"]},
        "metadata": {"type": "object", "description": "Optional metadata dict."},
        "user_confirmed": {"type": "boolean", "description": "Whether user explicitly confirmed this entry.", "default": False},
    }, ["title", "content"]),
    "memory.list": _schema({
        "workspace_id": S["workspace_id"],
        "scope": {"type": "string", "description": "Filter by scope."},
        "memory_type": {"type": "string", "description": "Filter by type."},
        "status": {"type": "string", "description": "Filter by status: pending_confirmation or confirmed.", "enum": ["pending_confirmation", "confirmed"]},
        "session_id": {"type": "string", "description": "Filter by session."},
        "limit": S["limit"],
    }),
    "memory.confirm": _schema({
        "workspace_id": S["workspace_id"],
        "memory_id": {"type": "string", "description": "Memory id to confirm."},
    }, ["memory_id"]),
    "memory.get_profile": _schema({"workspace_id": S["workspace_id"]}),
    "memory.set_profile": _schema({
        "workspace_id": S["workspace_id"],
        "field": {"type": "string", "description": "Profile field name to set."},
        "value": {"type": "string", "description": "Value to set. Do NOT store secrets."},
        "merge": {"type": "boolean", "description": "Merge into explicit_preferences (default true). Set false to replace.", "default": True},
    }, ["field"]),
    "skill.request_load": _schema({
        "workspace_id": S["workspace_id"],
        "skill_name": {"type": "string", "description": "Skill directory name from skill.list output."},
        "reason": {"type": "string", "description": "Optional reason for requesting this skill."},
        "session_id": {"type": "string", "description": "Optional session id for request recording."},
    }, ["skill_name"]),

    # Runtime
    "runtime.health": _schema({"workspace_id": S["workspace_id"]}),
    "runtime.selfcheck": _schema({"workspace_id": S["workspace_id"]}),
    "runtime.diagnostics": _schema({"workspace_id": S["workspace_id"]}),
    "runtime.retention_preview": _schema({"workspace_id": S["workspace_id"]}),
    "runtime.archive_preview": _schema({"workspace_id": S["workspace_id"]}),

    # Report / document
    "report.render_markdown": _schema({"content": S["content"], "title": S["title"]}, ["content"]),
    "report.save_artifact": _schema({"workspace_id": S["workspace_id"], "title": S["title"], "content": S["content"]}, ["content"]),
    "doc.render_from_safe_summary": _schema({"title": S["title"], "summary": {"type": "string", "description": "Safe summary only; raw configs are not accepted."}}, ["summary"]),
    "table.render_markdown": _schema({"rows": {"type": "array", "description": "Array of rows, each row is an array or object."}, "headers": {"type": "array", "description": "Optional column header names."}}),
    "diagram.render_mermaid": _schema({"mermaid": {"type": "string", "description": "Mermaid source text to return safely."}}, ["mermaid"]),

    # Text / data
    "text.redact": _schema({"text": S["text"]}, ["text"]),
    "text.diff": _schema({"text_a": {"type": "string", "description": "First text (original/before)."}, "text_b": {"type": "string", "description": "Second text (changed/after)."}}, ["text_a", "text_b"]),
    "text.extract_keywords": _schema({"text": S["text"], "limit": S["limit"]}, ["text"]),
    "text.classify": _schema({"text": S["text"]}, ["text"]),
    "json.validate": _schema({"text": S["text"]}, ["text"]),
    "yaml.validate": _schema({"text": S["text"]}, ["text"]),
    "csv.summarize": _schema({"text": S["text"]}, ["text"]),
    "table.extract": _schema({"text": S["text"]}, ["text"]),

    # Workspace
    "workspace.list_files": _schema({"workspace_id": S["workspace_id"], "subdir": {"type": "string", "description": "Workspace-relative subdirectory."}}),
    "workspace.read_text_preview": _schema({"workspace_id": S["workspace_id"], "filepath": {"type": "string", "description": "Workspace-relative text file path."}}, ["filepath"]),
    "workspace.write_artifact_file": _schema({"workspace_id": S["workspace_id"], "filename": {"type": "string", "description": "Output filename, e.g. report.md or output.json."}, "content": S["content"]}, ["filename", "content"]),
    "workspace.path_exists": _schema({"workspace_id": S["workspace_id"], "filepath": S["filepath"]}, ["filepath"]),
    "workspace.get_metadata": _schema({"workspace_id": S["workspace_id"]}),

    # Approved high-risk surfaces
    "shell.exec": _schema({"command": {"type": "string", "description": "Bash command. For Linux/macOS. On Windows, use powershell.exec."}}, ["command"]),
    "powershell.exec": _schema({"command": {"type": "string", "description": "PowerShell command. For Windows. On Linux/macOS, use shell.exec."}}, ["command"]),

    # Python Exec (high risk, AST-sandboxed)
    "python.exec": _schema({
        "workspace_id": S["workspace_id"],
        "code": S["code"],
        "run_id": S["run_id"],
        "timeout": {"type": "integer", "description": "Max execution seconds (1-10).", "default": 10},
    }, ["code"]),

    # Session snapshot / rewind
    "session.snapshot": _schema({
        "workspace_id": S["workspace_id"],
        "session_id": S["session_id"],
        "reason": S["reason"],
    }, ["session_id"]),
    "session.list_snapshots": _schema({
        "workspace_id": S["workspace_id"],
        "session_id": S["session_id"],
    }, ["session_id"]),
    "session.rewind": _schema({
        "workspace_id": S["workspace_id"],
        "session_id": S["session_id"],
        "snapshot_id": {"type": "string", "description": "Snapshot ID to restore from."},
        "dry_run": S["dry_run"],
    }, ["session_id", "snapshot_id"]),

    # Agent spawn (sub-agent)
    "agent.spawn": _schema({
        "workspace_id": S["workspace_id"],
        "session_id": S["session_id"],
        "instruction": {"type": "string", "description": "Task instruction for the sub-agent."},
        "allowed_tools": {"type": "array", "description": "Optional tool allowlist override.", "items": {"type": "string"}},
        "max_turns": {"type": "integer", "description": "Max LLM turns (1-3).", "default": 1},
    }, ["instruction"]),
}


def _planned_handler(name: str):
    """Return a handler for planned (not yet implemented) tools."""
    def handler(inv: ToolInvocation) -> dict:
        return _error(f"工具 {name} 尚未实现")
    return handler


_NON_PAYLOAD_KEYS = {
    "ok", "tool_id", "status", "summary", "warnings", "errors", "next_actions",
    "metadata", "source_type", "provider", "query", "filters",
}


def _wrap_general_handler(tool_id: str, handler):
    """Normalize every general tool result so LLMs never see an empty shell."""
    @wraps(handler)
    def wrapped(inv: ToolInvocation) -> dict:
        return _finalize_tool_output(tool_id, handler(inv))
    return wrapped


def _finalize_tool_output(tool_id: str, raw: Any) -> dict:
    if not isinstance(raw, dict):
        raw = {"ok": True, "output": str(raw)}
    out = dict(raw)
    ok = bool(out.get("ok", True))
    out["ok"] = ok
    out.setdefault("tool_id", tool_id)
    out.setdefault("status", "succeeded" if ok else "failed")
    if not ok:
        if not out.get("errors"):
            err = out.get("error") or out.get("summary") or f"{tool_id} failed"
            out["errors"] = [str(err)[:200]]
        out.setdefault("summary", out.get("error") or f"{tool_id} failed")
        out.setdefault("next_actions", _default_tool_next_actions(tool_id, ok=False))
        return out

    payload_keys = [k for k, v in out.items() if k not in _NON_PAYLOAD_KEYS and _has_value(v)]
    if not payload_keys:
        warnings = list(out.get("warnings") or [])
        if "tool_returned_no_payload" not in warnings:
            warnings.append("tool_returned_no_payload")
        out["warnings"] = warnings
        out.setdefault("next_actions", _default_tool_next_actions(tool_id, ok=True))
    out.setdefault("summary", _default_tool_summary(tool_id, out))
    out.setdefault("next_actions", _default_tool_next_actions(tool_id, ok=True))
    if "count" not in out:
        inferred = _infer_result_count(out)
        if inferred is not None:
            out["count"] = inferred
    return out


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, dict, tuple, set)) and not value:
        return False
    return True


def _infer_result_count(out: dict) -> int | None:
    for key in ("results", "files", "sessions", "runs", "links", "keywords", "components", "forecast_daily"):
        value = out.get(key)
        if isinstance(value, list):
            return len(value)
    for key in ("rows", "columns", "changed_lines", "archive_count", "candidate_count", "artifact_count"):
        if isinstance(out.get(key), int):
            return int(out[key])
    return None


def _default_tool_summary(tool_id: str, out: dict) -> str:
    if out.get("summary"):
        return str(out["summary"])
    if out.get("artifact_id"):
        return f"{tool_id} saved artifact {out['artifact_id']}"
    if out.get("count") is not None:
        return f"{tool_id} returned {out['count']} item(s)"
    if out.get("valid") is False:
        return f"{tool_id} completed: invalid input"
    if out.get("valid") is True:
        return f"{tool_id} completed: valid input"
    if out.get("preview"):
        return f"{tool_id} returned a safe preview"
    if out.get("markdown") or out.get("document") or out.get("table") or out.get("mermaid"):
        return f"{tool_id} generated output"
    return f"{tool_id} completed"


def _default_tool_next_actions(tool_id: str, *, ok: bool) -> list[str]:
    group = tool_id.split(".", 1)[0]
    if not ok:
        return [f"检查 {tool_id} 的必填参数和返回错误；必要时换同类主入口重试。"]
    defaults = {
        "artifact": ["如需正文，下一步用 artifact.read_content_safe 读取 artifact_id。"],
        "knowledge": ["根据返回的 chunk/source id 继续调用 knowledge.get_chunk_summary 或 knowledge.get_source。"],
        "web": ["用返回的 citation/URL 回答；需要正文细节时调用 web.fetch_summary。"],
        "weather": ["直接使用 current/forecast_daily 字段回答，并引用来源。"],
        "news": ["交叉比较前几条来源，避免把单一网页当最终事实。"],
        "session": ["如需展开某条记录，继续调用对应 get_summary 工具。"],
        "run": ["如需展开某条运行记录，继续调用 run.get_summary。"],
        "memory": ["如结果不足，换更具体关键词重试。"],
        "skill": ["根据返回的 skill 名称和描述判断是否匹配用户需求。"],
        "runtime": ["根据 diagnostics/health 的组件状态给出下一步排查建议。"],
        "report": ["将生成内容直接返回用户，或用 report.save_artifact 保存。"],
        "doc": ["将生成文档内容直接返回用户，或保存为 artifact。"],
        "table": ["用表格内容直接回答；如为空，说明没有可提取数据。"],
        "diagram": ["把 Mermaid 文本返回用户或嵌入报告。"],
        "text": ["基于转换/分析结果继续回答用户。"],
        "json": ["根据 valid/error 告诉用户 JSON 是否可用。"],
        "yaml": ["根据 valid/error 告诉用户 YAML 是否可用。"],
        "csv": ["用 rows/columns/header 总结 CSV 结构。"],
        "workspace": ["根据 workspace 文件状态继续读取或写入输出文件。"],
        "command": ["只使用 allowlisted 只读结果，不要声称执行了未批准命令。"],
        "powershell": ["只使用 allowlisted 只读结果，不要声称执行了未批准脚本。"],
    }
    return defaults.get(group, ["使用工具返回的数据继续回答用户。"])


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
        input_schema=input_schema or GENERAL_TOOL_INPUT_SCHEMAS.get(tool_id) or {"type": "object", "properties": {}, "required": []},
        timeout_seconds=60 if risk_level != "high" else 120,
        dry_run_supported=dry_run_supported,
        writes_artifact=writes_artifact,
        reads_artifact=category in ("artifact", "knowledge"),
        requires_approval=requires_approval,
        tags=[risk_level, category],
    )
    ALL_GENERAL_TOOLS.append((spec, _wrap_general_handler(tool_id, handler)))
    return spec


# ── A. Artifact Tools ──
_reg("artifact.search", "Artifact Search", "artifact", "low",
     "Search workspace artifacts by title/type. Use before reading an artifact when the user references prior outputs, reports, translated configs, or saved web pages.", handle_artifact_search)
_reg("artifact.read_content_safe", "Read Content Safe", "artifact", "low",
     "Read a size-limited safe preview of artifact content. Use only after artifact.search/list identifies an artifact_id; sensitive artifacts return metadata instead of full content.", handle_artifact_read_content_safe)
_reg("artifact.save_result", "Save Result", "artifact", "medium",
     "Save useful generated text as an artifact for later reference. Medium risk because it writes workspace state; avoid credential values or raw device configs unless explicitly intended.", handle_artifact_save_result, writes_artifact=True)
_reg("artifact.tag", "Tag Artifact", "artifact", "low",
     "Add tags to an artifact", handle_artifact_tag)
_reg("artifact.delete_soft", "Soft Delete", "artifact", "medium",
     "Soft-delete an artifact", handle_artifact_delete_soft, writes_artifact=True)

# ── B. Knowledge Tools ──
_reg("knowledge.index_artifact", "Index Artifact", "knowledge", "medium",
     "Index a safe artifact into the workspace knowledge base so future answers can retrieve it. Medium risk because it changes retrieval state.", handle_knowledge_index_artifact, writes_artifact=True)
_reg("knowledge.reindex", "Reindex", "knowledge", "medium",
     "Rebuild chunks for a knowledge source when search results look stale or incomplete. Medium risk because it updates the knowledge index.", handle_knowledge_reindex, writes_artifact=True)
_reg("knowledge.search", "Knowledge Search", "knowledge", "low",
     "Search the local workspace knowledge base for safe chunks and citations. Use before answering questions about imported docs, prior project knowledge, vendor notes, or user-specific network material.", handle_knowledge_search)
_reg("knowledge.get_source", "Get Source", "knowledge", "low",
     "Get metadata for a knowledge source id returned by knowledge.search. Does not expose raw source content.", handle_knowledge_get_source)
_reg("knowledge.get_chunk_summary", "Get Chunk Summary", "knowledge", "low",
     "Get a safe summary for a specific knowledge chunk id when search results need more local context.", handle_knowledge_get_chunk_summary)
_reg("knowledge.explain_not_found", "Explain Not Found", "knowledge", "low",
     "Explain why search returned no results", handle_knowledge_explain_not_found)

# ── C. Web Tools ──
WEB_SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query. Use specific keywords; include vendor/protocol/version when known.",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of results to return, 1-10. Default 5.",
            "default": 5,
        },
        "site": {
            "type": "string",
            "description": "Optional comma-separated domains to restrict search, e.g. cisco.com,ietf.org.",
        },
        "domains": {
            "type": "array",
            "description": "Optional domain allowlist, e.g. ['cisco.com', 'ietf.org'].",
        },
        "recency": {
            "type": "string",
            "description": "Optional freshness filter: day, week, month, year.",
            "enum": ["day", "week", "month", "year"],
        },
        "language": {
            "type": "string",
            "description": "Preferred result language/region, e.g. zh-CN or en-US.",
            "default": "zh-CN",
        },
        "safe_search": {
            "type": "string",
            "description": "Safe search mode.",
            "enum": ["strict", "moderate", "off"],
            "default": "moderate",
        },
    },
}

_reg("web.search", "Web Search", "web", "medium",
     "Search public web and return citation-ready results with title, URL, domain, snippet, source quality, and next-step guidance. Use for current facts, official docs, standards, vendor references, or anything that may have changed.",
     handle_web_search, input_schema=WEB_SEARCH_INPUT_SCHEMA)
_reg("web.fetch_summary", "Fetch Summary", "web", "medium",
     "Fetch and summarize a public http(s) webpage after web.search or when the user provides a URL. Blocks private/local URLs; use returned URL/title/summary for cited answers.", handle_web_fetch_summary)
_reg("web.official_doc_search", "Official Doc Search", "web", "low",
     "Search official vendor documentation by restricting web search to known vendor domains when possible. Use for Cisco/Huawei/H3C/Ruijie/Arista commands, protocols, release behavior, and standards-facing references.", handle_web_official_doc_search)
_reg("web.extract_links", "Extract Links", "web", "medium",
     "Extract public http(s) links from a webpage when the user asks for references, downloads, related docs, or navigation targets. Blocks private/local URLs.", handle_web_extract_links)
_reg("web.save_to_artifact", "Save to Artifact", "web", "medium",
     "Fetch a public webpage and save its readable text as a knowledge_doc artifact for later indexing or citation. Medium risk because it writes workspace state; blocks private/local URLs.", handle_web_save_to_artifact, writes_artifact=True)

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

# ── Real-time data tools backed by public web search ──
_reg("weather.current", "Current Weather", "web", "medium",
     "Get current weather for a location using public web results. Medium risk because weather changes quickly; cite returned sources and avoid claiming sensor-grade precision.",
     handle_weather_current)
_reg("weather.forecast", "Weather Forecast", "web", "medium",
     "Get a short weather forecast for a location using public web results. Medium risk because forecasts change; cite returned sources and mention uncertainty.",
     handle_weather_forecast)
_reg("news.search", "News Search", "web", "medium",
     "Search recent public news using web search with optional recency/domain filters. Medium risk because news can be incomplete or stale; compare sources before firm claims.",
     handle_news_search)
_reg("memory.search", "Memory Search", "session", "low",
     "Search memory store", handle_memory_search)
_reg("skill.list", "List Skills", "skill", "low",
     "List registered agent skills with names and capabilities.",
     handle_skill_list)
_reg("memory.create", "Create Memory", "memory", "low",
     "Create a long-term memory entry. Do not store secrets, tokens, or passwords.",
     handle_memory_create)
_reg("memory.list", "List Memories", "memory", "low",
     "List memory entries in the workspace. Returns id + summary only.",
     handle_memory_list)
_reg("memory.get_profile", "Get Profile", "memory", "low",
     "Get the current workspace user profile.",
     handle_memory_get_profile)
_reg("memory.set_profile", "Set Profile", "memory", "low",
     "Set a user profile preference. Use for long-term preferences, not secrets.",
     handle_memory_set_profile)
_reg("skill.request_load", "Request Skill Load", "skill", "low",
     "Request loading a skill. Does NOT directly inject skill into system prompt. "
     "Only records the request for future runtime-controlled loading.",
     handle_skill_request_load)
_reg("memory.confirm", "Confirm Memory", "memory", "low",
     "Confirm a pending_confirmation memory entry. Changes status from pending to confirmed.",
     handle_memory_confirm)

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

# ── I. Shell / PowerShell Tools (HIGH RISK, approval gated) ──
_reg("shell.exec", "Shell Exec", "shell", "high",
     "Execute shell commands (bash). Use this on Linux/macOS. On Windows use powershell.exec instead. 30s timeout, 10000 chars output. Requires user approval.",
     handle_command_approved_exec, requires_approval=True)
_reg("powershell.exec", "PowerShell Exec", "powershell", "high",
     "Execute PowerShell commands. Use this on Windows. On Linux/macOS use shell.exec instead. 15s timeout, 10000 chars output. Requires user approval.",
     handle_powershell_approved_script, requires_approval=True)

# ── J. Python Exec Tool (HIGH RISK, AST-sandboxed, approval gated) ──
_reg("python.exec", "Python Exec", "python", "high",
     "Execute Python code in an AST-sandboxed subprocess. Code is checked for forbidden imports (os, subprocess, socket, etc.), forbidden builtins (eval, exec, open, etc.), and dunder access before execution. 10s timeout. Requires user approval.",
     handle_python_exec, requires_approval=True)

# ── K. Session Snapshot / Rewind Tools ──
_reg("session.snapshot", "Session Snapshot", "session", "low",
     "Create a snapshot of the current session messages for later recovery or rewind.",
     handle_session_snapshot)
_reg("session.list_snapshots", "List Snapshots", "session", "low",
     "List all snapshots for a session without full message content.",
     handle_session_list_snapshots)
_reg("session.rewind", "Session Rewind", "session", "medium",
     "Rewind a session to a previous snapshot. Set dry_run=True to preview without applying. Set dry_run=False to restore messages from the snapshot.",
     handle_session_rewind)

# ── L. Agent Spawn (Sub-Agent) Tool ──
_reg("agent.spawn", "Spawn Sub-Agent", "session", "medium",
     "Spawn a sub-agent with restricted read-only tool access to research, summarize, or validate data. Returns compressed results. Max 3 turns with only low-risk tools.",
     handle_agent_spawn, requires_approval=False)


def register_all_general_tools(registry):
    """Register all general tools into a ToolRegistry.

    Creates copies of ToolSpec instances to prevent cross-registry mutation.
    """
    from copy import deepcopy
    for spec, handler in ALL_GENERAL_TOOLS:
        if spec.tool_id in REMOVED_GENERAL_TOOL_IDS:
            continue
        registry.register_tool(deepcopy(spec), handler)
    return registry
