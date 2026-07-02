from __future__ import annotations

from core.tools.schemas import ToolInvocation
from workspace.ids import validate_workspace_id
"""Web tool handlers — search, weather, news, fetch."""
import threading
import time

from core.tools.general_tools.shared import _caller_workspace, _contract, _error, _error_inv, _ok, _result, _safe_preview, _unavailable, _workspace_path
from core.tools.general_tools.shared_web import *  # has __all__ — 21 functions, all needed



_fetch_summary_cache_lock = threading.Lock()
_fetch_summary_cache: dict[str, tuple[float, dict]] = {}


def _ddgs_to_results(raw: list, domains: list, limit: int) -> list:
    """Convert ddgs raw results to standard web-result format."""
    seen = set()
    out = []
    for item in raw:
        url = (item.get("href") or item.get("url") or "").strip()
        if not url or url in seen:
            continue
        if domains:
            from urllib.parse import urlparse
            host = urlparse(url).netloc.lower()
            if not any(d in host for d in domains):
                continue
        seen.add(url)
        out.append({
            "title": (item.get("title") or "").strip(),
            "url": url,
            "snippet": (item.get("body") or "").strip(),
            "source": item.get("source", ""),
            "rank": len(out) + 1,
        })
        if len(out) >= limit:
            break
    return out


