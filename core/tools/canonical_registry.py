"""v3.0 canonical-only tool registry.

This registry is the dispatch layer. Its public registration key is
``canonical_tool_id``. Each entry maps a canonical_tool_id to:

  - an internal handler_id (used by the runtime to call the
    implementation; never exposed publicly)
  - the underlying handler callable (existing handler that takes a
    ``ToolInvocation``)
  - input_schema, risk_level, requires_approval, callable_by_llm,
    enabled, description, permission_action

The handler_id is purely internal: it is not part of the public
catalog, LLM prompt, or frontend. If two canonical IDs share the same
implementation, the registration is duplicated (each canonical tool
gets its own spec).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import threading
import time

from agent.runtime.utils import now_iso
from core.tools.schemas import ToolSpec, ToolInvocation
from core.tools.registry_helpers import tool_keyword_score


def _inv_workspace(inv: ToolInvocation) -> str:
    args = inv.arguments or {}
    requested = str(args.get("workspace_id") or "").strip()
    caller = str(inv.workspace_id or "").strip()
    if caller and requested and caller != requested:
        raise ValueError(f"workspace_id mismatch: caller={caller!r}, requested={requested!r}")
    ws = caller or requested
    if not ws:
        raise ValueError("workspace_id is required")
    from workspace.ids import validate_workspace_id
    validate_workspace_id(ws)
    return ws


def _adapt(handler: Callable[[ToolInvocation], dict]) -> Callable[..., Any]:
    """Adapter: existing handlers take (inv: ToolInvocation)."""
    def _callable(*args: Any, **kwargs: Any) -> Any:
        if args and isinstance(args[0], ToolInvocation):
            return handler(args[0])
        inv = ToolInvocation(arguments=dict(kwargs), tool_id="")
        return handler(inv)
    return _callable


_BACKGROUND_JOBS: dict[str, dict[str, Any]] = {}
_BACKGROUND_LOCK = threading.Lock()


# ── v3.5 Merged tool routing wrappers ──

def _handle_web_search_merged(inv: ToolInvocation) -> dict:
    args = inv.arguments or {}
    source = str(args.get("source", "")).lower()
    if source == "docs":
        return handle_web_official_doc_search(inv)
    elif source == "news":
        return handle_news_search(inv)
    else:
        return handle_web_search(inv)




def _handle_knowledge_read_merged(inv: ToolInvocation) -> dict:
    args = inv.arguments or {}
    level = str(args.get("level", "")).lower()
    if level == "source":
        return handle_knowledge_get_source(inv)
    elif level == "parent":
        return _k_parent_read(inv)
    else:
        return handle_knowledge_get_chunk_summary(inv)


def _handle_memory_manage_merged(inv: ToolInvocation) -> dict:
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower()
    if action == "update":
        return handle_memory_update(inv)
    elif action == "confirm":
        return handle_memory_confirm(inv)
    elif action == "delete":
        return handle_memory_delete_soft(inv)
    elif action == "review":
        return handle_memory_review(inv)
    else:
        return handle_memory_create(inv)


def _handle_text_analyze_merged(inv: ToolInvocation) -> dict:
    """text.analyze — action=extract|redact|match."""
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower()
    if action == "extract":
        return handle_text_extract_entities(inv)
    elif action == "match":
        return _handle_text_match(inv)
    else:
        return handle_text_redact(inv)


def _handle_text_match(inv: ToolInvocation) -> dict:
    """action=match — regex pattern match."""
    import re
    args = inv.arguments or {}
    text = str(args.get("text", ""))
    pattern = str(args.get("pattern", ""))
    if not pattern:
        return {"ok": False, "error": "pattern is required"}
    if len(text) > 100000:
        return {"ok": False, "error": "text too large (max 100K)"}
    try:
        matches = re.findall(pattern, text, re.MULTILINE | re.DOTALL)
    except re.error as e:
        return {"ok": False, "error": f"invalid regex: {e}"}
    unique = list(dict.fromkeys(matches))
    return {
        "ok": True,
        "matches": unique[:100],
        "match_count": len(matches),
        "unique_count": len(unique),
        "pattern": pattern[:200],
        "_hint": f"找到 {len(matches)} 处匹配（{len(unique)} 个唯一值）。用 extract 提取结构化实体。",
    }


def _handle_session_snapshot_merged(inv: ToolInvocation) -> dict:
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower()
    if action == "list":
        return handle_session_list_snapshots(inv)
    else:
        return handle_session_snapshot(inv)


# ── v3.6 Merged tool routing wrappers ──

def _handle_exec_run_merged(inv: ToolInvocation) -> dict:
    """Route exec.run(target=X/ shell=X) to the right sub-handler."""
    args = inv.arguments or {}
    target = str(args.get("target", "")).lower()

    if target == "ssh":
        return _handler_network_ssh(inv)
    elif target == "telnet":
        return _handler_network_telnet(inv)
    else:
        # local: route to shell or powershell
        shell = str(args.get("shell", "")).lower()
        if shell == "powershell":
            return handle_powershell_approved_script(inv)
        else:
            return handle_command_approved_exec(inv)


# ── v3.9.2: 11 new merged handlers (Codex-style dispatch) ────────────
# Each dispatches arguments.action to the original per-action handler.
# The original per-action handlers above are kept (not deleted) because
# they may still be referenced from tests and from internal flows.

def _action(inv: ToolInvocation) -> tuple[str, dict]:
    """Return (action_string, arguments) for merged-tool dispatch."""
    args = inv.arguments or {}
    return str(args.get("action", "")).lower().strip(), args


def _handle_exec_merged(inv: ToolInvocation) -> dict:
    """exec.run — action=shell (default) | python | slash | background | stream."""
    action, _ = _action(inv)
    if action == "python":
        return handle_python_exec(inv)
    if action == "slash":
        return handle_slash_run(inv)
    if action == "background":
        return handle_background_exec(inv)
    if action == "stream":
        return handle_stream_exec(inv)
    # default: shell (local/ssh/telnet via target + shell)
    return _handle_exec_run_merged(inv)


def _handle_git_merged(inv: ToolInvocation) -> dict:
    """git.manage — action=status|log|diff|commit|push."""
    action, _ = _action(inv)
    return {
        "status": _handler_git_status,
        "log": _handler_git_log,
        "diff": _handler_git_diff,
        "commit": _handler_git_commit,
        "push": _handler_git_push,
    }.get(action, _handler_git_status)(inv)


def _handle_device_merged(inv: ToolInvocation) -> dict:
    """device.manage — action=list|get|add|delete|update|export."""
    action, _ = _action(inv)
    return {
        "list": _handler_cmdb_list_assets,
        "get": _handler_cmdb_get_asset,
        "add": _handler_cmdb_add_asset,
        "delete": _handler_cmdb_delete_asset,
        "update": _handler_cmdb_update_asset,
        "export": _handler_cmdb_export_assets,
    }.get(action, _handler_cmdb_list_assets)(inv)


def _handle_inspection_managed(inv: ToolInvocation) -> dict:
    """inspection.manage — CMDB-driven device health inspection.

    Dispatches to agent.modules.inspection.service. The runner is
    internal — credentials stay server-side and never cross the
    canonical_tool boundary. The LLM never sees device passwords.
    """
    from agent.modules.inspection import service as inspection_service

    ws = _inv_workspace(inv)
    action = str((inv.arguments or {}).get("action", "") or "").lower()
    args = dict(inv.arguments or {})

    if action == "run":
        try:
            scope = args.get("scope") or {}
            try:
                _mc = int(args.get("max_concurrency", 3) or 3)
            except (TypeError, ValueError):
                _mc = 3
            _mc = max(1, min(_mc, 16))
            from_args = str(args.get("created_by", "") or "")
            if from_args and from_args != "user":
                caller = from_args
            else:
                inv_caller = getattr(inv, "requested_by", "") or ""
                if inv_caller and inv_caller != "turn_runner":
                    caller = inv_caller
                else:
                    caller = "user"

            task = inspection_service.start_background_task(
                workspace_id=ws,
                profile_id="",
                scope=scope if isinstance(scope, dict) else {},
                created_by=caller,
                session_id=str(args.get("session_id", "") or ""),
                max_concurrency=_mc,
            )
        except Exception as exc:
            import logging as _il
            _il.getLogger(__name__).exception(
                "_handle_inspection_managed run failed",
            )
            return {"ok": False, "error": "inspection_run_failed: see server logs"}
        return {
            "ok": task.status != "failed" or not task.error.startswith("unknown_profile"),
            "task_id": task.task_id,
            "status": task.status,
            "profile_id": task.profile_id,
            "scope": {
                "region": task.scope.region, "location": task.scope.location,
                "search": getattr(task.scope, "search", ""),
                "type": task.scope.type, "vendor": task.scope.vendor,
                "tags": list(task.scope.tags),
                "asset_ids": list(task.scope.asset_ids), "limit": task.scope.limit,
            },
            "summary": {
                "total_devices": task.total_assets,
                "succeeded_devices": task.succeeded,
                "failed_devices": task.failed,
                "skipped_devices": task.skipped,
                "findings_total": task.warnings + task.criticals + task.infos,
                "findings_critical": task.criticals,
                "findings_warning": task.warnings,
                "findings_info": task.infos,
            },
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "tracking": task.tracking,
            "message": (
                "巡检任务已创建并在后台运行。用 get(task_id) 跟踪进度，"
                "到达 succeeded/partial 终态后，用 report 获取详细报告。"
            ),
            "error": task.error,
        }

    if action == "list":
        limit = int(args.get("limit", 50) or 50)
        items = inspection_service.list_tasks(ws, limit=limit)
        return {"ok": True, "items": items, "count": len(items)}

    if action == "get":
        task_id = str(args.get("task_id", "") or "")
        task = inspection_service.get_task(ws, task_id)
        if task is None:
            return {"ok": False, "error": "task_not_found"}
        from dataclasses import asdict
        return {"ok": True, "task": asdict(task), "tracking": task.tracking}

    if action == "cancel":
        task_id = str(args.get("task_id", "") or "")
        return inspection_service.cancel_task(ws, task_id)

    if action == "report":
        task_id = str(args.get("task_id", "") or "")
        fmt = str(args.get("format", "md") or "md").lower()
        return inspection_service.render_report(ws, task_id, fmt)

    return {"ok": False, "error": f"unknown_action: {action}"}


def _handle_browser_merged(inv: ToolInvocation) -> dict:
    """browser.manage — 16 action dispatcher."""
    action, _ = _action(inv)
    handlers = {
        "navigate": _handler_browser_navigate,
        "snapshot": _handler_browser_snapshot,
        "screenshot": _handler_browser_screenshot,
        "click": _handler_browser_click,
        "type": _handler_browser_type,
        "extract": _handler_browser_extract,
        "scroll": _handler_browser_scroll,
        "hover": _handler_browser_hover,
        "press_key": _handler_browser_press_key,
        "select_option": _handler_browser_select_option,
        "evaluate": _handler_browser_evaluate,
        "wait": _handler_browser_wait,
        "fill_form": _handler_browser_fill_form,
        "tabs": _handler_browser_tabs,
        "network": _handler_browser_network,
        "console": _handler_browser_console,
        "navigate_back": _handler_browser_navigate_back,
        "close": _handler_browser_close,
    }
    return handlers.get(action, _handler_browser_navigate)(inv)


def _handle_web_merged(inv: ToolInvocation) -> dict:
    """web.manage — action=search|fetch|weather|deep_search. list is a synonym for search."""
    action, _ = _action(inv)
    if action == "weather":
        return _weather_merged(inv)
    if action == "fetch":
        return _handle_web_fetch_v2(inv)
    if action == "deep_search":
        return _handle_web_deep_search(inv)
    # default: search (respects source=general|docs|news; also covers list)
    return _handle_web_search_merged(inv)


def _handle_web_fetch_v2(inv: ToolInvocation) -> dict:
    """action=fetch — extract clean content from a URL."""
    from core.tools.general_tools.web_content import fetch_and_extract

    args = inv.arguments or {}
    url = str(args.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "url is required"}

    extract_mode = str(args.get("extract_mode", "article")).strip()
    max_length = int(args.get("max_length", 15000) or 15000)
    timeout = int(args.get("timeout", 15) or 15)
    ws_id = _inv_workspace(inv)

    result = fetch_and_extract(
        url=url,
        extract_mode=extract_mode,
        max_length=max_length,
        timeout=timeout,
        workspace_id=ws_id,
    )
    description = str(args.get("description", "")).strip()
    if description:
        result["description"] = description
    return result


def _handle_web_deep_search(inv: ToolInvocation) -> dict:
    """action=deep_search — search + quality-filter + auto-fetch + aggregate.

    Three-layer progression:
      1. Pre-filter search results (dedup domains, exclude nav pages)
      2. Fetch with quality-aware fallback (article → full mode retry)
      3. Deepen search if effective articles < target (switch to depth=deep)
    """
    import re as _re
    from urllib.parse import urlparse as _urlparse
    from core.tools.general_tools.web_content import fetch_with_fallback

    args = inv.arguments or {}
    query = str(args.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "query is required"}

    max_fetch = min(int(args.get("max_fetch", 3) or 3), 5)
    ws_id = _inv_workspace(inv)

    # ── Layer 1: Search + Pre-filter ──────────────────────────────────
    search_result = _handle_web_search_merged(inv)
    if not search_result.get("ok"):
        return search_result

    raw_results = search_result.get("results", [])
    if not raw_results:
        return {
            "ok": False, "query": query,
            "error": "no search results to fetch",
            "search_results": [],
        }

    # 1.1: Dedup same-domain (max 2 per domain)
    domain_count: dict[str, int] = {}
    deduped: list[dict] = []
    for r in raw_results:
        url = r.get("url", "")
        if not url:
            continue
        dom = (_urlparse(url).hostname or "").lower()
        if dom:
            domain_count[dom] = domain_count.get(dom, 0) + 1
            if domain_count[dom] <= 2:
                deduped.append(r)

    # 1.2: Exclude navigation/landing page URLs by structural heuristics
    NAV_PATTERNS = [
        r'/$',
        r'/index\.(html?|php|jsp|asp)$',
    ]
    candidates = []
    for r in deduped:
        url = r.get("url", "")
        if any(_re.search(p, url, _re.I) for p in NAV_PATTERNS):
            continue
        candidates.append(r)
    if not candidates:
        candidates = deduped

    pool = candidates[: max_fetch * 2]

    # ── Layer 2: Fetch with quality scoring ───────────────────────────
    sources: list[dict] = []
    for r in pool:
        url = r.get("url", "")
        if not url:
            continue
        fetch_result = fetch_with_fallback(
            url=url, workspace_id=ws_id, max_length=20000, timeout=15,
        )
        cl = fetch_result.get("content_length", 0)
        score = fetch_result.get("quality_score", 0)
        sources.append({
            "url": url,
            "title": r.get("title", fetch_result.get("title", "")),
            "snippet": r.get("snippet", ""),
            "content": fetch_result.get("content", "") if cl > 0 else "",
            "content_length": cl,
            "fetched": fetch_result.get("ok", False) and cl > 0,
            "fetch_error": fetch_result.get("error", ""),
            "quality_score": score,
            "extraction_method": fetch_result.get("extraction_method", ""),
        })
        # Stop early if we have enough high-quality sources
        if score >= 2 and len([s for s in sources if s.get("quality_score", 0) >= 2]) >= max_fetch:
            break

    good_sources = [s for s in sources if s.get("quality_score", 0) >= 2]

    # ── Layer 3: Deepen search if insufficient ───────────────────────
    if len(good_sources) < max_fetch and len(sources) < max_fetch * 2:
        inv_deep = ToolInvocation(
            tool_id=inv.tool_id,
            arguments={**inv.arguments, "depth": "deep", "max_results": 20},
            workspace_id=inv.workspace_id,
            requested_by=inv.requested_by,
        )
        try:
            search2 = _handle_web_search_merged(inv_deep)
            results2 = search2.get("results", [])
            seen_urls = {s["url"] for s in sources}
            for r in results2:
                if len(good_sources) >= max_fetch:
                    break
                url = r.get("url", "")
                if not url or url in seen_urls:
                    continue
                dom = (_urlparse(url).hostname or "").lower()
                # Quick pre-filter for deep search results too
                if any(_re.search(p, url, _re.I) for p in NAV_PATTERNS):
                    continue
                fetch_result = fetch_with_fallback(
                    url=url, workspace_id=ws_id, max_length=20000, timeout=15,
                )
                cl = fetch_result.get("content_length", 0)
                score = fetch_result.get("quality_score", 0)
                seen_urls.add(url)
                sources.append({
                    "url": url,
                    "title": r.get("title", fetch_result.get("title", "")),
                    "snippet": r.get("snippet", ""),
                    "content": fetch_result.get("content", "") if cl > 0 else "",
                    "content_length": cl,
                    "fetched": fetch_result.get("ok", False) and cl > 0,
                    "fetch_error": fetch_result.get("error", ""),
                    "quality_score": score,
                    "extraction_method": fetch_result.get("extraction_method", ""),
                    "source": "deepened_search",
                })
                if score >= 2:
                    good_sources = [s for s in sources if s.get("quality_score", 0) >= 2]
        except Exception:
            pass

    # ── Build result ─────────────────────────────────────────────────
    fetched_count = sum(1 for s in sources if s["fetched"])
    total_cl = sum(s["content_length"] for s in sources)
    high_quality_count = len([s for s in sources if s.get("quality_score", 0) >= 2])

    return {
        "ok": len(sources) > 0,
        "query": query,
        "search_provider": search_result.get("provider", "unknown"),
        "sources": sources,
        "fetched_count": fetched_count,
        "high_quality_count": high_quality_count,
        "total_content_length": total_cl,
        "search_query": search_result.get("search_query", query),
        "summary": (
            f"Deep search: '{query}', "
            f"fetched {fetched_count}/{len(sources)} pages "
            f"({total_cl} chars, {high_quality_count} high-quality)."
        ),
        "_synthesis_guidance": (
            "综合所有 source 的 content 形成答案。"
            "优先使用 quality_score>=2 的高质量来源。"
            "对每个关键点注明来源URL。如果多个来源说法一致，可以合并引用。"
            "如果某篇 fetched=false 或 quality_score=0，说明该源未能有效读取，不要编造其内容。"
        ),
        "_actions": [
            "综合各 source 的 content 回答，注明引用URL。",
            "优先使用 quality_score>=2 的来源，跳过 quality_score=0 的无用源。",
            "如某篇关键内容不完整，用 action=fetch 单独抓取。",
        ],
    }


def _handle_data_merged(inv: ToolInvocation) -> dict:
    """data.manage — action=parse|stats|distinct|aggregate|filter|sort|render|pivot|join."""
    from core.tools.general_tools.data_engine import (
        data_parse, data_stats, data_distinct, data_aggregate,
        data_filter, data_sort, data_render, data_pivot, data_join,
    )
    action, args = _action(inv)
    text = str(args.get("text", ""))
    rows = args.get("rows")

    if action == "parse":
        return data_parse(text=text, rows=rows)
    if action == "stats":
        return data_stats(text=text, rows=rows)
    if action == "distinct":
        return data_distinct(text=text, rows=rows, column=str(args.get("column", "")))
    if action == "aggregate":
        return data_aggregate(
            text=text, rows=rows,
            group_by=args.get("group_by"),
            metrics=args.get("metrics"),
        )
    if action == "filter":
        return data_filter(
            text=text, rows=rows,
            conditions=args.get("conditions"),
            max_rows=int(args.get("max_rows", 50) or 50),
        )
    if action == "sort":
        return data_sort(
            text=text, rows=rows,
            by=args.get("by", ""),
            order=str(args.get("order", "asc")),
            max_rows=int(args.get("max_rows", 50) or 50),
        )
    if action == "render":
        return data_render(
            text=text, rows=rows,
            output=str(args.get("output", "markdown")),
            max_rows=int(args.get("max_rows", 50) or 50),
        )
    if action == "pivot":
        return data_pivot(
            text=text, rows=rows,
            index=str(args.get("index", "")),
            columns=str(args.get("pivot_columns", "")),
            values=str(args.get("pivot_values", "")),
            aggfunc=str(args.get("aggfunc", "sum")),
        )
    if action == "join":
        return data_join(
            text=text, rows=rows,
            right_text=str(args.get("right_text", "")),
            right_rows=args.get("right_rows"),
            on=str(args.get("on", "")),
            how=str(args.get("how", "inner")),
        )
    # default: parse
    return data_parse(text=text, rows=rows)


def _handle_report_merged(inv: ToolInvocation) -> dict:
    """report.manage — action=save|diff|document."""
    action, _ = _action(inv)
    if action == "diff":
        return _handle_report_diff(inv)
    if action == "document":
        return _handle_report_document(inv)
    # default: save
    return _handle_report_save(inv)


def _handle_report_save(inv: ToolInvocation) -> dict:
    """action=save — persist content as artifact."""
    ws = _inv_workspace(inv)
    args = inv.arguments or {}
    title = str(args.get("title", "report"))
    content = str(args.get("content", ""))
    artifact_type = str(args.get("artifact_type", "report"))
    if not content.strip():
        return {"ok": False, "error": "content is required"}
    try:
        from artifacts.store import save_artifact
        rec = save_artifact(
            workspace_id=ws, content=content, title=title,
            artifact_type=artifact_type, sensitivity="internal",
        )
        if not rec:
            return {"ok": False, "error": "artifact save blocked or failed"}
        return {
            "ok": True, "artifact_id": rec.artifact_id,
            "title": title, "artifact_type": artifact_type,
            "_hint": f"已保存为 artifact {rec.artifact_id}。用 system.manage 查询，或用 diff 对比。",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _handle_report_diff(inv: ToolInvocation) -> dict:
    """action=diff — compare texts or artifacts."""
    args = inv.arguments or {}
    text_a = str(args.get("text_a", "")).strip()
    text_b = str(args.get("text_b", "")).strip()
    aid_a = str(args.get("artifact_id_a", "")).strip()
    aid_b = str(args.get("artifact_id_b", "")).strip()

    # If artifact IDs provided, read their content
    if aid_a and not text_a:
        try:
            from core.tools.general_tools.file_tools import handle_artifact_read_content_safe
            res = handle_artifact_read_content_safe(ToolInvocation(
                arguments={"workspace_id": _inv_workspace(inv), "artifact_id": aid_a},
            ))
            text_a = res.get("content", "") if isinstance(res, dict) else ""
        except Exception:
            logger.debug("artifact diff: failed to read artifact_id_a=%s", aid_a, exc_info=True)
    if aid_b and not text_b:
        try:
            from core.tools.general_tools.file_tools import handle_artifact_read_content_safe
            res = handle_artifact_read_content_safe(ToolInvocation(
                arguments={"workspace_id": _inv_workspace(inv), "artifact_id": aid_b},
            ))
            text_b = res.get("content", "") if isinstance(res, dict) else ""
        except Exception:
            logger.debug("artifact diff: failed to read artifact_id_b=%s", aid_b, exc_info=True)

    if not text_a and not text_b:
        return {"ok": False, "error": "text_a/text_b or artifact_id_a/artifact_id_b required"}

    import difflib
    differ = difflib.unified_diff(
        text_a.splitlines(keepends=True),
        text_b.splitlines(keepends=True),
        fromfile=aid_a or "left",
        tofile=aid_b or "right",
        n=3,
    )
    diff_lines = list(differ)[:200]
    diff_text = "".join(diff_lines)

    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    return {
        "ok": True,
        "diff": diff_text[:10000],
        "lines_added": added,
        "lines_removed": removed,
        "total_diff_lines": len(diff_lines),
        "_hint": f"差异：+{added}行 -{removed}行。",
    }


def _handle_report_document(inv: ToolInvocation) -> dict:
    """action=document — generate complete HTML document with TOC + styling."""
    args = inv.arguments or {}
    title = str(args.get("title", "Document"))
    sections = args.get("sections", [])
    style = str(args.get("style", "default"))

    if not sections:
        return {"ok": False, "error": "sections is required: [{heading, content}, ...]"}

    # Build TOC
    toc_items = []
    body_items = []
    for i, sec in enumerate(sections):
        h = str(sec.get("heading", f"Section {i+1}"))
        c = str(sec.get("content", ""))
        anchor = f"s{i}"
        toc_items.append(f'<li><a href="#{anchor}">{h}</a></li>')
        body_items.append(f'<section id="{anchor}"><h2>{h}</h2>\n{_md_to_html(c)}</section>')

    # CSS themes
    themes = {
        "default": "body{font:16px/1.6 system-ui,sans-serif;max-width:800px;margin:40px auto;color:#222}"
                   "h1{border-bottom:2px solid #0052d9;padding-bottom:12px}"
                   "h2{color:#0052d9;margin-top:32px}"
                   "pre,code{background:#f5f5f5;padding:2px 6px;border-radius:4px}"
                   "pre{padding:16px;overflow-x:auto}"
                   "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px}"
                   "#toc{background:#f9f9f9;padding:16px 24px;border-radius:8px;margin-bottom:32px}",
        "dark": "body{font:16px/1.6 system-ui,sans-serif;max-width:800px;margin:40px auto;background:#1a1a2e;color:#e0e0e0}"
                  "h1{color:#7c9fff;border-bottom:2px solid #7c9fff;padding-bottom:12px}"
                  "h2{color:#7c9fff;margin-top:32px}"
                  "pre,code{background:#16213e;padding:2px 6px;border-radius:4px;color:#a8d8ff}"
                  "pre{padding:16px;overflow-x:auto}"
                  "table{border-collapse:collapse;width:100%}th,td{border:1px solid #444;padding:8px}"
                  "#toc{background:#16213e;padding:16px 24px;border-radius:8px;margin-bottom:32px}",
        "minimal": "body{font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:32px auto;color:#333}"
                   "h1{font-size:1.8em}h2{font-size:1.3em;margin-top:24px}"
                   "pre,code{font-size:0.9em;background:#f8f8f8;padding:2px 4px}"
                   "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px}"
                   "#toc{border-left:3px solid #999;padding-left:16px;margin-bottom:24px}",
    }
    css = themes.get(style, themes["default"])

    html = (
        "<!DOCTYPE html>\n<html lang='zh-CN'>\n<head>\n"
        "<meta charset='utf-8'>\n"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>\n"
        f"<title>{_html_escape(title)}</title>\n"
        f"<style>{css}</style>\n"
        "</head>\n<body>\n"
        f"<h1>{_html_escape(title)}</h1>\n"
        f"<nav id='toc'><h3>目录</h3><ul>{''.join(toc_items)}</ul></nav>\n"
        f"{''.join(body_items)}\n"
        "</body>\n</html>"
    )

    # Save as artifact
    ws = _inv_workspace(inv)
    try:
        from artifacts.store import save_artifact
        rec = save_artifact(
            workspace_id=ws, content=html, title=title,
            artifact_type="document", sensitivity="internal",
        )
        return {
            "ok": True,
            "artifact_id": rec.artifact_id,
            "title": title,
            "section_count": len(sections),
            "format": "html",
            "style": style,
            "html_preview": html[:2000],
            "_hint": f"文档已生成并保存为 artifact {rec.artifact_id}。{len(sections)} 个章节，含目录。",
        }
    except Exception as e:
        # Fallback: return raw HTML without saving
        return {
            "ok": True, "title": title, "section_count": len(sections),
            "format": "html", "html": html[:50000],
            "_hint": "已生成 HTML 文档（未保存为 artifact）。",
            "save_note": str(e)[:100],
        }


def _html_escape(s: str) -> str:
    import html
    return html.escape(s, quote=False)


def _md_to_html(text: str) -> str:
    """Convert basic Markdown to HTML inline."""
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    # Code blocks
    text = re.sub(r'```(\w*)\n(.*?)```', r'<pre><code>\2</code></pre>', text, flags=re.S)
    # Paragraphs
    paras = text.split('\n\n')
    result = []
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if p.startswith('<pre') or p.startswith('<table'):
            result.append(p)
        else:
            result.append(f'<p>{p.replace(chr(10), "<br>")}</p>')
    return '\n'.join(result) + "\n"


def _handle_knowledge_merged(inv: ToolInvocation) -> dict:
    """knowledge.manage — action=search|read|list|chunk|import|manage."""
    action, _ = _action(inv)
    return {
        "search": handle_knowledge_search,
        "read": _handle_knowledge_read_merged,
        "list": _k_source_list,
        "chunk": _k_chunk_list,
        "manage": _k_source_manage,
        "import": _handle_knowledge_import_merged,
    }.get(action, handle_knowledge_search)(inv)


def _handle_memory_merged(inv: ToolInvocation) -> dict:
    """memory.manage — action=search|create|update|confirm|delete|review|profile_get|profile_set."""
    action, _ = _action(inv)
    return {
        "search": handle_memory_search_merged,
        "create": _handle_memory_manage_merged,
        "update": _handle_memory_manage_merged,
        "confirm": _handle_memory_manage_merged,
        "delete": _handle_memory_manage_merged,
        "review": _handle_memory_manage_merged,
        "profile_get": handle_memory_profile_merged,
        "profile_set": handle_memory_profile_merged,
    }.get(action, _handle_memory_manage_merged)(inv)


def _handle_skill_merged(inv: ToolInvocation) -> dict:
    """skill.manage — action=list|search|load|inspect."""
    action, _ = _action(inv)
    return {
        "list": handle_skill_list,
        "search": handle_skill_find,
        "load": handle_skill_load,
        "inspect": handle_skill_inspect,
    }.get(action, handle_skill_list)(inv)


def _handle_agent_merged(inv: ToolInvocation) -> dict:
    """agent.manage — action=list|spawn|get|cancel|status."""
    action, _ = _action(inv)
    return {
        "list": handle_agent_list,
        "spawn": handle_agent_spawn,
        "get": handle_agent_get_result,
        "cancel": handle_agent_cancel,
        "status": handle_agent_status,
    }.get(action, handle_agent_list)(inv)


def _handle_system_merged(inv: ToolInvocation) -> dict:
    """system.manage — 13 actions for diagnostics/run/session/review."""
    action, _ = _action(inv)
    return {
        "diagnostics": handle_runtime_diagnostics,
        "health": handle_runtime_health,
        "selfcheck": handle_runtime_selfcheck,
        "local_info": handle_runtime_local_info,
        "tasks": handle_runtime_tasks,
        "audit_log": handle_audit_log_query,
        "run_get": _handle_system_run_get_merged,
        "session_get": _handle_system_session_get_merged,
        "session_checkpoint": handle_session_checkpoint,
        "session_rewind": handle_session_rewind,
        "session_export": handle_session_export,
        "session_snapshot": _handle_session_snapshot_merged,
        "review_list": _review_item_list,
        "review_update": _review_item_update,
    }.get(action, handle_runtime_diagnostics)(inv)


# ─── workspace.file merged handler ─────────────────────────────────────
# action=list|read|read_image|edit|patch|write_artifact|glob|delete
# Removed tool IDs are intentionally absent from the LLM namespace.
def _handle_workspace_file_merged(inv: ToolInvocation) -> dict:
    """Route workspace.file(action=X) to the right sub-handler."""
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower().strip()

    if action == "list":
        return handle_file_list_merged(inv)
    elif action == "read":
        return handle_file_read(inv)
    elif action == "read_image":
        return handle_file_read_image(inv)
    elif action == "edit":
        return handle_file_edit(inv)
    elif action == "patch":
        return handle_file_patch(inv)
    elif action == "write_artifact":
        return handle_ws_write_artifact_file(inv)
    elif action == "glob":
        return handle_file_glob(inv)
    elif action == "delete":
        return handle_file_delete(inv)
    else:
        return {
            "ok": False,
            "error": f"workspace.file: unknown action={action!r}. "
                     f"Valid actions: list, read, read_image, edit, patch, write_artifact, glob, delete",
        }


# ─── v3.9.1: workspace.artifact merged handler ────────────────────────
# 合并 7 个原 tool: list / read / save / tag / delete_soft / diff / export
# dispatch 字段: action (list|read|save|tag|delete|diff|export)
def _handle_workspace_artifact_merged(inv: ToolInvocation) -> dict:
    """Route workspace.artifact(action=X) to the right sub-handler."""
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower().strip()

    if action == "list":
        return _ws_artifact_list_merged(inv)
    elif action == "read":
        return handle_artifact_read_content_safe(inv)
    elif action == "save":
        return handle_artifact_save_result(inv)
    elif action == "tag":
        return handle_artifact_tag(inv)
    elif action == "delete":
        return handle_artifact_delete_soft(inv)
    elif not action:
        # Default to list when no explicit action is provided
        return _ws_artifact_list_merged(inv)
    else:
        return {
            "ok": False,
            "error": f"workspace.artifact: unknown action={action!r}. "
                     f"Valid actions: list, read, save, tag, delete",
        }


def _handle_workspace_filestore_merged(inv: ToolInvocation) -> dict:
    """Route workspace.filestore(action=X) to the right FileStore handler.

    Supports FileStore references and workspace-path imports.
    """
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower().strip()

    if action == "references":
        from core.tools.general_tools.filestore_tools import handle_file_references

        file_id = str(args.get("file_id") or args.get("filepath") or "").strip()
        return handle_file_references(inv, file_id=file_id)
    elif action == "import":
        from core.tools.general_tools.filestore_tools import handle_file_import_workspace_path

        return handle_file_import_workspace_path(
            inv,
            filepath=str(args.get("filepath") or "").strip(),
        )
    else:
        return {
            "ok": False,
            "error": f"workspace.filestore: unknown action={action!r}. "
                     f"Valid actions: references, import",
        }


def _handle_system_run_get_merged(inv: ToolInvocation) -> dict:
    """Route system.run.get(list=true|false) to list or summary handler."""
    args = inv.arguments or {}
    if args.get("list"):
        return handle_run_list_recent(inv)
    else:
        return handle_run_get_summary(inv)


def _handle_system_session_get_merged(inv: ToolInvocation) -> dict:
    """Route system.session.get(list=true|false) to list or summary handler."""
    args = inv.arguments or {}
    if args.get("list"):
        return handle_session_list(inv)
    else:
        return handle_session_get_summary(inv)


def _handle_memory_profile_merged(inv: ToolInvocation) -> dict:
    """Route memory.manage(action=profile_get|profile_set) to the right handler."""
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower()
    if action == "set":
        return handle_memory_set_profile(inv)
    else:
        return handle_memory_get_profile(inv)


def _handle_memory_search_merged(inv: ToolInvocation) -> dict:
    """Route memory.manage(action=search|list) to the right handler."""
    args = inv.arguments or {}
    if args.get("list"):
        return handle_memory_list(inv)
    else:
        return handle_memory_search(inv)




def _handle_knowledge_import_merged(inv: ToolInvocation) -> dict:
    """Route knowledge.import with artifact_id to artifact import handler."""
    args = inv.arguments or {}
    if args.get("artifact_id"):
        return handle_knowledge_import_artifact(inv)
    else:
        return handle_knowledge_import(inv)


@dataclass(frozen=True)
class CanonicalToolEntry:
    canonical_tool_id: str
    handler: Callable[..., Any]
    input_schema: dict[str, Any]
    risk_level: str = "low"
    requires_approval: bool = False
    permission_action: str = ""
    description: str = ""
    callable_by_llm: bool = True  # v3.10: mark internal sub-tools False

    @property
    def handler_id(self) -> str:
        """Internal dispatch key. By default, equals canonical_tool_id."""
        return self.canonical_tool_id


# ----------------------------------------------------------------------
# Handler imports.
# ----------------------------------------------------------------------

from core.tools.general_tools.file_tools import (
    handle_file_list,
    handle_file_exists,
    handle_file_list_merged,
    handle_file_read,
    handle_file_read_image,
    handle_file_edit,
    handle_file_patch,
    handle_ws_list_files,
    handle_ws_read_text_preview,
    handle_ws_write_artifact_file,
    handle_ws_path_exists,
    handle_ws_get_metadata,
)
from core.tools.general_tools.artifact_tools import (
    handle_artifact_search,
    handle_artifact_read_content_safe,
    handle_artifact_save_result,
    handle_artifact_tag,
    handle_artifact_delete_soft,
)
from core.tools.general_tools.web_tools import (
    handle_web_search,
    handle_weather_current,
    handle_weather_forecast,
    handle_news_search,
    handle_web_official_doc_search,
)
from core.tools.general_tools.session_tools import (
    handle_session_list,
    handle_session_get_summary,
    handle_session_get_merged,
    handle_run_list_recent,
    handle_run_get_summary,
    handle_run_get_merged,
    handle_session_snapshot,
    handle_session_list_snapshots,
    handle_session_rewind,
    handle_session_checkpoint,
    handle_session_export,
)
from core.tools.general_tools.memory_tools import (
    handle_memory_search,
    handle_memory_search_merged,
    handle_memory_create,
    handle_memory_list,
    handle_memory_confirm,
    handle_memory_review,
    handle_memory_get_profile,
    handle_memory_set_profile,
    handle_memory_profile_merged,
    handle_memory_update,
    handle_memory_delete_soft,
)
from core.tools.general_tools.skill_tools import (
    handle_skill_list,
    handle_skill_load,
    handle_skill_find,
    handle_skill_inspect,
    handle_skill_create,
    handle_skill_install,
)
from core.tools.general_tools.pdf_tools import handle_pdf_extract_text
from core.tools.general_tools.command_tools import (
    handle_command_approved_exec,
    handle_powershell_approved_script,
    handle_slash_run,
    handle_python_exec,
)
from core.tools.general_tools.agent_tools import (
    handle_agent_spawn,
    handle_agent_list,
    handle_agent_get_result,
    handle_agent_cancel,
    handle_agent_status,
)
from core.tools.general_tools.runtime_tools import (
    handle_knowledge_search,
    handle_knowledge_get_source,
    handle_knowledge_get_chunk_summary,
    handle_runtime_health,
    handle_runtime_selfcheck,
    handle_runtime_diagnostics,
    handle_runtime_local_info,
    handle_runtime_retention_preview,
    handle_runtime_archive_preview,
    handle_text_diff,
    handle_text_redact,
)
import logging



logger = logging.getLogger(__name__)

# ── Output truncation (max chars per execution result) ─────────────
_OUTPUT_TRUNCATE = 10000  # matches _SHELL_MAX_OUTPUT in shared.py

def _safe_int(value, default: int = 0) -> int:
    """Convert value to int safely, returning default on failure."""
    try:
        return int(value or default)
    except (ValueError, TypeError):
        return default


# ── Directory-level tool handlers ────────────────────────────────────

# ── v3.4: Git / Code / Browser handlers ──

def _handler_git_status(inv: ToolInvocation) -> dict:
    from agent.modules.git.core import git_status
    args = inv.arguments or {}
    return git_status(str(args.get("repo_path", ".")))

def _handler_git_diff(inv: ToolInvocation) -> dict:
    from agent.modules.git.core import git_diff
    args = inv.arguments or {}
    return git_diff(str(args.get("repo_path", ".")), bool(args.get("staged", False)), str(args.get("file_path", "")))

def _handler_git_log(inv: ToolInvocation) -> dict:
    from agent.modules.git.core import git_log
    args = inv.arguments or {}
    return git_log(str(args.get("repo_path", ".")), _safe_int(args.get("n", 10)), str(args.get("file_path", "")))

def _handler_git_commit(inv: ToolInvocation) -> dict:
    from agent.modules.git.core import git_commit
    args = inv.arguments or {}
    msg = str(args.get("message", ""))
    if not msg:
        return {"ok": False, "error": "message is required"}
    files = args.get("files")
    files = args.get("files")
    if isinstance(files, list):
        return git_commit(str(args.get("repo_path", ".")), msg, files)
    return git_commit(str(args.get("repo_path", ".")), msg, None)

def _handler_git_push(inv: ToolInvocation) -> dict:
    from agent.modules.git.core import git_push
    args = inv.arguments or {}
    return git_push(str(args.get("repo_path", ".")), str(args.get("remote", "origin")), str(args.get("branch", "")))

def _handler_code_search(inv: ToolInvocation) -> dict:
    from agent.modules.code.core import search_code
    args = inv.arguments or {}
    return search_code(
        str(args.get("pattern", "")),
        str(args.get("directory", ".")),
        str(args.get("file_type", "")),
        _safe_int(args.get("max_results"), 50),
    )

# ── Browser action handlers ──────────────────────────────────────────

def _handler_browser_navigate(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_navigate
    args = inv.arguments or {}
    return browser_navigate(
        str(args.get("url", "")),
        str(args.get("wait_selector", "")),
        int(args.get("timeout", 30000) or 30000),
    )


def _handler_browser_snapshot(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_snapshot
    args = inv.arguments or {}
    return browser_snapshot(
        str(args.get("selector", "body")),
        bool(args.get("compact", True)),
        int(args.get("max_elements", 50) or 50),
    )


def _handler_browser_screenshot(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_screenshot
    args = inv.arguments or {}
    return browser_screenshot(
        str(args.get("url", "")),
        bool(args.get("full_page", False)),
        as_file=bool(args.get("save_to_file", True)),
        workspace_id=_inv_workspace(inv),
    )


def _handler_browser_click(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_click
    args = inv.arguments or {}
    return browser_click(
        str(args.get("selector", "")),
        str(args.get("ref", "")),
    )


def _handler_browser_type(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_type
    args = inv.arguments or {}
    return browser_type(
        str(args.get("text", "")),
        str(args.get("selector", "")),
        str(args.get("ref", "")),
        bool(args.get("clear_first", True)),
    )


def _handler_browser_extract(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_extract
    args = inv.arguments or {}
    return browser_extract(
        str(args.get("url", "")),
        str(args.get("selector", "body")),
    )


def _handler_browser_scroll(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_scroll
    args = inv.arguments or {}
    return browser_scroll(
        str(args.get("direction", "down")),
        int(args.get("amount", 500) or 500),
    )


def _handler_browser_hover(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_hover
    args = inv.arguments or {}
    return browser_hover(
        str(args.get("selector", "")),
        str(args.get("ref", "")),
    )


def _handler_browser_press_key(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_press_key
    args = inv.arguments or {}
    return browser_press_key(str(args.get("key", "")))


def _handler_browser_select_option(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_select_option
    args = inv.arguments or {}
    return browser_select_option(
        str(args.get("value", "")),
        str(args.get("selector", "")),
        str(args.get("ref", "")),
    )


def _handler_browser_evaluate(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_evaluate
    args = inv.arguments or {}
    return browser_evaluate(str(args.get("script", "")))


def _handler_browser_wait(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_wait
    args = inv.arguments or {}
    return browser_wait(
        int(args.get("wait_ms", 0) or 0),
        str(args.get("wait_text", "")),
        int(args.get("timeout", 10000) or 10000),
    )


def _handler_browser_fill_form(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_fill_form
    args = inv.arguments or {}
    fields = args.get("fields", {})
    if isinstance(fields, dict):
        return browser_fill_form({str(k): str(v) for k, v in fields.items()})
    return {"ok": False, "error": "fields must be a dict of {selector: value}"}


def _handler_browser_tabs(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_tabs
    args = inv.arguments or {}
    return browser_tabs(
        str(args.get("tab_action", "list")),
        int(args.get("tab_index", 0) or 0),
        str(args.get("url", "")),
    )


def _handler_browser_network(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_network
    return browser_network()


def _handler_browser_console(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_console
    return browser_console()


def _handler_browser_navigate_back(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_navigate_back
    return browser_navigate_back()


def _handler_browser_close(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_close
    return browser_close()


def _handler_config_analysis_run(inv: ToolInvocation) -> dict:
    """Unified config analysis entrypoint — delegates to config_analysis service."""
    from agent.modules.config_analysis.service import run_config_analysis
    args = inv.arguments or {}
    return run_config_analysis(
        action=str(args.get("action", "")),
        workspace_id=_inv_workspace(inv),
        filepath=str(args.get("filepath", "")),
        file_id=str(args.get("file_id", "")),
        source_config=str(args.get("source_config", "")),
        source_vendor=str(args.get("source_vendor", "")),
        target_vendor=str(args.get("target_vendor", "")),
    )


def _handler_pcap_analysis_run(inv: ToolInvocation) -> dict:
    """Unified PCAP analysis entrypoint — delegates to pcap service."""
    from agent.modules.pcap.service import run_pcap_analysis
    args = inv.arguments or {}
    return run_pcap_analysis(
        action=str(args.get("action", "")),
        workspace_id=_inv_workspace(inv),
        filepath=str(args.get("filepath", "")),
        file_id=str(args.get("file_id", "")),
        session_id=str(args.get("session_id", "")),
        src=str(args.get("src", "")),
        sport=_safe_int(args.get("sport", 0)),
        dst=str(args.get("dst", "")),
        dport=_safe_int(args.get("dport", 0)),
        protocol=str(args.get("protocol", "")),
        use_filter=bool(args.get("use_filter", False)),
        run_id=inv.run_id or "",
        agent_session_id=str(args.get("agent_session_id", "")),
    )


def _handler_cmdb_list_assets(inv: ToolInvocation) -> dict:
    """List CMDB device assets with optional filtering."""
    import json as _json
    from agent.modules.cmdb.tools import tool_list_assets
    args = inv.arguments or {}
    workspace_id = _inv_workspace(inv)
    filter_arg = str(args.get("filter", "") or "").strip()
    direct_filter = {
        key: str(args.get(key, "") or "").strip()
        for key in ("type", "vendor", "region", "location")
        if str(args.get(key, "") or "").strip()
    }
    if direct_filter:
        if filter_arg:
            try:
                merged = _json.loads(filter_arg)
                if not isinstance(merged, dict):
                    return {"ok": False, "error": "filter must be a JSON object"}
            except _json.JSONDecodeError:
                return {"ok": False, "error": f"invalid filter JSON: {filter_arg}"}
            merged.update(direct_filter)
        else:
            merged = direct_filter
        filter_arg = _json.dumps(merged, ensure_ascii=False)
    return tool_list_assets(
        workspace_id=workspace_id,
        filter=filter_arg,
        search=str(args.get("search", "")),
        sort_by=str(args.get("sort_by", "name")),
    )


def _handler_cmdb_get_asset(inv: ToolInvocation) -> dict:
    """Get a single CMDB asset by ID."""
    from agent.modules.cmdb.tools import tool_get_asset
    args = inv.arguments or {}
    workspace_id = _inv_workspace(inv)
    asset_id = str(args.get("asset_id", "")).strip()
    if not asset_id:
        return {"ok": False, "error": "asset_id is required"}
    return tool_get_asset(workspace_id=workspace_id, asset_id=asset_id)


def _handler_cmdb_add_asset(inv: ToolInvocation) -> dict:
    """Add a CMDB asset (requires approval)."""
    from agent.modules.cmdb.tools import tool_add_asset
    args = inv.arguments or {}
    workspace_id = _inv_workspace(inv)
    name = str(args.get("name", "")).strip()
    host = str(args.get("host", "")).strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    if not host:
        return {"ok": False, "error": "host is required"}
    return tool_add_asset(
        workspace_id=workspace_id,
        name=name, host=host,
        type=str(args.get("type", "switch")),
        vendor=str(args.get("vendor", "")),
        protocol=str(args.get("protocol", "ssh")),
        port=_safe_int(args.get("port", 22)),
        username=str(args.get("username", "")),
        password=str(args.get("password", "")),
        region=str(args.get("region", "")),
        location=str(args.get("location", "")),
        model=str(args.get("model", "")),
        description=str(args.get("description", "")),
    )


def _handler_cmdb_delete_asset(inv: ToolInvocation) -> dict:
    """Soft-delete a CMDB asset."""
    from agent.modules.cmdb.tools import tool_delete_asset
    args = inv.arguments or {}
    workspace_id = _inv_workspace(inv)
    asset_id = str(args.get("asset_id", "")).strip()
    if not asset_id:
        return {"ok": False, "error": "asset_id is required"}
    return tool_delete_asset(workspace_id=workspace_id, asset_id=asset_id)


# ── Network device access (SSH / Telnet) ──

# Config command patterns — used to flag config-mode commands so the
# runner can mark them as ``is_config`` for the audit trail. These
# are NOT a destructive-command list; the destructive scan lives in
# ``core.tools.dangerous_patterns`` (the single source of truth).
_CONFIG_COMMAND_PATTERNS = [
    r"(?i)^conf(igure)?\s*(terminal|t)?$",
    r"(?i)^system-view$", r"(?i)^config$",
    r"(?i)^interface\s+\S", r"(?i)^router\s+\S",
    r"(?i)^no\s+", r"(?i)^undo\s+", r"(?i)^set\s+",
    r"(?i)^vlan\s+\d", r"(?i)^ip\s+route",
    r"(?i)^access-list", r"(?i)^snmp-server",
    r"(?i)^aaa\s+", r"(?i)^username\s+\S+\s+password",
]


def _is_dangerous_command(command: str) -> tuple[bool, str]:
    """Check if a command matches a destructive pattern.

    Delegates to ``core.tools.general_tools.dangerous_commands`` for
    tiered detection (BLOCK vs WARN vs SUSPICIOUS) covering both
    Linux/Windows and network-device commands.
    """
    if not command:
        return False, ""
    from core.tools.general_tools.dangerous_commands import check_dangerous
    is_dangerous, reason = check_dangerous(command)
    if is_dangerous:
        return True, reason or "dangerous command blocked (policy violation)"
    return False, ""


def _is_config_command(command: str) -> bool:
    """Check if a command requires config-mode (approval needed)."""
    import re
    for pattern in _CONFIG_COMMAND_PATTERNS:
        if re.search(pattern, command):
            return True
    return False


def _handler_network_ssh(inv: ToolInvocation) -> dict:
    """SSH into a device, execute a command, return output.

    v3.3: Supports persistent sessions via session_id.
    - First call without session_id: creates session, returns session_id.
    - Subsequent calls with session_id: reuses existing session (fast).
    - Set close_session=true or omit command to close.
    """
    from agent.modules.remote.core import ssh_connect, exec_command, disconnect, get_session

    args = inv.arguments or {}
    workspace_id = _inv_workspace(inv)
    asset_id = str(args.get("asset_id", "")).strip()
    host = str(args.get("host", "")).strip()
    port = _safe_int(args.get("port"), 22)
    username = str(args.get("username", "")).strip()
    password = str(args.get("password", "")).strip()
    command = str(args.get("command", "")).strip()
    vendor = str(args.get("vendor", "generic")).strip()
    session_id = str(args.get("session_id", "")).strip()
    close_session = bool(args.get("close_session", False))
    sudo = bool(args.get("sudo", False))

    if asset_id:
        try:
            from agent.modules.cmdb.service import get_asset
            asset = get_asset(workspace_id, asset_id, safe=False)
            if not asset:
                return {"ok": False, "error": f"asset_not_found: {asset_id}"}
            host = str(asset.get("host") or host).strip()
            port = _safe_int(asset.get("port") or port, 22)
            username = str(asset.get("username") or username).strip()
            password = str(asset.get("password") or password)
            vendor = str(asset.get("vendor") or vendor or "generic").strip()
        except Exception as exc:
            return {"ok": False, "error": f"asset_resolve_failed: {str(exc)[:120]}"}

    # Close session request
    if session_id and (close_session or not command):
        try:
            existing = get_session(session_id)
            if not existing or getattr(existing, "workspace_id", "") != workspace_id:
                return {"ok": False, "error": "session_workspace_mismatch"}
            disconnect(session_id)
        except Exception:
            logger.debug("_handler_network_ssh: <pass>", exc_info=True)
        return {"ok": True, "session_closed": True, "session_id": session_id}

    # Reuse existing session
    if session_id:
        try:
            existing = get_session(session_id)
            if existing and getattr(existing, "connected", False):
                if getattr(existing, "workspace_id", "") != workspace_id:
                    return {"ok": False, "error": "session_workspace_mismatch"}
                if not command:
                    return {"ok": True, "session_id": session_id, "session_active": True}
                if sudo and not command.startswith("sudo "):
                    command = f"sudo {command}"
                exec_result = exec_command(session_id, command)
                output_text = _extract_output(exec_result)
                return {
                    "ok": True, "host": getattr(existing, "host", host), "command": command,
                    "output": output_text[:_OUTPUT_TRUNCATE], "session_id": session_id,
                }
            # Session expired — auto-reconnect using stored info
            if existing and not host:
                host = getattr(existing, "host", "")
                port = getattr(existing, "port", 22)
                username = getattr(existing, "username", "")
                password = getattr(existing, "password", "")
                # Remove stale session entry
                try:
                    disconnect(session_id)
                except Exception:
                    logger.debug("_handler_network_ssh: <pass>", exc_info=True)
        except Exception:
            logger.debug("_handler_network_ssh: <pass>", exc_info=True)

    # New session
    if not host:
        return {"ok": False, "error": "host is required"}
    if not username:
        return {"ok": False, "error": "username is required"}
    if not password:
        return {"ok": False, "error": "SSH password is missing. Use asset_id (from CMDB) so credentials are resolved server-side, or provide password explicitly."}
    if not command:
        return {"ok": False, "error": "command is required"}

    # Safety: block dangerous commands
    is_dangerous, reason = _is_dangerous_command(command)
    if is_dangerous:
        return {"ok": False, "error": reason}

    is_config = _is_config_command(command)

    try:
        new_sid = session_id or f"ssh_{int(__import__('time').time())}_{host.replace('.', '_')}"
        if sudo and not command.startswith("sudo "):
            command = f"sudo {command}"
        session = ssh_connect(
            new_sid, host, port, username, password, vendor,
            workspace_id=workspace_id,
        )
        exec_result = exec_command(new_sid, command)
        if isinstance(exec_result, dict) and not exec_result.get("ok"):
            # Command failed — clean up session
            try:
                disconnect(new_sid)
            except Exception:
                logger.debug("_handler_network_ssh: <pass>", exc_info=True)
            return {"ok": False, "error": f"Command failed: {exec_result.get('error', '')}"}
        output_text = _extract_output(exec_result)
        return {
            "ok": True, "host": host, "command": command,
            "output": output_text[:_OUTPUT_TRUNCATE], "session_id": new_sid,
            "is_config": is_config,
        }
    except Exception as e:
        # Clean up on connection failure
        if 'new_sid' in dir():
            try:
                disconnect(new_sid)
            except Exception:
                logger.debug("_handler_network_ssh: <pass>", exc_info=True)
        return {"ok": False, "error": f"SSH failed: {e}"}


def _extract_output(exec_result) -> str:
    if isinstance(exec_result, dict):
        if not exec_result.get("ok"):
            return f"ERROR: {exec_result.get('error', '')}"
        return str(exec_result.get("output", ""))
    return str(exec_result)


def _handler_network_telnet(inv: ToolInvocation) -> dict:
    """Telnet into a device, execute a command, return output. v3.3: session reuse."""
    from agent.modules.remote.core import telnet_connect, exec_command, disconnect, get_session

    args = inv.arguments or {}
    workspace_id = _inv_workspace(inv)
    asset_id = str(args.get("asset_id", "")).strip()
    host = str(args.get("host", "")).strip()
    port = _safe_int(args.get("port"), 23)
    username = str(args.get("username", "")).strip()
    password = str(args.get("password", "")).strip()
    command = str(args.get("command", "")).strip()
    vendor = str(args.get("vendor", "generic")).strip()
    session_id = str(args.get("session_id", "")).strip()
    close_session = bool(args.get("close_session", False))

    if asset_id:
        try:
            from agent.modules.cmdb.service import get_asset
            asset = get_asset(workspace_id, asset_id, safe=False)
            if not asset:
                return {"ok": False, "error": f"asset_not_found: {asset_id}"}
            host = str(asset.get("host") or host).strip()
            port = _safe_int(asset.get("port") or port, 23)
            username = str(asset.get("username") or username).strip()
            password = str(asset.get("password") or password)
            vendor = str(asset.get("vendor") or vendor or "generic").strip()
        except Exception as exc:
            return {"ok": False, "error": f"asset_resolve_failed: {str(exc)[:120]}"}

    # Close session
    if session_id and (close_session or not command):
        try:
            existing = get_session(session_id)
            if not existing or getattr(existing, "workspace_id", "") != workspace_id:
                return {"ok": False, "error": "session_workspace_mismatch"}
            disconnect(session_id)
        except Exception:
            logger.debug("_handler_network_telnet: <pass>", exc_info=True)
        return {"ok": True, "session_closed": True, "session_id": session_id}

    # Reuse existing session
    if session_id:
        try:
            existing = get_session(session_id)
            if existing and getattr(existing, "connected", False):
                if getattr(existing, "workspace_id", "") != workspace_id:
                    return {"ok": False, "error": "session_workspace_mismatch"}
                exec_result = exec_command(session_id, command)
                return {
                    "ok": True, "host": host, "command": command,
                    "output": _extract_output(exec_result)[:_OUTPUT_TRUNCATE],
                    "session_id": session_id,
                }
        except Exception:
            logger.debug("_handler_network_telnet: <pass>", exc_info=True)

    if not host:
        return {"ok": False, "error": "host is required"}
    if not command:
        return {"ok": False, "error": "command is required"}

    is_dangerous, reason = _is_dangerous_command(command)
    if is_dangerous:
        return {"ok": False, "error": reason}

    try:
        new_sid = session_id or f"telnet_{int(__import__('time').time())}_{host.replace('.', '_')}"
        telnet_connect(
            new_sid, host, port, username, password, vendor,
            workspace_id=workspace_id,
        )
        exec_result = exec_command(new_sid, command)
        return {
            "ok": True, "host": host, "command": command,
            "output": _extract_output(exec_result)[:8000],
            "session_id": new_sid,
        }
    except Exception as e:
        return {"ok": False, "error": f"Telnet failed: {e}"}


# ─── Current action handlers ──────────────────────────────────────────

def handle_runtime_tasks(inv: ToolInvocation) -> dict:
    """List pending/running background tasks."""
    now = time.time()
    tasks = []
    try:
        with _BACKGROUND_LOCK:
            for job_id, job in list(_BACKGROUND_JOBS.items()):
                proc = job.get("process")
                returncode = proc.poll() if proc else job.get("returncode")
                status = "running" if returncode is None else "completed"
                if returncode is not None and not job.get("collected"):
                    try:
                        stdout, stderr = proc.communicate(timeout=0.1)
                    except Exception:
                        stdout, stderr = "", ""
                    job["stdout"] = str(stdout)[-8000:]
                    job["stderr"] = str(stderr)[-4000:]
                    job["returncode"] = returncode
                    job["collected"] = True
                    job["completed_at"] = now
                if status == "completed" and now - float(job.get("completed_at") or now) > 3600:
                    _BACKGROUND_JOBS.pop(job_id, None)
                    continue
                tasks.append({
                    "job_id": job_id,
                    "pid": job.get("pid"),
                    "status": status,
                    "returncode": returncode,
                    "command": job.get("command", ""),
                    "started_at": job.get("started_at"),
                    "elapsed_seconds": round(now - float(job.get("started_ts") or now), 2),
                    "stdout_tail": job.get("stdout", ""),
                    "stderr_tail": job.get("stderr", ""),
                })
        return {"ok": True, "tasks": tasks, "count": len(tasks)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def handle_audit_log_query(inv: ToolInvocation) -> dict:
    """Query audit log entries."""
    args = inv.arguments or {}
    log_level = str(args.get("log_level", "info")).lower()
    limit = max(1, min(int(args.get("limit", 20) or 20), 100))
    try:
        import json
        from storage.paths import workspace_root
        ws_id = _inv_workspace(inv)
        log_dir = workspace_root(ws_id) / "audit"
        files = sorted(log_dir.glob("*.json"))[-limit:] if log_dir.exists() else []
        entries = []
        for f in files:
            try:
                parsed = json.loads(f.read_text(encoding="utf-8")[:20000])
                level = str(parsed.get("level", parsed.get("severity", "info"))).lower() if isinstance(parsed, dict) else "info"
                if log_level == "error" and level != "error":
                    continue
                if log_level == "warn" and level not in {"warn", "warning", "error"}:
                    continue
                entries.append(parsed)
            except Exception:
                logger.debug("handle_audit_log_query: <pass>", exc_info=True)
        return {"ok": True, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"ok": True, "entries": [], "count": 0, "note": f"Audit log not available: {e}"}


def handle_text_extract_entities(inv: ToolInvocation) -> dict:
    """Extract network entities: IP, MAC, VLAN, subnet, hostname."""
    import re
    args = inv.arguments or {}
    text = str(args.get("text", ""))
    patterns = {
        "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "mac": r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b",
        "vlan": r"\bvlan\s*\d+\b",
        "subnet": r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b",
        "hostname": r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b",
    }
    result = {}
    for entity_type, pat in patterns.items():
        matches = list(set(re.findall(pat, text, re.IGNORECASE)))
        if matches:
            result[entity_type] = matches[:50]
    return {"ok": True, "entities": result, "total": sum(len(v) for v in result.values())}



def handle_background_exec(inv: ToolInvocation) -> dict:
    """Launch a background command and return a job_id for polling."""
    import subprocess, uuid
    args = inv.arguments or {}
    command = str(args.get("command", ""))
    if not command:
        return {"ok": False, "error": "command is required"}

    # ── Safety: dangerous command detection ──
    from core.tools.general_tools.dangerous_commands import check_dangerous
    is_dangerous, reason = check_dangerous(command)
    if is_dangerous:
        return {"ok": False, "error": reason, "blocked": True}
    job_id = f"bg_{uuid.uuid4().hex[:8]}"
    try:
        proc = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        started_ts = time.time()
        with _BACKGROUND_LOCK:
            _BACKGROUND_JOBS[job_id] = {
                "process": proc,
                "pid": proc.pid,
                "command": command[:500],
                "started_ts": started_ts,
                "started_at": now_iso(),
                "stdout": "",
                "stderr": "",
                "collected": False,
            }
        return {
            "ok": True, "job_id": job_id, "command": command[:200],
            "pid": proc.pid, "status": "started",
            "hint": "Use system.manage action=tasks to check status.",
            "description": str(args.get("description", "")).strip() or "background command",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def handle_stream_exec(inv: ToolInvocation) -> dict:
    """Execute command with streaming output (PTY-like)."""
    import subprocess
    args = inv.arguments or {}
    command = str(args.get("command", ""))
    if not command:
        return {"ok": False, "error": "command is required"}

    # ── Safety: dangerous command detection ──
    from core.tools.general_tools.dangerous_commands import check_dangerous
    is_dangerous, reason = check_dangerous(command)
    if is_dangerous:
        return {"ok": False, "error": reason, "blocked": True}
    timeout = args.get("timeout", 30)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[:_OUTPUT_TRUNCATE],
            "stderr": result.stderr[:5000],
            "exit_code": result.returncode,
            "description": str(args.get("description", "")).strip() or "stream output",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def handle_file_glob(inv: ToolInvocation) -> dict:
    """Glob file pattern matching."""
    import glob as g, os
    args = inv.arguments or {}
    subdir = str(args.get("subdir", "."))
    pattern = str(args.get("pattern", "*"))
    try:
        from core.tools.general_tools.shared import _workspace_path
        ws_id = _inv_workspace(inv)
        base = str(_workspace_path(ws_id, subdir))
        full_pattern = os.path.join(base, pattern)
        matches = sorted(g.glob(full_pattern, recursive=True))[:200]
        rel = [os.path.relpath(m, base) for m in matches]
        return {"ok": True, "files": rel, "count": len(rel), "directory": subdir}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def handle_file_delete(inv: ToolInvocation) -> dict:
    """Soft-delete a file (move to .trash)."""
    import shutil
    from pathlib import Path
    args = inv.arguments or {}
    filepath = str(args.get("filepath", ""))
    if not filepath:
        return {"ok": False, "error": "filepath is required"}
    try:
        from core.tools.general_tools.shared import _workspace_path
        ws_id = _inv_workspace(inv)
        target = _workspace_path(ws_id, filepath)
        base = _workspace_path(ws_id, "")
        if not target.exists() or not target.is_file():
            return {"ok": False, "error": f"File not found: {filepath}"}
        trash = base / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        dest = trash / f"{Path(filepath).name}.{ts}"
        shutil.move(target, dest)
        return {"ok": True, "deleted": filepath, "trash_path": str(dest)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}







def handle_report_diff(inv: ToolInvocation) -> dict:
    """Diff two artifacts."""
    args = inv.arguments or {}
    aid_a = str(args.get("artifact_id_a", ""))
    aid_b = str(args.get("artifact_id_b", ""))
    try:
        ws_id = _inv_workspace(inv)
        from core.tools.general_tools.file_tools import handle_artifact_read_content_safe
        inv_a = ToolInvocation(arguments={"workspace_id": ws_id, "artifact_id": aid_a})
        res_a = handle_artifact_read_content_safe(inv_a)
        inv_b = ToolInvocation(arguments={"workspace_id": ws_id, "artifact_id": aid_b})
        res_b = handle_artifact_read_content_safe(inv_b)
        text_a = res_a.get("content", "") if isinstance(res_a, dict) else ""
        text_b = res_b.get("content", "") if isinstance(res_b, dict) else ""
        return {
            "ok": True,
            "artifact_a": {"id": aid_a, "size": len(text_a)},
            "artifact_b": {"id": aid_b, "size": len(text_b)},
            "same": text_a == text_b,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _handler_cmdb_update_asset(inv: ToolInvocation) -> dict:
    """Update an existing CMDB asset."""
    args = inv.arguments or {}
    asset_id = str(args.get("asset_id", ""))
    if not asset_id:
        return {"ok": False, "error": "asset_id is required for update"}
    try:
        from agent.modules.cmdb.service import get_asset, save_asset
        ws_id = _inv_workspace(inv)
        asset = get_asset(ws_id, asset_id, safe=False)
        if not asset:
            return {"ok": False, "error": f"Asset not found: {asset_id}"}
        for key in ("name", "host", "vendor", "type", "protocol", "port", "username",
                    "model", "region", "location", "description", "tags"):
            if key in args and args[key] is not None:
                asset[key] = args[key]
        result = save_asset(ws_id, asset)
        if not result.get("ok"):
            return result
        updated = get_asset(ws_id, asset_id, safe=True) or asset
        return {"ok": True, "asset": updated, "updated": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _handler_cmdb_export_assets(inv: ToolInvocation) -> dict:
    """Export CMDB assets list."""
    import json
    args = inv.arguments or {}
    fmt = str(args.get("format", "json")).lower()
    try:
        from agent.modules.cmdb.service import export_assets
        result = _handler_cmdb_list_assets(inv)
        assets = result.get("assets", []) if isinstance(result, dict) else []
        if fmt == "csv":
            return {"ok": True, "format": "csv", "data": export_assets(_inv_workspace(inv)), "count": len(assets)}
        return {"ok": True, "format": "json", "data": json.dumps(assets, ensure_ascii=False), "count": len(assets)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _schema(properties: dict | None = None, required: list[str] | None = None) -> dict:
    """Build JSON Schema, then strip bloat for token efficiency."""
    raw = {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
    }
    return _strip_schema_bloat(raw)


# Fields that need descriptions — everything else is self-documenting
_KEEP_DESC = {
    "ref", "script", "selector", "scope", "use_filter",
    "expression", "agent_type", "extract_mode", "gate_mode",
    "background", "merge", "page_range", "created_by",
    "days", "max_results", "allowed_domains", "blocked_domains",
    "depth", "max_fetch", "location", "url",
}


def _strip_schema_bloat(schema: dict) -> dict:
    """Remove default values and verbose field descriptions to save ~3K tokens."""
    props = schema.get("properties", {})
    for key, val in list(props.items()):
        if not isinstance(val, dict):
            continue
        # 1. Drop action enum description (main tool desc covers it)
        if key == "action":
            val.pop("description", None)
        # 2. Drop default values (handlers have code defaults)
        val.pop("default", None)
        val.pop("default_strategy", None)
        # 3. Drop field descriptions unless ambiguous
        if "description" in val and key not in _KEEP_DESC:
            val.pop("description")
    return schema


_S = {
    "workspace_id": {"type": "string", "description": "Workspace id."},
    "query": {"type": "string", "description": "Natural language query or keyword."},
    "limit": {"type": "integer", "description": "Max results, 1-50.", "default": 10},
    "artifact_id": {"type": "string", "description": "Artifact id."},
    "source_id": {"type": "string", "description": "Knowledge source id."},
    "chunk_id": {"type": "string", "description": "Knowledge chunk id."},
    "url": {"type": "string", "description": "Public http(s) URL."},
    "title": {"type": "string", "description": "Human-readable title."},
    "content": {"type": "string", "description": "Text content."},
    "text": {"type": "string", "description": "Text to inspect or transform."},
    "session_id": {"type": "string", "description": "Session id."},
    "run_id": {"type": "string", "description": "Run id."},
    "filepath": {"type": "string", "description": "Workspace-relative file path, e.g. files/topology.txt."},
    "days": {"type": "integer", "description": "Forecast horizon in days, 1-10.", "default": 3},
    "recency": {"type": "string", "description": "Time filter: day, week, month, year.", "default": "week"},
    "format": {"type": "string", "description": "Output format.", "enum": ["txt", "md"]},
    "language": {"type": "string", "description": "Language code, e.g. zh-CN, en.", "default": "zh-CN"},
    "command": {"type": "string", "description": "Shell command. macOS/Linux. Example: ifconfig, ping -c 3 8.8.8.8, ls -la. NOT destructive commands."},
    "status": {"type": "string", "description": "Filter by status."},
    "location": {"type": "string", "description": "City or location name."},
    "units": {"type": "string", "description": "Temperature units.", "enum": ["metric", "imperial"], "default": "metric"},
    "code": {"type": "string", "description": "Python source code."},
    "reason": {"type": "string", "description": "Human-readable reason or note."},
    "dry_run": {"type": "boolean", "description": "Preview without making changes.", "default": True},
    "memory_id": {"type": "string", "description": "Memory entry id."},
    "old_string": {"type": "string", "description": "Text to replace."},
    "new_string": {"type": "string", "description": "New text to insert in place of the old text."},
    "patch_text": {"type": "string", "description": "Unified diff patch text."},
    "skill_name": {"type": "string", "description": "Skill directory name."},
    "description": {"type": "string", "description": "Short description."},
    "capabilities": {"type": "array", "description": "Capability identifiers.", "items": {"type": "string"}},
    "page_range": {"type": "string", "description": "Optional page range, e.g. 1-3."},
}


def _ordered_unique(items) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


# ── Knowledge module adapters (v3.2.1: replace placeholder handlers) ──

def _k_source_list(inv: ToolInvocation) -> dict:
    from agent.modules.knowledge.tools import tool_handler_list
    r = tool_handler_list({"workspace_id": _inv_workspace(inv)}, {})
    return _module_result_to_dict(r)

def _k_chunk_list(inv: ToolInvocation) -> dict:
    from agent.modules.knowledge.tools import tool_handler_list_chunks
    args = inv.arguments or {}
    r = tool_handler_list_chunks({"workspace_id": _inv_workspace(inv), "source_id": str(args.get("source_id", ""))}, {})
    return _module_result_to_dict(r)

def _k_parent_read(inv: ToolInvocation) -> dict:
    from agent.modules.knowledge.tools import tool_handler_read_parent
    args = inv.arguments or {}
    r = tool_handler_read_parent({
        "workspace_id": _inv_workspace(inv),
        "child_chunk_id": str(args.get("chunk_id", ""))}, {})
    return _module_result_to_dict(r)

def _k_import(inv: ToolInvocation) -> dict:
    """Merged import: delegates to import_file (handles most file types)."""
    from agent.modules.knowledge.tools import tool_handler_import_file
    args = inv.arguments or {}
    fp = str(args.get("filepath", "")).strip()
    if not fp:
        fp = str(args.get("source", "")).strip()
    if not fp:
        return {"ok": False, "error": "filepath or source is required", "status": "failed"}
    r = tool_handler_import_file({
        "workspace_id": _inv_workspace(inv),
        "source": fp,
        "title": str(args.get("title", fp.split("/")[-1] if "/" in fp else "imported")),
        "author": str(args.get("author", "")),
        "edition": str(args.get("edition", "")),
    }, {})
    return _module_result_to_dict(r)

def _k_source_manage(inv: ToolInvocation) -> dict:
    """Merged: disable, delete, or reindex a knowledge source."""
    from agent.modules.knowledge.tools import tool_handler_disable, tool_handler_delete, tool_handler_reindex
    args = inv.arguments or {}
    action = str(args.get("action", "disable")).strip().lower()
    ws = _inv_workspace(inv)
    sid = str(args.get("source_id", ""))
    if action == "delete":
        r = tool_handler_delete({"workspace_id": ws, "source_id": sid}, {})
    elif action == "reindex":
        r = tool_handler_reindex({"workspace_id": ws, "source_id": sid}, {})
    else:
        r = tool_handler_disable({"workspace_id": ws, "source_id": sid}, {})
    return _module_result_to_dict(r)

def _review_item_list(inv: ToolInvocation) -> dict:
    """List review items. Returns items attached to a specific artifact."""
    try:
        from agent.modules.review.tools import tool_handler_list
        args = inv.arguments or {}
        ws = _inv_workspace(inv)
        r = tool_handler_list({"workspace_id": ws, "limit": int(args.get("limit", 10)),
                               "artifact_id": str(args.get("artifact_id", ""))}, {})
        return _module_result_to_dict(r)
    except Exception as e:
        return {"ok": False, "tool_id": "system.manage", "status": "failed",
                "summary": f"Review service unavailable: {str(e)[:120]}"}


def _review_item_update(inv: ToolInvocation) -> dict:
    """Update review item status. Falls back if unavailable."""
    try:
        from agent.modules.review.tools import tool_handler_update
        args = inv.arguments or {}
        ws = _inv_workspace(inv)
        r = tool_handler_update({
            "workspace_id": ws,
            "artifact_id": str(args.get("artifact_id", args.get("review_id", ""))),
            "item_id": str(args.get("item_id", args.get("review_id", ""))),
            "status": str(args.get("status", "")),
            "user_note": str(args.get("user_note", "")),
        }, {})
        return _module_result_to_dict(r)
    except Exception as e:
        return {"ok": False, "tool_id": "system.manage", "status": "failed",
                "summary": f"Review service unavailable: {str(e)[:120]}"}

def _weather_merged(inv: ToolInvocation) -> dict:
    """Merged weather tool: days=1 → current, days>1 → forecast.
    v3.10: Calls internal handlers directly (not through client.invoke) since
    web.weather.current/forecast are implementation details of this merged handler.
    The client.invoke path would require unused tool namespace entries and manifests
    just for internal routing."""
    args = inv.arguments or {}
    days = _safe_int(args.get("days"), 1)
    if days <= 1:
        result = handle_weather_current(ToolInvocation(
            tool_id="web.weather.current",
            arguments={**args, "language": args.get("language", "zh-CN"), "units": args.get("units", "metric")},
            workspace_id=inv.workspace_id, requested_by=inv.requested_by, approval_id=inv.approval_id,
        ))
    else:
        result = handle_weather_forecast(ToolInvocation(
            tool_id="web.weather.forecast",
            arguments={**args, "days": str(days), "language": args.get("language", "zh-CN"), "units": args.get("units", "metric")},
            workspace_id=inv.workspace_id, requested_by=inv.requested_by, approval_id=inv.approval_id,
        ))
    payload = _llm_payload_from_handler_result(result)
    return {"ok": result.get("ok", False),
            "summary": result.get("summary") or "",
            "output": payload,
            "errors": list(result.get("errors", []))[:5] if isinstance(result, dict) else [],
            "warnings": list(result.get("warnings", []))[:5] if isinstance(result, dict) else []}


def _llm_payload_from_handler_result(result: Any) -> dict:
    """Extract the full LLM-facing payload from split tool handlers.

    Most general-tool handlers return their structured payload directly at the
    top level (``forecast_daily``, ``results_markdown``, ``answer_hint`` ...).
    Some older handlers use ``output`` or ``content``. Merged canonical wrappers
    must preserve all of those fields instead of reducing the result to summary
    text, otherwise the finalizer cannot answer multi-day weather, inspection,
    or search questions accurately.
    """
    if not isinstance(result, dict):
        return {}
    for key in ("output", "content"):
        value = result.get(key)
        if isinstance(value, dict) and value:
            return value
    wrapper_keys = {
        "ok", "status", "tool_id", "summary", "error", "errors", "warnings",
        "artifact_ids", "redacted", "policy_decision", "created_at",
    }
    return {k: v for k, v in result.items() if k not in wrapper_keys}

def _module_result_to_dict(r: dict) -> dict:
    """Convert module handler result dict to canonical tool output."""
    if not isinstance(r, dict):
        return {"ok": False, "error": "unexpected result type"}
    ok = bool(r.get("ok", False))
    content = r.get("content", "")
    if isinstance(content, str):
        import json
        try:
            content = json.loads(content)
        except Exception:
            logger.debug("_module_result_to_dict: <pass>", exc_info=True)
    return {
        "ok": ok, "tool_id": r.get("tool_id", ""),
        "status": "succeeded" if ok else "failed",
        "summary": str(r.get("summary", "")),
        "errors": r.get("errors", []), "content": content,
    }


def _ws_artifact_list_merged(inv: ToolInvocation) -> dict:
    """Merged handler for workspace.artifact — dispatches to list or search."""
    if inv.arguments.get("query", "").strip():
        result = handle_artifact_search(inv)
    else:
        result = _ws_artifact_list_basic(inv)
    if isinstance(result, dict):
        return result
    return {"ok": False, "error": "unexpected result type"}


def _ws_artifact_list_basic(inv: ToolInvocation) -> dict:
    """List artifact metadata for a workspace (simple list, no full content)."""
    workspace_id = inv.arguments.get("workspace_id", inv.workspace_id or "")
    try:
        from workspace.manager import get_workspace_state
        state = get_workspace_state(workspace_id)
        art_refs = state.get("artifact_refs", []) if isinstance(state, dict) else []
        return {
            "ok": True,
            "tool_id": "workspace.artifact",
            "status": "ok",
            "summary": f"Listed {len(art_refs)} artifact references",
            "artifacts": art_refs[:50],
            "workspace_id": workspace_id,
            "warnings": ["Artifact list is metadata-only; no full content returned"] if art_refs else [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "tool_id": "workspace.artifact",
            "status": "failed",
            "summary": f"Failed to list artifacts: {str(exc)[:100]}",
            "artifacts": [],
            "warnings": [f"workspace.artifact failed: {str(exc)[:100]}"],
        }


# canonical_tool_id -> CanonicalToolEntry
_RAW_REGISTRY: list[CanonicalToolEntry] = [
    # ── 22-tool Codex-style registry (all visible to LLM) ──
    # Merged tools use action=... dispatch (see _handle_*_merged above).
    # LLMs and runtime callers use the merged canonical_tool_ids below.

    # 1. exec.run — unifies shell + python + slash
    CanonicalToolEntry(
        canonical_tool_id="exec.run",
        handler=_adapt(_handle_exec_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string",
                       "enum": ["shell", "python", "slash", "background", "stream"],
                       "description": "shell (default) | python | slash | background | stream.",
                       "default": "shell"},
            "description": {"type": "string",
                            "description": "Short description (5-10 words) of what this command does. Required for safety auditing."},
            "target": {"type": "string", "enum": ["local", "ssh", "telnet"],
                       "default": "local",
                       "description": "[action=shell] Execution target: local (default) | ssh | telnet."},
            "shell": {"type": "string",
                      "description": "[action=shell] Shell type: cmd (bash) or powershell.", "default": "cmd"},
            "command": {"type": "string", "description": "[action=shell|background|stream] Shell command to execute."},
            "code": {"type": "string", "description": "[action=python] Python code to execute (AST-sandboxed, imports restricted)."},
            "host": {"type": "string", "description": "[target=ssh|telnet] Host/IP — only use when asset_id is unavailable."},
            "port": {"type": "integer", "description": "[target=ssh|telnet] Port — only use when asset_id is unavailable."},
            "asset_id": {"type": "string", "description": "[target=ssh|telnet] PREFERRED. CMDB asset ID — host/user/password auto-resolved server-side. When a device was just queried from CMDB, pass its asset_id."},
            "username": {"type": "string", "description": "[target=ssh|telnet] Fallback username — only use when asset_id is unavailable."},
            "password": {"type": "string", "description": "[target=ssh|telnet] Fallback password — only use when asset_id is unavailable."},
            "vendor": {"type": "string", "description": "[target=ssh|telnet] Device vendor hint for command adaptation."},
            "session_id": {"type": "string", "description": "[target=ssh] Reuse existing SSH session (faster)."},
            "close_session": {"type": "boolean", "description": "[target=ssh] Close SSH session after execution."},
            "working_dir": {"type": "string", "description": "[action=shell] Working directory for command execution."},
            "env_vars": {"type": "object", "description": "[action=shell] Environment variables (PATH/LD_PRELOAD blocked)."},
            "timeout": {"type": "integer", "description": "[action=shell|python|stream] Timeout in seconds (default: shell=120, python=30, stream=30)."},
            "args": {"type": "string", "description": "[action=slash] Slash command arguments."},
        }),
        risk_level="medium", permission_action="exec",
        description=(
            "Command execution. action=shell (local|ssh|telnet), action=python (AST-sandboxed), "
            "action=slash (registered commands), action=background (async), action=stream (PTY). "
            "Always provide a `description` field. Read-only commands and connection attempts are medium risk. "
            "Only destructive commands (rm -f, delete, wipe, format, erase) escalate to high-risk approval."
        ),
    ),

    # 2. git.manage — status / log / diff / commit / push
    CanonicalToolEntry(
        canonical_tool_id="git.manage",
        handler=_adapt(_handle_git_merged),
        input_schema=_schema({
            "repo_path": {"type": "string", "default": ".", "description": "Path to git repository."},
            "action": {"type": "string",
                       "enum": ["status", "log", "diff", "commit", "push"],
                       "description": "status | log | diff | commit | push."},
            "staged": {"type": "boolean", "default": False, "description": "[diff] Show staged only."},
            "file_path": {"type": "string", "default": "", "description": "[diff/log] Scope to file."},
            "n": {"type": "integer", "default": 10, "description": "[log] Number of commits."},
            "message": {"type": "string", "description": "[commit] Commit message."},
            "files": {"type": "array", "items": {"type": "string"},
                      "description": "[commit] Specific files; omit to stage all (-A)."},
            "remote": {"type": "string", "default": "origin", "description": "[push] Remote."},
            "branch": {"type": "string", "default": "", "description": "[push] Branch."},
        }, ["action"]),
        risk_level="medium", requires_approval=False,  # only commit/push require approval at runtime
        description=(
            "Unified git tool. action=status (working tree), action=log, action=diff "
            "(unstaged/staged/file-scoped), action=commit (requires approval), "
            "action=push (requires approval). Always run status+diff before commit/push."
        ),
    ),

    # 3. device.manage — list / get / add / update / delete / export
    CanonicalToolEntry(
        canonical_tool_id="device.manage",
        handler=_adapt(_handle_device_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["list", "get", "add", "delete", "update", "export"]},
            "search": {"type": "string", "description": "[list] Fuzzy search name/vendor/host/model/region."},
            "filter": {"type": "string", "description": '[list] JSON filter, e.g. {"type":"switch","region":"华东"}.'},
            "sort_by": {"type": "string", "description": "[list] Sort: name/type/vendor/region/location/host/updated_at."},
            "asset_id": {"type": "string", "description": "[get|delete|update] Asset ID."},
            "name": {"type": "string"}, "host": {"type": "string"},
            "type": {"type": "string", "enum": ["switch", "router", "firewall", "server", "other"],
                     "default": "switch"},
            "vendor": {"type": "string"},
            "model": {"type": "string"},
            "region": {"type": "string", "description": "[list|add|update] Region, e.g. 华东, 华南."},
            "location": {"type": "string", "description": "[list|add|update] Physical site location."},
            "protocol": {"type": "string", "enum": ["ssh", "telnet"], "default": "ssh"},
            "port": {"type": "integer", "default": 22},
            "username": {"type": "string"},
            "password": {"type": "string", "description": "[add] Saved credential; never returned by reads."},
            "description": {"type": "string"},
            "format": {"type": "string", "enum": ["json", "csv"], "default": "json",
                       "description": "[export] Output format (json recommended)."},
        }, ["action"]),
        risk_level="medium", requires_approval=False,  # add/delete require approval at runtime
        description=(
            "CMDB device inventory. Use list to search/filter by type/vendor/region, "
            "get to view details (including SSH credentials), "
            "add/update/delete for management (requires approval). "
            "export for CSV backup. Never fabricate asset data."
        ),
    ),

    # 4. browser.manage — 16 browser automation actions
    CanonicalToolEntry(
        canonical_tool_id="browser.manage",
        handler=_adapt(_handle_browser_merged),
        input_schema=_schema({
            "action": {
                "type": "string",
                "enum": [
                    "navigate", "snapshot", "screenshot", "click",
                    "type", "extract", "scroll", "hover",
                    "press_key", "select_option", "evaluate", "wait",
                    "fill_form", "tabs", "network", "console",
                    "navigate_back", "close",
                ],
                "description": (
                    "navigate (load URL) | snapshot (accessibility tree — use first to see page structure) | "
                    "screenshot (capture page as image) | click | type (input text) | "
                    "extract (get element text) | scroll | hover | press_key (Enter/Escape/Tab/ArrowDown) | "
                    "select_option | evaluate (run JavaScript) | wait (time or text) | "
                    "fill_form (batch fill) | tabs (manage tabs) | network (list requests) | "
                    "console (view messages) | navigate_back | close"
                ),
                "default": "navigate",
            },
            "url": {"type": "string", "description": "[navigate|screenshot|extract|tabs] URL to load or tab target."},
            "selector": {"type": "string", "default": "body",
                         "description": "[click|type|extract|hover|select_option] CSS selector. Prefer ref over selector."},
            "ref": {"type": "string", "description": "[click|type|hover|select_option|fill_form] Element ref from snapshot (e.g. e1, e2). Use this instead of selector for precision."},
            "text": {"type": "string", "description": "[type] Text to type into the element."},
            "value": {"type": "string", "description": "[select_option] Option value to select."},
            "script": {"type": "string", "description": "[evaluate] JavaScript code to execute in page context."},
            "direction": {"type": "string", "enum": ["up", "down"], "default": "down",
                          "description": "[scroll] Scroll direction."},
            "amount": {"type": "integer", "default": 500,
                       "description": "[scroll] Pixels to scroll."},
            "key": {"type": "string", "description": "[press_key] Key name (Enter, Escape, Tab, ArrowDown, F5, etc.)."},
            "fields": {"type": "object", "description": "[fill_form] Dict of {selector_or_ref: value}. Keys can be CSS selectors or snapshot ref IDs (e1, e2)."},
            "clear_first": {"type": "boolean", "default": True,
                            "description": "[type] Clear existing content before typing."},
            "wait_ms": {"type": "integer", "default": 0,
                        "description": "[wait] Milliseconds to wait."},
            "wait_text": {"type": "string", "description": "[wait] Wait until this text appears on page."},
            "compact": {"type": "boolean", "default": True,
                        "description": "[snapshot] Only show interactive elements (buttons/inputs/links)."},
            "max_elements": {"type": "integer", "default": 50,
                             "description": "[snapshot] Max elements to return (prevents context overflow)."},
            "full_page": {"type": "boolean", "default": False,
                          "description": "[screenshot] Capture full scrollable page."},
            "save_to_file": {"type": "boolean", "default": True,
                             "description": "[screenshot] Save to workspace file (True) or return base64 (False)."},
            "tab_action": {"type": "string", "enum": ["list", "new", "close", "select"],
                           "description": "[tabs] list | new | close | select."},
            "tab_index": {"type": "integer", "description": "[tabs] Tab index."},
            "timeout": {"type": "integer", "default": 30000,
                        "description": "[navigate|wait] Timeout in milliseconds."},
        }, ["action"]),
        description=(
            "Headless Chromium browser. "
            "WORKFLOW: navigate → snapshot (get ref IDs) → interact via ref=e1. "
            "Core actions: click, type, scroll, hover, press_key, select_option. "
            "Advanced: extract, evaluate, fill_form, wait, screenshot, tabs, network, console. "
            "Use ref over CSS selectors for precision. navigate_back/close for nav."
        ),
    ),

    # 5. web.manage — search / fetch / weather / deep_search / monitor
    CanonicalToolEntry(
        canonical_tool_id="web.manage",
        handler=_adapt(_handle_web_merged),
        input_schema=_schema({
            "action": {
                "type": "string",
                "enum": ["search", "fetch", "weather", "deep_search", "list"],
                "description": "search (web search) | fetch (read a URL) | weather (forecast) | deep_search (search+fetch+aggregate) | list (alias for search, no-op).",
                "default": "search",
            },
            # ── search / deep_search ──
            "query": {"type": "string", "description": "[search|deep_search] Search query."},
            "source": {"type": "string", "enum": ["general", "docs", "news"],
                       "default": "general",
                       "description": "[search|deep_search] Search source."},
            "allowed_domains": {"type": "array", "items": {"type": "string"},
                                "description": "[search] Only include results from these domains."},
            "blocked_domains": {"type": "array", "items": {"type": "string"},
                                "description": "[search] Exclude results from these domains."},
            "depth": {"type": "string", "enum": ["fast", "balanced", "deep"],
                      "default": "balanced",
                      "description": "[search] fast (one backend, quick) | balanced (default) | deep (all backends, comprehensive)."},
            "max_results": {"type": "integer", "default": 8, "minimum": 1, "maximum": 30,
                            "description": "[search] Max results to return."},
            "recency": _S["recency"],
            "language": _S["language"],
            # ── fetch ──
            "url": _S["url"],
            "extract_mode": {"type": "string", "enum": ["article", "full", "structured", "links"],
                             "default": "article",
                             "description": "[fetch] article (main content, best for reading) | full (entire page as Markdown) | structured (tables/code/lists as JSON) | links (extract all links)."},
            "max_length": {"type": "integer", "default": 15000, "minimum": 1000, "maximum": 200000,
                           "description": "[fetch] Max chars in content (default=15000, 0=no limit). Set higher for full pages, lower for summaries."},
            "timeout": {"type": "integer", "default": 15, "minimum": 5, "maximum": 60,
                        "description": "[fetch] Request timeout in seconds."},
            # ── deep_search ──
            "max_fetch": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5,
                          "description": "[deep_search] Max pages to fetch after searching."},
            # ── weather ──
            "location": _S["location"],
            "days": {"type": "integer", "default": 1,
                     "description": "[weather] 1=current conditions, 2-10=forecast."},
            "units": _S["units"],
            # ── common ──
            "workspace_id": _S["workspace_id"],
        }, ["action"]),
        description=(
            "Web knowledge. search: find info/docs/news. "
            "fetch: read a URL (article/full/structured/links). "
            "weather: forecast. deep_search: search+fetch in one call."
        ),
    ),

    # 6. data.manage — parse / stats / distinct / aggregate / filter / sort / render / pivot / join
    CanonicalToolEntry(
        canonical_tool_id="data.manage",
        handler=_adapt(_handle_data_merged),
        input_schema=_schema({
            "action": {
                "type": "string",
                "enum": ["parse", "stats", "distinct", "aggregate", "filter", "sort", "render", "pivot", "join"],
                "description": (
                    "parse (auto-detect schema) | stats (describe numerical columns) | "
                    "distinct (unique values + frequency) | aggregate (group by + metrics) | "
                    "filter (eq/neq/gt/lt/contains/in) | sort (multi-column) | "
                    "render (Markdown/JSON output) | pivot (cross tabulation) | "
                    "join (merge two datasets). Start with parse to understand data shape."
                ),
                "default": "parse",
            },
            "text": _S["text"],
            "rows": {"type": "array", "description": "Pre-parsed rows from previous action."},
            # ── distinct ──
            "column": {"type": "string", "description": "[distinct] Column to analyze."},
            # ── aggregate ──
            "group_by": {"type": "array", "items": {"type": "string"},
                         "description": "[aggregate] Column(s) to group by."},
            "metrics": {
                "type": "array", "items": {"type": "object"},
                "description": "[aggregate] [{column, func}] — func: count|sum|avg|min|max."
            },
            # ── filter ──
            "conditions": {
                "type": "array", "items": {"type": "object"},
                "description": "[filter] [{column, op, value}] — op: eq|neq|gt|lt|gte|lte|contains|in."
            },
            # ── sort ──
            "by": {"type": "array", "items": {"type": "string"},
                   "description": "[sort] Column(s) to sort by."},
            "order": {"type": "string", "enum": ["asc", "desc"], "default": "asc",
                      "description": "[sort] Sort order."},
            # ── render / common ──
            "output": {"type": "string", "enum": ["markdown", "json"], "default": "markdown",
                       "description": "[render] Output format."},
            "max_rows": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200,
                         "description": "[render|filter|sort] Max rows to return."},
            # ── pivot ──
            "index": {"type": "string", "description": "[pivot] Column for row labels."},
            "pivot_columns": {"type": "string", "description": "[pivot] Column for column labels."},
            "pivot_values": {"type": "string", "description": "[pivot] Column to aggregate."},
            "aggfunc": {"type": "string", "enum": ["sum", "count", "avg"], "default": "sum",
                        "description": "[pivot] Aggregate function."},
            # ── join ──
            "right_text": {"type": "string", "description": "[join] Right-side data (CSV/JSON/Markdown)."},
            "right_rows": {"type": "array", "description": "[join] Right-side pre-parsed rows."},
            "on": {"type": "string", "description": "[join] Join column (must exist in both datasets)."},
            "how": {"type": "string", "enum": ["inner", "left"], "default": "inner",
                    "description": "[join] Join type: inner (matching only) or left (all left rows)."},
        }, ["action"]),
        description=(
            "CSV/JSON/Markdown table data engine. "
            "WORKFLOW: parse → stats/distinct → filter/sort → aggregate/pivot/join → render. "
            "Use aggregate for GROUP BY (COUNT/SUM/AVG). Use join to merge datasets."
        ),
    ),

    # 7. report.manage — save / diff / document
    CanonicalToolEntry(
        canonical_tool_id="report.manage",
        handler=_adapt(_handle_report_merged),
        input_schema=_schema({
            "action": {
                "type": "string",
                "enum": ["save", "diff", "document"],
                "description": (
                    "save (persist content as artifact) | "
                    "diff (compare two texts or artifacts) | "
                    "document (generate complete HTML document with TOC + styling)"
                ),
                "default": "save",
            },
            "content": _S["content"],
            "title": _S["title"],
            # ── save ──
            "artifact_type": {"type": "string", "default": "report",
                              "description": "[save] Artifact type tag."},
            # ── diff ──
            "text_a": {"type": "string", "description": "[diff] First text to compare."},
            "text_b": {"type": "string", "description": "[diff] Second text to compare."},
            "artifact_id_a": {"type": "string", "description": "[diff] First artifact ID (alternative to text_a)."},
            "artifact_id_b": {"type": "string", "description": "[diff] Second artifact ID (alternative to text_b)."},
            # ── document ──
            "sections": {
                "type": "array",
                "items": {"type": "object"},
                "description": "[document] [{heading, content}, ...] — each section becomes a chapter with anchor."
            },
            "style": {"type": "string", "enum": ["default", "minimal", "dark"], "default": "default",
                      "description": "[document] CSS theme."},
            # ── common ──
            "workspace_id": _S["workspace_id"],
        }, ["action"]),
        description=(
            "Persist and compare documents. "
            "save: persist text as artifact (use for 'save/保存'). "
            "diff: unified diff of two texts or artifacts (use for 'compare/对比'). "
            "document: generate HTML doc with TOC from structured sections."
        ),
    ),

    # 8. config.manage — unified config parsing / translation
    CanonicalToolEntry(
        canonical_tool_id="config.manage",
        handler=_adapt(_handler_config_analysis_run),
        input_schema=_schema({
            "action": {"type": "string",
                       "enum": ["parse", "translate", "extract_interfaces", "extract_routes", "diff", "summarize"]},
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
            "file_id": {"type": "string", "description": "FileStore file_id; takes priority over filepath."},
            "source_config": {"type": "string", "description": "Inline config text."},
            "source_vendor": {"type": "string"},
            "target_vendor": {"type": "string"},
        }, ["action"]),
        description="Config analysis: parse, translate, extract interfaces/routes, diff, summarize.",
    ),

    # 9. pcap.manage — parse / summary / filter / protocol / align / scan
    CanonicalToolEntry(
        canonical_tool_id="pcap.manage",
        handler=_adapt(_handler_pcap_analysis_run),
        input_schema=_schema({
            "action": {
                "type": "string",
                "enum": ["parse", "summary", "filter", "protocol", "align", "scan"],
                "description": (
                    "parse (load+analyze PCAP) | summary (overview stats) | "
                    "filter (by port/IP/protocol) | protocol (per-protocol breakdown) | "
                    "align (TCP sequence/gap analysis) | scan (security/threat detection)"
                ),
            },
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
            "file_id": {"type": "string", "description": "[parse] FileStore file_id (alternative to filepath)."},
            "session_id": _S["session_id"],
            "src": {"type": "string", "description": "[filter|align|scan] Source IP."},
            "sport": {"type": "integer", "description": "[filter|align] Source port."},
            "dst": {"type": "string", "description": "[filter|align|scan] Destination IP."},
            "dport": {"type": "integer", "description": "[filter|align] Destination port."},
            "protocol": {"type": "string", "description": "[protocol|filter] Protocol: TCP/UDP/HTTP/HTTPS/QUIC/DNS."},
        }, ["action"]),
        description=(
            "PCAP packet capture analysis. First parse a file to create a session, "
            "then use summary (overview), filter (by port/IP/protocol), "
            "protocol (per-protocol stats), align (TCP sequence), scan (security)."
        ),
    ),

    # 10. knowledge.manage — search / read / list / chunk / import / manage
    CanonicalToolEntry(
        canonical_tool_id="knowledge.manage",
        handler=_adapt(_handle_knowledge_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {
                "type": "string",
                "enum": ["search", "read", "list", "chunk", "import", "manage"],
                "description": "search (find docs) | read (view chunk) | list (browse sources) | chunk (list chunks) | import (add docs) | manage (disable/delete/reindex).",
            },
            "query": _S["query"],
            "limit": _S["limit"],
            "level": {"type": "string", "enum": ["chunk", "source", "parent"], "default": "chunk"},
            "chunk_id": _S["chunk_id"],
            "source_id": _S["source_id"],
            "action_source": {
                "type": "string", "enum": ["disable", "delete", "reindex"],
                "description": "[manage] disable|delete|reindex.",
            },
            "filepath": _S["filepath"],
            "artifact_id": _S["artifact_id"],
            "title": {"type": "string", "description": "[import] Document title."},
        }, ["action"]),
        description=(
            "RAG knowledge base. search: find relevant documents via BM25. "
            "read: view a chunk. list: browse indexed sources. "
            "chunk: list chunks for a source. import: add markdown/pdf/docx/txt. "
            "manage: disable/delete/reindex sources."
        ),
    ),

    # 11. memory.manage — search / create / update / confirm / delete / profile_get / profile_set
    CanonicalToolEntry(
        canonical_tool_id="memory.manage",
        handler=_adapt(_handle_memory_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string",
                       "enum": ["search", "create", "update", "confirm", "delete",
                                "review", "profile_get", "profile_set"]},
            "query": _S["query"],
            "scope": {"type": "string", "enum": ["short_term", "project", "long_term"],
                      "default": "long_term"},
            "memory_type": {"type": "string", "default": "knowledge_note"},
            "status": {"type": "string"},
            "session_id": _S["session_id"],
            "limit": _S["limit"],
            "title": _S["title"],
            "content": _S["content"],
            "memory_id": _S["memory_id"],
            "tags": {"type": "array", "items": {"type": "string"}},
            "field": {"type": "string", "description": "[profile_set] Profile field name."},
            "value": {"type": "string", "description": "[profile_set] Field value."},
            "merge": {"type": "boolean", "default": True, "description": "[profile_set] Merge with existing."},
        }, ["action"]),
        risk_level="medium",
        description=(
            "Memory store with auto-injection. Memories auto-loaded at session start. "
            "search/list: find memories. create/update: record facts. "
            "review: show pending confirmations. confirm/delete: manage. "
            "profile_get/set: user preferences. NEVER store passwords/keys."
        ),
    ),

    # 12. skill.manage — list / find / load / inspect
    CanonicalToolEntry(
        canonical_tool_id="skill.manage",
        handler=_adapt(_handle_skill_merged),
        input_schema=_schema({
            "action": {"type": "string", "enum": ["list", "search", "load", "inspect"],
                       "default": "list",
                       "description": "list (default) | search | load | inspect."},
            "query": _S["query"],
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 20},
            "skill_name": _S["skill_name"],
        }),
        description=(
            "Unified skill tool. action=list, find, load, inspect. "
            "Read-only discovery; loading does not execute the business task."
        ),
    ),

    # 13. agent.manage — list / spawn / get / cancel / status
    CanonicalToolEntry(
        canonical_tool_id="agent.manage",
        handler=_adapt(_handle_agent_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {
                "type": "string",
                "enum": ["list", "spawn", "get", "cancel", "status"],
                "description": (
                    "list (show agent profiles) | spawn (launch subagent) | "
                    "get (fetch subagent result) | cancel (stop subagent) | "
                    "status (view all subagent tasks)"
                ),
                "default": "list",
            },
            "session_id": _S["session_id"],
            "agent_type": {
                "type": "string",
                "enum": ["explore", "research", "worker", "review"],
                "description": "[spawn] Subagent profile. explore=code search, research=web lookup, worker=full access, review=code check.",
                "default": "explore",
            },
            "instruction": {
                "type": "string",
                "description": "[spawn] Task description for the subagent.",
            },
            "max_turns": {
                "type": "integer", "default": 3, "minimum": 1, "maximum": 10,
                "description": "[spawn] Max tool-call turns for subagent.",
            },
            "background": {
                "type": "boolean", "default": False,
                "description": "[spawn] Run in background (async).",
            },
            "child_session_id": _S["session_id"],
            "subtask_id": {"type": "string", "description": "[cancel] Subagent task ID to cancel."},
        }, ["action"]),
        risk_level="medium",
        description=(
            "Delegates tasks to subagents. Use when: search multiple codebases, "
            "parallel research, independent subtasks. "
            "list: show 4 profiles (explore=code, research=web, worker=full, review=check). "
            "spawn: launch subagent with agent_type+instruction. "
            "get: fetch result. cancel: stop running. status: view all."
        ),
    ),

    # 14. system.manage — 9 system tools merged
    CanonicalToolEntry(
        canonical_tool_id="system.manage",
        handler=_adapt(_handle_system_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string",
                       "enum": ["diagnostics", "health", "selfcheck", "local_info", "tasks", "audit_log",
                                "run_get", "session_get",
                                "session_checkpoint", "session_rewind", "session_export",
                                "session_snapshot", "review_list", "review_update"]},
            "run_id": _S["run_id"],
            "limit": _S["limit"],
            "session_id": _S["session_id"],
            "status": _S["status"],
            "snapshot_id": {"type": "string"},
            "dry_run": _S["dry_run"],
            "format": _S["format"],
            "reason": _S["reason"],
            "review_id": {"type": "string"},
            "log_level": {"type": "string", "enum": ["info", "warn", "error"],
                          "default": "info", "description": "[audit_log] Minimum log level."},
        }, ["action"]),
        risk_level="medium",
        description=(
            "System introspection and session management. "
            "diagnostics/health/selfcheck/local_info/tasks/audit_log for monitoring. "
            "run_get/session_get/session_snapshot/review_list for inspection. "
            "session_checkpoint/rewind/export for recovery. "
            "review_update for annotation. session_rewind requires approval."
        ),
    ),

    # 15. text.analyze
    CanonicalToolEntry(
        canonical_tool_id="text.analyze",
        handler=_adapt(_handle_text_analyze_merged),
        input_schema=_schema({
            "text": _S["text"],
            "action": {
                "type": "string",
                "enum": ["redact", "extract", "match"],
                "description": (
                    "extract (IP/MAC/VLAN/subnet/ASN/hostname from network text) | "
                    "redact (remove passwords/keys/internal IPs) | "
                    "match (regex pattern matching)"
                ),
                "default": "redact",
            },
            "pattern": {"type": "string", "description": "[match] Python regex pattern."},
        }, ["text"]),
        description=(
            "Text analysis for network ops. "
            "extract: find IPs/MACs/VLANs in device output. "
            "redact: remove passwords/keys before sharing. "
            "match: regex pattern matching. Extract first, redact before external use."
        ),
    ),

    # 16. code.search
    CanonicalToolEntry(
        canonical_tool_id="code.search",
        handler=_adapt(_handler_code_search),
        input_schema=_schema({
            "pattern": {"type": "string", "description": "Search pattern (regex or literal)."},
            "directory": {"type": "string", "default": "."},
            "file_type": {"type": "string", "default": ""},
            "max_results": {"type": "integer", "default": 50},
            "context_lines": {"type": "integer", "default": 2,
                              "description": "Lines before/after each match."},
            "output_mode": {"type": "string", "enum": ["content", "files_with_matches", "count"],
                            "default": "content",
                            "description": "content: show matching lines; files_with_matches: file paths; count: match counts."},
            "case_sensitive": {"type": "boolean", "default": False},
            "multiline": {"type": "boolean", "default": False,
                          "description": "Enable multiline matching (dot matches newline)."},
        }, ["pattern"]),
        description=(
            "Search codebase using ripgrep (fast) or Python fallback. "
            "Supports regex, context lines, and multiple output modes."
        ),
    ),

    # 17. workspace.file
    CanonicalToolEntry(
        canonical_tool_id="workspace.file",
        handler=_adapt(_handle_workspace_file_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["list", "read", "read_image",
                                                  "edit", "patch", "write_artifact",
                                                  "glob", "delete"]},
            "subdir": {"type": "string", "description": "[list|glob] Workspace-relative subdirectory."},
            "filepath": _S["filepath"],
            "pattern": {"type": "string", "description": "[glob] File pattern, e.g. **/*.py."},
            "limit": {"type": "integer", "default": 50000,
                      "description": "[read] Max chars to return."},
            "offset": {"type": "integer", "default": 0,
                       "description": "[read] Start reading from line N (0-based)."},
            "old_string": _S["old_string"],
            "new_string": _S["new_string"],
            "replace_all": {"type": "boolean", "default": False, "description": "[edit] Replace all."},
            "dry_run": {"type": "boolean", "default": False,
                        "description": "[edit] Preview diff without writing."},
            "patch_text": _S["patch_text"],
            "filename": {"type": "string", "description": "[write_artifact] Output filename."},
            "content": _S["content"],
        }, ["action"]),
        permission_action="",
        description=(
            "Unified workspace file tool. action=list, read, read_image, glob (reads); "
            "action=edit, patch, write_artifact (writes); action=delete (delete)."
        ),
    ),

    # 18. workspace.artifact
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["list", "read", "save", "tag", "delete"]},
            "status": _S["status"],
            "query": _S["query"],
            "limit": _S["limit"],
            "artifact_id": _S["artifact_id"],
            "title": _S["title"],
            "content": _S["content"],
            "artifact_type": {"type": "string", "description": "[save] Artifact type."},
            "sensitivity": {"type": "string", "enum": ["internal", "sensitive"],
                            "default": "internal"},
            "tags": {"type": "array", "items": {"type": "string"}},
        }, ["action"]),
        permission_action="",
        description=(
            "Workspace artifact management. "
            "action=list (list all), read (view content), save (create), "
            "tag (label), delete (soft-delete, requires approval). "
            "For diff/comparison use report.manage(action=diff). "
            "For saving reports use report.manage(action=save)."
        ),
    ),

    # 19. workspace.filestore
    CanonicalToolEntry(
        canonical_tool_id="workspace.filestore",
        handler=_adapt(_handle_workspace_filestore_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["references", "import"]},
            "file_id": {"type": "string", "description": "[references] FileStore file_id."},
            "filepath": {"type": "string", "description": "[references|import] Workspace-relative path."},
        }, ["action"]),
        description=(
            "Unified FileStore tool. action=references (query cross-refs); "
            "action=import (import a workspace-relative file into FileStore)."
        ),
    ),

    # 20. workspace.metadata.get
    CanonicalToolEntry(
        canonical_tool_id="workspace.metadata.get",
        handler=_adapt(handle_ws_get_metadata),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
        description="Get workspace metadata: name, owner, quota, stats.",
    ),

    # 21. workspace.document.pdf.extract_text
    CanonicalToolEntry(
        canonical_tool_id="workspace.document.pdf.extract_text",
        handler=_adapt(handle_pdf_extract_text),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "page_range": _S["page_range"],
        }, ["filepath"]),
        description="Extract text from PDF files in workspace.",
    ),

    # 22. inspection.manage (CMDB-driven device health inspection)
    CanonicalToolEntry(
        canonical_tool_id="inspection.manage",
        handler=_adapt(_handle_inspection_managed),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {
                "type": "string",
                "enum": ["run", "list", "get", "cancel", "report"],
                "description": "run (start inspection, returns task_id) | list (history) | get (status) | cancel | report.",
            },
            "scope": {
                "type": "object",
                "description": (
                    "[run] CMDB filter. Keys: region, location, search, type (switch|router|firewall|server|other), "
                    "vendor, tags[], asset_ids[], limit (1-500, default 50). "
                    "All optional; {} = all devices."
                ),
            },
            "created_by": {"type": "string", "description": "[run] user|job|system."},
            "session_id": {"type": "string", "description": "[run] Session id."},
            "max_concurrency": {"type": "integer", "description": "[run] Per-task device concurrency (default 3)."},
            "task_id": {"type": "string",
                "description": "[get|cancel|report] Task id from action=run."},
            "limit": {"type": "integer", "description": "[list] Max items (default 50)."},
            "format": {"type": "string", "enum": ["md", "json", "html"], "description": "[report] Report format."},
        }, ["action"]),
        description=(
            "Device health inspection via CMDB. run starts background check "
            "(scope by type/vendor/region), returns task_id. get polls status "
            "(wait for succeeded/partial before report). cancel stops a task. "
            "list shows history. Credentials auto-selected via CMDB."
        ),
    ),
]


CANONICAL_REGISTRY: dict[str, CanonicalToolEntry] = {
    entry.canonical_tool_id: entry for entry in _RAW_REGISTRY
}


def list_canonical_ids() -> list[str]:
    return sorted(CANONICAL_REGISTRY)


def get_entry(canonical_tool_id: str) -> CanonicalToolEntry:
    if canonical_tool_id not in CANONICAL_REGISTRY:
        raise KeyError(f"unknown canonical_tool_id: {canonical_tool_id}")
    return CANONICAL_REGISTRY[canonical_tool_id]


def to_tool_specs() -> list[tuple]:
    """Return list of (ToolSpec, handler) tuples for the ToolRegistry path.

    v3.9.3: governance layer removed. All canonical tools are visible by
    default. A canonical id that fails to resolve in TOOL_NAMESPACE
    (i.e. unknown) is the only case that gets filtered out.
    """
    out: list[tuple] = []
    for entry in _RAW_REGISTRY:
        try:
            from core.tools.tool_namespace import get_namespace_entry
            ns_entry = get_namespace_entry(entry.canonical_tool_id)
        except Exception as exc:
            # v3.10: namespace lookup failing for a canonical id is a
            # real drift bug, not a routine "skip". Surface as a
            # warning so it shows up in logs without crashing the
            # whole registry build.
            logger.warning(
                "to_tool_specs: namespace lookup failed for %s: %s",
                entry.canonical_tool_id, exc,
            )
            ns_entry = None
        # Build the description: prefer the namespace's usage_hint, then
        # the entry description, then the namespace's display_name.
        description = (
            (getattr(ns_entry, "usage_hint", "") if ns_entry else "")
            or entry.description
            or (getattr(ns_entry, "display_name", "") if ns_entry else "")
        )
        # Resolve permission_action:
        # 1. Use explicit value if set on the entry
        # 2. Fallback: infer from namespace entry's action field
        # 3. Final fallback: use PermissionMatrix.action_for_tool()
        perm_action = entry.permission_action
        if not perm_action:
            perm_action = _infer_permission_action(
                entry.canonical_tool_id,
                ns_entry.action if ns_entry else "",
            )
        try:
            from core.tools.manifest_registry import get_manifest
            manifest = get_manifest(entry.canonical_tool_id)
        except Exception as exc:
            # v3.10: a missing manifest is also a real drift bug —
            # the canonical registry and the manifest registry must
            # stay in sync. Warn loudly so the operator notices; we
            # still build a ToolSpec from the entry defaults below
            # so the tool remains callable until the manifest is
            # added.
            logger.warning(
                "to_tool_specs: manifest lookup failed for %s: %s",
                entry.canonical_tool_id, exc,
            )
            manifest = None
        spec = ToolSpec(
            tool_id=entry.canonical_tool_id,
            handler_id=entry.canonical_tool_id,
            description=description,
            category=ns_entry.category if ns_entry else "",
            risk_level=manifest.risk_level if manifest else entry.risk_level,
            requires_approval=manifest.requires_approval if manifest else entry.requires_approval,
            permission_action=perm_action,
            callable_by_llm=getattr(entry, 'callable_by_llm', True),
            enabled=True,
            input_schema=entry.input_schema,
        )
        out.append((spec, entry.handler))
    return out


# Map namespace action strings (from tool_namespace_data.py) to
# PermissionAction values (read|write|exec|network).
_NS_ACTION_TO_PERMISSION: dict[str, str] = {
    # exec
    "exec": "exec", "slash_run": "exec",
    # write
    "edit": "write", "write": "write", "patch": "write",
    "save": "write", "create": "write", "delete": "write",
    "import": "write", "export": "write", "update": "write",
    "archive": "write", "restore": "write", "rebuild": "write",
    "uninstall": "write", "install": "write", "load": "write",
    "unload": "write", "soft_delete": "write", "confirm": "write",
    "rollback": "write", "checkpoint": "write",
    # read
    "read": "read", "list": "read", "preview": "read",
    "search": "read", "get": "read", "summarize": "read",
    "render": "read", "validate": "read", "extract": "read",
    "check": "read", "parse": "read", "translate": "read",
    "classify": "read", "diff": "read", "redact": "read",
    "answer": "read", "explain": "read", "run_summary": "read",
    "run_list": "read", "label": "read", "diagnose": "read",
    "health": "read",
    # network
    "web_search": "network", "weather": "network", "fetch": "network",
    "retrieve": "network",
}


def _infer_permission_action(
    canonical_tool_id: str,
    ns_action: str,
) -> str:
    """Infer permission_action from namespace metadata.

    Precedence:
    1. Category-prefix overrides (web.* → network, host.* → exec)
    2. Explicit mapping from ns_action
    3. Heuristic based on canonical_tool_id prefixes
    4. Fallback to PermissionMatrix.action_for_tool()
    """
    # Category-prefix overrides take priority over ns_action mapping
    if canonical_tool_id.startswith(("web.", "news.", "weather.")):
        return "network"
    if canonical_tool_id.startswith(("host.",)):
        return "exec"

    if ns_action and ns_action in _NS_ACTION_TO_PERMISSION:
        return _NS_ACTION_TO_PERMISSION[ns_action]

    # Heuristic: category-based inference from canonical_tool_id
    if canonical_tool_id.startswith(("workspace.artifact.", "workspace.file.")):
        if any(w in canonical_tool_id for w in ("edit", "write", "save", "create",
                                                  "patch", "delete", "archive",
                                                  "import", "export", "update")):
            return "write"
        return "read"
    if canonical_tool_id.startswith(("knowledge.manage.",)):
        if any(w in canonical_tool_id for w in ("import", "delete", "rebuild")):
            return "write"
        return "read"
    if canonical_tool_id.startswith(("memory.",)):
        if any(w in canonical_tool_id for w in ("create", "update", "delete", "confirm")):
            return "write"
        return "read"
    if canonical_tool_id.startswith(("session.", "run.")):
        if any(w in canonical_tool_id for w in ("export", "rollback", "checkpoint")):
            return "write"
        return "read"
    if canonical_tool_id.startswith(("skill.", "slash.")):
        if any(w in canonical_tool_id for w in ("install", "uninstall", "load", "run")):
            return "exec" if "run" in canonical_tool_id else "write"
        return "read"

    # Final fallback: use PermissionMatrix.action_for_tool(),
    # but default to "read" for truly unknown tools (action_for_tool
    # returns WRITE as its catch-all, which is too permissive here).
    try:
        from agent.runtime.permission_matrix import PermissionMatrix
        action = PermissionMatrix().action_for_tool(canonical_tool_id)
        # action_for_tool defaults to WRITE for unknown tools; we want
        # a conservative default of READ for the fallback path.
        if action.value == "write" and not any(
            canonical_tool_id.startswith(p)
            for p in ("host.", "workspace.", "web.", "knowledge.manage.",
                       "memory.", "session.", "run.", "skill.", "slash.",
                       "runtime.", "text.", "data.", "diagram.")
        ):
            return "read"
        return action.value
    except Exception:
        return "read"