def handle_web_search(inv: ToolInvocation) -> dict:
    args = inv.arguments
    query = (args.get("query") or "").strip()
    limit = _coerce_int(args.get("top_k", args.get("limit", 5)), default=5, min_value=1, max_value=10)
    domains = _normalize_search_domains(args)
    recency = (args.get("recency") or "").strip().lower()
    language = (args.get("language") or "").strip() or "zh-CN"
    safe_search = (args.get("safe_search") or "moderate").strip().lower()
    if not query:
        return _error_inv(inv, "query is required")
    search_query = _build_web_search_query(query, domains)

    # ── v3.2.1 Primary: ddgs multi-backend search (Google → Bing → DDG → Brave) ──
    try:
        from ddgs import DDGS
        timelimit_map = {"day": "d", "week": "w", "month": "m", "year": "y"}
        backends = "google,bing,duckduckgo,brave"
        with DDGS(timeout=10) as ddgs:
            raw = ddgs.text(
                query=search_query,
                region="cn-zh" if language.startswith("zh") else "us-en",
                safesearch=safe_search,
                timelimit=timelimit_map.get(recency),
                max_results=min(limit * 3, 15),
                backend=backends,
            )
        if raw:
            results = _ddgs_to_results(raw, domains, limit)
            if results:
                guidance = _web_search_guidance(query, results, domains)
                return _ok(inv, "", {
                    "ok": True, "status": "succeeded",
                    "query": query, "search_query": search_query,
                    "results": results, "count": len(results),
                    "answer_hint": guidance["answer_hint"],
                    "results_markdown": _web_results_markdown(results),
                    "next_actions": guidance["next_actions"],
                    "summary": f"Found {len(results)} public web result(s) for '{query}'",
                    "provider": "ddgs",
                    "filters": {
                        "domains": domains, "recency": recency or "any",
                        "language": language, "safe_search": safe_search,
                    },
                })
    except Exception:
        pass  # Fall through to DuckDuckGo

    # ── Fallback: DuckDuckGo HTML scraping ──
    try:
        import requests
        results = []

        # ── DuckDuckGo HTML search (fallback when ddgs unavailable) ──
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
                return _ok(inv, "", {
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
            return _ok(inv, "", {
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
        return _result(inv, False, {
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
        return _result(inv, False, {
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


def _invoke_internal_web_search(inv: ToolInvocation, arguments: dict) -> dict:
    """Reuse the canonical web search implementation inside web.manage.

    This is an implementation detail of the merged ``web.manage`` tool. It
    deliberately does not invoke the removed public ``web.search`` id.
    """
    sub_inv = ToolInvocation(
        tool_id="web.manage",
        arguments=dict(arguments or {}),
        workspace_id=inv.workspace_id,
        session_id=inv.session_id,
        run_id=inv.run_id,
        task_id=inv.task_id,
        job_id=inv.job_id,
        dry_run=inv.dry_run,
        requested_by=inv.requested_by,
        approval_id=inv.approval_id,
    )
    return handle_web_search(sub_inv)


def handle_weather_current(inv: ToolInvocation) -> dict:
    """Current-weather lookup backed by structured public weather data."""
    args = inv.arguments
    location = (args.get("location") or "").strip()
    if not location:
        return _error_inv(inv, "location is required")
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
            tool_id="web.weather.current",
            location=location,
            units=units,
            language=language,
            structured=structured,
        )

    query = f"{location} current weather temperature humidity wind"
    result = _invoke_internal_web_search(inv, {
        "query": query,
        "top_k": _coerce_int(args.get("top_k", 5), default=5, min_value=1, max_value=10),
        "recency": args.get("recency", "day"),
        "language": language,
        "safe_search": args.get("safe_search", "moderate"),
    })
    out = {"ok": bool(result.get("ok")),
           "summary": result.get("summary", ""),
           "results": result.get("results", []),
           "errors": list(result.get("errors") or [])[:5],
           "warnings": list(result.get("warnings") or [])[:5]}
    return _decorate_realtime_search_result(
        out,
        tool_id="web.weather.current",
        query=query,
        tool_fallback="web.manage(action=search)",
        extra={"location": location, "units": units, "language": language},
    )

def handle_weather_forecast(inv: ToolInvocation) -> dict:
    """Weather forecast lookup backed by structured public weather data."""
    args = inv.arguments
    location = (args.get("location") or "").strip()
    if not location:
        return _error_inv(inv, "location is required")
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
            tool_id="web.weather.forecast",
            location=location,
            units=units,
            language=language,
            structured=structured,
        )

    query = f"{location} {days} day weather forecast"
    result = _invoke_internal_web_search(inv, {
        "query": query,
        "top_k": _coerce_int(args.get("top_k", 5), default=5, min_value=1, max_value=10),
        "recency": args.get("recency", "day"),
        "language": language,
        "safe_search": args.get("safe_search", "moderate"),
    })
    out = {"ok": bool(result.get("ok")),
           "summary": result.get("summary", ""),
           "results": result.get("results", []),
           "errors": list(result.get("errors") or [])[:5],
           "warnings": list(result.get("warnings") or [])[:5]}
    return _decorate_realtime_search_result(
        out,
        tool_id="web.weather.forecast",
        query=query,
        tool_fallback="web.manage(action=search)",
        extra={"location": location, "days": days, "units": units, "language": language},
    )

def handle_news_search(inv: ToolInvocation) -> dict:
    """News lookup backed by the public web search provider."""
    args = inv.arguments
    query = (args.get("query") or "").strip()
    if not query:
        return _error_inv(inv, "query is required")
    recency = (args.get("recency") or "day").strip().lower()
    language = (args.get("language") or "zh-CN").strip() or "zh-CN"
    result = _invoke_internal_web_search(inv, {
        "query": query,
        "top_k": _coerce_int(args.get("top_k", args.get("limit", 5)), default=5, min_value=1, max_value=10),
        "site": args.get("site", ""),
        "domains": args.get("domains", []),
        "recency": recency,
        "language": language,
        "safe_search": args.get("safe_search", "moderate"),
    })
    out = {"ok": bool(result.get("ok")),
           "summary": result.get("summary", ""),
           "results": result.get("results", []),
           "errors": list(result.get("errors") or [])[:5],
           "warnings": list(result.get("warnings") or [])[:5]}
    return _decorate_realtime_search_result(
        out,
        tool_id="web.manage",
        query=query,
        tool_fallback="web.manage(action=search)",
        extra={"recency": recency, "language": language},
    )

def handle_web_fetch_summary(inv: ToolInvocation) -> dict:
    args = inv.arguments
    url = (args.get("url") or "").strip()
    if not url:
        return _error_inv(inv, "url is required")
    if _is_private_url(url):
        return _error_inv(inv, "blocked: private/local network URLs not allowed")

    # ── DNS resolution safety check ──
    try:
        from urllib.parse import urlparse
        import socket
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname:
            resolved_ip = socket.gethostbyname(hostname)
            if _is_private_ip(resolved_ip):
                return _error_inv(inv, f"blocked: resolved IP {resolved_ip} is private/loopback")
    except Exception:
        pass  # DNS resolution failure doesn't block; proceed

    # ── Workspace-aware cache: same URL within 60s, workspace-scoped ──
    ws_id = inv.workspace_id or ""
    cache_key = f"{ws_id}::{url.lower().strip()}"
    _now = time.time()
    # P1 fix (round 7): cache lookups / writes now happen under a lock so
    # concurrent fetches don't race on dict mutation (RuntimeError on
    # "dictionary changed size during iteration") or duplicate the
    # oldest-entry eviction.
    with _fetch_summary_cache_lock:
        _cache = _fetch_summary_cache
        # Clean stale entries (60s TTL)
        for k in list(_cache.keys()):
            if _now - _cache[k][0] >= 60:
                del _cache[k]
        if cache_key in _cache:
            cached_at, cached_result = _cache[cache_key]
            if _now - cached_at < 60:
                return {
                    **cached_result,
                    "cached": True,
                    "cached_at": cached_at,
                }

    try:
        import requests
        headers = {
            "User-Agent": "NetworkAgent/0.2",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, timeout=10, headers=headers, allow_redirects=True)

        # ── Redirect re-validation ──
        redirect_url = url
        if resp.history:
            final_url = resp.url
            redirect_url = final_url
            if _is_private_url(final_url):
                return _error_inv(inv, "blocked: redirect target is private/local network URL")
            try:
                final_host = urlparse(final_url).hostname
                if final_host:
                    final_ip = socket.gethostbyname(final_host)
                    if _is_private_ip(final_ip):
                        return _error_inv(inv, f"blocked: redirect target resolved to private IP {final_ip}")
            except Exception:
                pass

        if resp.status_code != 200:
            return _error_inv(inv, f"HTTP {resp.status_code}")
        _fix_encoding(resp)
        html = resp.text
        text = _html_to_text(html)
        if not text:
            return _result(inv, False, {
                "status": "empty_readable_text",
                "url": url,
                "status_code": resp.status_code,
                "source_type": "web_fetch",
                "summary": "网页可访问，但没有抽取到可读正文。",
                "warnings": ["web_fetch_empty_readable_text"],
                "next_actions": ["换用更具体的公开网页 URL，或先用 web.extract_links 找正文页面。"],
            })
        result = _ok(inv, "", {
            "url": url,
            "title": _extract_title(html),
            "summary": _safe_preview(text, 800),
            "text_length": len(html),
            "status_code": resp.status_code,
            "source_type": "web_fetch",
            "redirected": url != redirect_url,
            "final_url": redirect_url if url != redirect_url else "",
        })
        # Cache the result under the same lock.
        with _fetch_summary_cache_lock:
            _fetch_summary_cache[cache_key] = (_now, result)
            if len(_fetch_summary_cache) > 100:
                oldest = min(
                    _fetch_summary_cache,
                    key=lambda k: _fetch_summary_cache[k][0],
                )
                del _fetch_summary_cache[oldest]
        return result
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_web_official_doc_search(inv: ToolInvocation) -> dict:
    args = inv.arguments
    query = (args.get("query") or "").strip()
    vendor = (args.get("vendor") or "").strip().lower()
    if not query:
        return _error_inv(inv, "query is required")
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
    result = _invoke_internal_web_search(inv, {
        "query": query,
        "domains": domains,
        "top_k": _coerce_int(args.get("top_k", 5), default=5, min_value=1, max_value=10),
        "language": args.get("language", "zh-CN"),
        "safe_search": args.get("safe_search", "moderate"),
    })
    out = {"ok": bool(result.get("ok")),
           "summary": result.get("summary", ""),
           "results": result.get("results", []),
           "errors": list(result.get("errors") or [])[:5],
           "warnings": list(result.get("warnings") or [])[:5]}
    result = dict(out)
    result["tool_id"] = "web.manage"
    result["source_type"] = "official_doc_search"
    result["vendor"] = vendor
    result["official_domains"] = domains
    result["doc_base_url"] = base
    result.setdefault("next_actions", [])
    result["next_actions"] = list(result["next_actions"]) + [
        "优先引用 official_or_primary 结果；如需要正文细节，再调用 web.manage(action=page)。",
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
    return _result(inv, bool(result.get("results")), result)

def handle_web_extract_links(inv: ToolInvocation) -> dict:
    args = inv.arguments
    url = (args.get("url") or "").strip()
    if not url:
        return _error_inv(inv, "url is required")
    if _is_private_url(url):
        return _error_inv(inv, "blocked: private/local network URLs not allowed")
    try:
        import requests
        headers = {
            "User-Agent": "NetworkAgent/0.2",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return _error_inv(inv, f"HTTP {resp.status_code}")
        _fix_encoding(resp)
        links = re.findall(r'href=["\'](https?://[^"\'\s]+)', resp.text)
        unique = list(dict.fromkeys(links))[:20]
        return _ok(inv, "", {"url": url, "links": unique, "count": len(unique)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_web_save_to_artifact(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = _caller_workspace(inv)
    url = (args.get("url") or "").strip()
    title = args.get("title", "web_save")
    if _is_private_url(url):
        return _error_inv(inv, "blocked: private/local network URLs not allowed")
    try:
        import requests
        headers = {
            "User-Agent": "NetworkAgent/0.2",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return _error_inv(inv, f"HTTP {resp.status_code}")
        _fix_encoding(resp)
        content = f"# {title}\n\nSource: {url}\n\n{_html_to_text(resp.text)}"
        from artifacts.store import save_artifact
        rec = save_artifact(workspace_id=ws, content=content, title=title,
                            artifact_type="knowledge_doc", sensitivity="internal")
        if not rec:
            return _error_inv(inv, "artifact save blocked or failed")
        return _ok(inv, "", {"artifact_id": rec.artifact_id, "title": title, "source_url": url})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

__all__ = ['handle_web_search', 'handle_weather_current', 'handle_weather_forecast', 'handle_news_search', 'handle_web_fetch_summary', 'handle_web_official_doc_search', 'handle_web_extract_links', 'handle_web_save_to_artifact']
