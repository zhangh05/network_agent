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

from tool_runtime.schemas import ToolSpec, ToolInvocation
from tool_runtime.registry_helpers import tool_keyword_score


def _adapt(handler: Callable[[ToolInvocation], dict]) -> Callable[..., Any]:
    """Adapter: existing handlers take (inv: ToolInvocation)."""
    def _callable(*args: Any, **kwargs: Any) -> Any:
        if args and isinstance(args[0], ToolInvocation):
            return handler(args[0])
        inv = ToolInvocation(arguments=dict(kwargs), tool_id="")
        return handler(inv)
    return _callable


@dataclass(frozen=True)
class CanonicalToolEntry:
    canonical_tool_id: str
    handler: Callable[..., Any]
    input_schema: dict[str, Any]
    risk_level: str = "low"
    requires_approval: bool = False
    permission_action: str = ""
    description: str = ""

    @property
    def handler_id(self) -> str:
        """Internal dispatch key. By default, equals canonical_tool_id."""
        return self.canonical_tool_id


# ----------------------------------------------------------------------
# Handler imports.
# ----------------------------------------------------------------------

from tool_runtime.general_tools.file_tools import (
    handle_file_list,
    handle_file_exists,
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
from tool_runtime.general_tools.artifact_tools import (
    handle_artifact_search,
    handle_artifact_read_content_safe,
    handle_artifact_save_result,
    handle_artifact_tag,
    handle_artifact_delete_soft,
)
from tool_runtime.general_tools.web_tools import (
    handle_web_search,
    handle_weather_current,
    handle_weather_forecast,
    handle_news_search,
    handle_web_fetch_summary,
    handle_web_official_doc_search,
    handle_web_extract_links,
    handle_web_save_to_artifact,
)
from tool_runtime.general_tools.session_tools import (
    handle_session_list,
    handle_session_get_summary,
    handle_run_list_recent,
    handle_run_get_summary,
    handle_session_snapshot,
    handle_session_list_snapshots,
    handle_session_rewind,
    handle_session_checkpoint,
    handle_session_export,
)
from tool_runtime.general_tools.memory_tools import (
    handle_memory_search,
    handle_memory_create,
    handle_memory_list,
    handle_memory_confirm,
    handle_memory_get_profile,
    handle_memory_set_profile,
    handle_memory_update,
    handle_memory_delete_soft,
)
from tool_runtime.general_tools.skill_tools import (
    handle_skill_list,
    handle_skill_load,
    handle_skill_find,
    handle_skill_inspect,
    handle_skill_create,
    handle_skill_install,
)
from tool_runtime.general_tools.pdf_tools import handle_pdf_extract_text
from tool_runtime.general_tools.command_tools import (
    handle_command_approved_exec,
    handle_powershell_approved_script,
    handle_slash_run,
    handle_python_exec,
)
from tool_runtime.general_tools.agent_tools import (
    handle_agent_spawn,
    handle_agent_list_roles,
    handle_agent_team,
    handle_agent_get_result,
)
from tool_runtime.general_tools.runtime_tools import (
    handle_knowledge_index_artifact,
    handle_knowledge_reindex,
    handle_knowledge_search,
    handle_knowledge_get_source,
    handle_knowledge_get_chunk_summary,
    handle_knowledge_explain_not_found,
    handle_runtime_health,
    handle_runtime_selfcheck,
    handle_runtime_diagnostics,
    handle_runtime_retention_preview,
    handle_runtime_archive_preview,
    handle_report_render_markdown,
    handle_report_save_artifact,
    handle_doc_render_from_safe_summary,
    handle_table_render_markdown,
    handle_diagram_render_mermaid,
    handle_text_redact,
    handle_text_diff,
    handle_text_extract_keywords,
    handle_text_classify,
    handle_json_validate,
    handle_yaml_validate,
    handle_csv_summarize,
    handle_table_extract,
)
from tool_runtime.builtins import (
    _handler_artifact_list,
)


def _safe_int(value, default: int = 0) -> int:
    """Convert value to int safely, returning default on failure."""
    try:
        return int(value or default)
    except (ValueError, TypeError):
        return default


# ── Directory-level tool handlers ────────────────────────────────────

def _handler_config_analysis_run(inv: ToolInvocation) -> dict:
    """Unified config analysis entrypoint — delegates to config_analysis service."""
    from agent.modules.config_analysis.service import run_config_analysis
    args = inv.arguments or {}
    return run_config_analysis(
        action=str(args.get("action", "")),
        workspace_id=inv.workspace_id or args.get("workspace_id", "default"),
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
        workspace_id=inv.workspace_id or args.get("workspace_id", "default"),
        filepath=str(args.get("filepath", "")),
        file_id=str(args.get("file_id", "")),
        session_id=str(args.get("session_id", "")),
        src=str(args.get("src", "")),
        sport=_safe_int(args.get("sport", 0)),
        dst=str(args.get("dst", "")),
        dport=_safe_int(args.get("dport", 0)),
        use_filter=bool(args.get("use_filter", False)),
    )

def _schema(properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
    }


_S = {
    "workspace_id": {"type": "string", "description": "Workspace id."},
    "query": {"type": "string", "description": "Natural language query or keyword. Example: OSPF config, VLAN setup, 本机IP地址."},
    "limit": {"type": "integer", "description": "Max results to return, 1-50.", "default": 10},
    "artifact_id": {"type": "string", "description": "Artifact id."},
    "source_id": {"type": "string", "description": "Knowledge source id."},
    "chunk_id": {"type": "string", "description": "Knowledge chunk id."},
    "url": {"type": "string", "description": "Public http(s) URL."},
    "title": {"type": "string", "description": "Human-readable title."},
    "content": {"type": "string", "description": "Text content."},
    "text": {"type": "string", "description": "Text to inspect or transform."},
    "session_id": {"type": "string", "description": "Session id."},
    "run_id": {"type": "string", "description": "Run id."},
    "filepath": {"type": "string", "description": "Workspace-relative file path. Example: files/topology.txt. NOT absolute paths."},
    "days": {"type": "integer", "description": "Forecast horizon in days, 1-10.", "default": 3},
    "recency": {"type": "string", "description": "Time filter: day, week, month, year.", "default": "week"},
    "format": {"type": "string", "description": "Output format.", "enum": ["txt", "md"]},
    "language": {"type": "string", "description": "Language code, e.g. zh-CN, en.", "default": "zh-CN"},
    "command": {"type": "string", "description": "Shell command to run on THIS machine (macOS/Linux). Example: ifconfig, ping -c 3 8.8.8.8, ls -la, whoami. Do NOT use rm -rf, chmod, sudo."},
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


def _handler_tool_catalog_search(inv: ToolInvocation) -> dict:
    """Search the canonical tool catalog and return loadable tool ids."""
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    args = inv.arguments or {}
    query = str(args.get("query") or "").strip()
    context_summary = str(args.get("context_summary") or "").strip()
    category_filter = str(args.get("category") or "").strip()
    group_filter = str(args.get("group") or "").strip()
    valid_categories = {ns.category for ns in TOOL_NAMESPACE.values()}
    valid_groups = {ns.group for ns in TOOL_NAMESPACE.values()}
    if category_filter and category_filter not in valid_categories:
        if category_filter in valid_groups and not group_filter:
            group_filter = category_filter
        category_filter = ""
    if group_filter and group_filter not in valid_groups:
        group_filter = ""
    try:
        limit = int(args.get("limit") or 8)
    except Exception:
        limit = 8
    limit = max(1, min(limit, 20))

    search_text = " ".join(part for part in (query, context_summary) if part)
    if not search_text:
        return {
            "ok": False,
            "tool_id": "tool.catalog.search",
            "status": "failed",
            "summary": "需要提供要搜索的工具需求。",
            "errors": ["missing_query"],
        }

    tokens = _catalog_query_tokens(search_text)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for tool_id, ns in TOOL_NAMESPACE.items():
        if tool_id == "tool.catalog.search":
            continue
        if category_filter and ns.category != category_filter:
            continue
        if group_filter and ns.group != group_filter:
            continue
        gov = TOOL_GOVERNANCE.get(tool_id)
        if gov is not None and gov.status in {"forbidden", "disabled", "internal"}:
            continue
        entry = CANONICAL_REGISTRY.get(tool_id)
        if entry is None:
            continue
        haystack = " ".join([
            tool_id, ns.category, ns.group, ns.action, ns.display_name,
            ns.short_label, ns.usage_hint, ns.not_for, entry.description,
        ]).lower()
        score = _catalog_score(tool_id, ns.category, ns.group, haystack, tokens, search_text)
        if score <= 0:
            continue
        scored.append((score, tool_id, {
            "tool_id": tool_id,
            "display_name": ns.display_name,
            "category": ns.category,
            "group": ns.group,
            "action": ns.action,
            "risk_level": entry.risk_level,
            "requires_approval": entry.requires_approval,
            "reason": _catalog_reason(tool_id, ns.display_name, score, tokens),
            "usage_hint": ns.usage_hint,
        }))

    scored.sort(key=lambda item: (-item[0], item[1]))
    matches = [item[2] for item in scored[:limit]]
    load_ids = [m["tool_id"] for m in matches]
    expansion = {
        "query": query,
        "context_summary": context_summary[:500],
        "load_tool_ids": load_ids,
        "matched_count": len(matches),
    }
    return {
        "ok": True,
        "tool_id": "tool.catalog.search",
        "status": "succeeded",
        "summary": f"工具目录匹配到 {len(matches)} 个可加载工具。",
        "content": {
            "matched_tools": matches,
            "load_tool_ids": load_ids,
            "instruction": "这些工具已可加入当前回合；下一步请直接调用最合适的工具完成用户需求。",
        },
        "data": {
            "matched_tools": matches,
            "load_tool_ids": load_ids,
        },
        "metadata": {
            "tool_catalog_expansion": expansion,
        },
    }


def _catalog_query_tokens(text: str) -> list[str]:
    import re
    base = [t.lower() for t in re.findall(r"[\w.\-]+", text or "") if len(t.strip()) >= 2]
    lowered = (text or "").lower()
    phrases = {
        "技能": ["skill"], "加载": ["load"], "创建": ["create"], "安装": ["install"],
        "报文": ["pcap", "packet"], "抓包": ["pcap"], "重传": ["retransmission"],
        "序列": ["sequence"], "五元组": ["5tuple"], "tcp": ["tcp"],
        "文件": ["file"], "编辑": ["edit"], "修改": ["edit", "patch"], "补丁": ["patch"],
        "知识库": ["knowledge"], "索引": ["index", "reindex"], "导入": ["import"],
        "记忆": ["memory"], "上下文": ["context"], "运行记录": ["run", "trace"],
        "事件": ["event"], "会话": ["session"], "网页": ["web"], "官方": ["official"],
        "新闻": ["news"], "天气": ["weather"], "表格": ["table"], "json": ["json"],
        "yaml": ["yaml"], "csv": ["csv"], "报告": ["report"],
    }
    expanded = list(base)
    for phrase, additions in phrases.items():
        if phrase in lowered:
            expanded.extend(additions)
    return _ordered_unique(expanded)


def _ordered_unique(items) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _catalog_score(tool_id: str, category: str, group: str, haystack: str, tokens: list[str], text: str) -> int:
    lowered = (text or "").lower()
    score = 0
    for token in tokens:
        if token == tool_id:
            score += 80
        elif token in tool_id:
            score += 28
        elif token in haystack:
            score += 8
    intent_boosts = [
        (("skill", "技能"), "skill.", 35),
        (("load", "加载"), "skill.load", 45),
        (("create", "创建"), "skill.create", 45),
        (("install", "安装"), "skill.install", 45),
        (("pcap", "报文", "抓包", "packet"), "pcap.analysis.run", 40),
        (("retransmission", "重传", "sequence", "序列", "tcp"), "pcap.analysis.run", 42),
        (("config", "配置", "翻译", "translate"), "config.analysis.run", 40),
        (("file", "文件"), "workspace.file.", 22),
        (("edit", "编辑", "修改"), "workspace.file.edit", 40),
        (("patch", "补丁"), "workspace.file.patch", 40),
        (("knowledge", "知识库"), "knowledge.", 30),
        (("import", "导入"), "knowledge.import.", 35),
        (("reindex", "索引"), "knowledge.source.reindex", 35),
        (("memory", "记忆"), "memory.", 28),
        (("run", "运行记录", "trace", "事件"), "run.", 30),
        (("session", "会话"), "session.", 25),
        (("web", "网页", "官方", "新闻", "天气"), "web.", 25),
        (("table", "表格"), "data.table.", 28),
        (("json",), "data.json.validate", 34),
        (("yaml",), "data.yaml.validate", 34),
        (("csv",), "data.csv.summarize", 34),
        (("report", "报告"), "report.", 26),
    ]
    for needles, prefix, boost in intent_boosts:
        if any(n in lowered or n in tokens for n in needles):
            if tool_id == prefix or tool_id.startswith(prefix):
                score += boost
    if category in tokens:
        score += 12
    if group in tokens:
        score += 12
    return score


def _catalog_reason(tool_id: str, display_name: str, score: int, tokens: list[str]) -> str:
    matched = [t for t in tokens[:8] if t in tool_id.lower()]
    if matched:
        return f"{display_name} 与关键词 {', '.join(matched)} 匹配。"
    return f"{display_name} 与当前需求相关，匹配分 {score}。"


# canonical_tool_id -> CanonicalToolEntry
_RAW_REGISTRY: list[CanonicalToolEntry] = [
    # Host
    CanonicalToolEntry(
        canonical_tool_id="host.shell.exec",
        handler=_adapt(handle_command_approved_exec),
        input_schema=_schema({"command": _S["command"]}, ["command"]),
        risk_level="high", requires_approval=True,
        permission_action="exec",
        description="Run a shell command on the local host. Requires approval.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="host.powershell.exec",
        handler=_adapt(handle_powershell_approved_script),
        input_schema=_schema({"command": _S["command"]}, ["command"]),
        risk_level="high", requires_approval=True,
        permission_action="exec",
        description="Run a PowerShell command on the local host. Requires approval.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="host.python.exec",
        handler=_adapt(handle_python_exec),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "code": _S["code"],
            "run_id": _S["run_id"],
            "timeout": {"type": "integer", "description": "Max execution seconds (1-10).", "default": 10},
        }, ["code"]),
        risk_level="high", requires_approval=True,
        permission_action="exec",
        description="Run a Python snippet on the local host. AST-sandboxed.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="host.command.slash_run",
        handler=_adapt(handle_slash_run),
        input_schema=_schema({
            "command": {"type": "string", "description": "Slash command name."},
            "args": {"type": "string", "description": "Optional command arguments."},
        }, ["command"]),
        description="Run a registered slash command.",
    ),

    # Workspace files
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.list",
        handler=_adapt(handle_file_list),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "subdir": {"type": "string", "description": "Workspace-relative subdirectory."},
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.exists",
        handler=_adapt(handle_file_exists),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
        }, ["filepath"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.read",
        handler=_adapt(handle_file_read),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "limit": {"type": "integer", "default": 50000},
        }, ["filepath"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.read_image",
        handler=_adapt(handle_file_read_image),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
        }, ["filepath"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.preview",
        handler=_adapt(handle_ws_read_text_preview),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
        }, ["filepath"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.edit",
        handler=_adapt(handle_file_edit),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "old_string": _S["old_string"], "new_string": _S["new_string"],
            "replace_all": {"type": "boolean", "default": False},
        }, ["filepath", "old_string", "new_string"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.patch",
        handler=_adapt(handle_file_patch),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "patch_text": _S["patch_text"],
        }, ["filepath", "patch_text"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.write_artifact",
        handler=_adapt(handle_ws_write_artifact_file),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "filename": {"type": "string", "description": "Output filename."},
            "content": _S["content"],
        }, ["filename", "content"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.metadata.get",
        handler=_adapt(handle_ws_get_metadata),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),

    # Workspace artifacts
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.list",
        handler=_adapt(_handler_artifact_list),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "status": _S["status"],
            "limit": _S["limit"],
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.read",
        handler=_adapt(handle_artifact_read_content_safe),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "artifact_id": _S["artifact_id"],
        }, ["artifact_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.save",
        handler=_adapt(handle_artifact_save_result),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "title": _S["title"], "content": _S["content"],
            "artifact_type": {"type": "string"},
            "sensitivity": {"type": "string", "enum": ["internal", "sensitive"], "default": "internal"},
        }, ["content"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.search",
        handler=_adapt(handle_artifact_search),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "query": _S["query"], "limit": _S["limit"],
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.tag",
        handler=_adapt(handle_artifact_tag),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "artifact_id": _S["artifact_id"],
            "tags": {"type": "array", "items": {"type": "string"}},
        }, ["artifact_id", "tags"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.delete_soft",
        handler=_adapt(handle_artifact_delete_soft),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "artifact_id": _S["artifact_id"],
        }, ["artifact_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.diff",
        handler=_adapt(handle_text_diff),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "artifact_a": {"type": "string", "description": "First artifact id."},
            "artifact_b": {"type": "string", "description": "Second artifact id."},
        }, ["artifact_a", "artifact_b"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.export",
        handler=_adapt(handle_report_save_artifact),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "artifact_id": {"type": "string"},
            "destination": {"type": "string", "description": "Workspace-relative destination path."},
        }, ["artifact_id", "destination"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.document.pdf.extract_text",
        handler=_adapt(handle_pdf_extract_text),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "page_range": _S["page_range"],
        }, ["filepath"]),
    ),

    # Knowledge
    CanonicalToolEntry(
        canonical_tool_id="knowledge.search",
        handler=_adapt(handle_knowledge_search),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "query": _S["query"], "limit": _S["limit"],
        }, ["query"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.chunk.read",
        handler=_adapt(handle_knowledge_get_chunk_summary),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "chunk_id": _S["chunk_id"],
        }, ["chunk_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.chunk.summary",
        handler=_adapt(handle_knowledge_get_chunk_summary),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "chunk_id": _S["chunk_id"],
        }, ["chunk_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.parent.read",
        handler=_adapt(handle_knowledge_get_source),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "chunk_id": _S["chunk_id"],
        }, ["chunk_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.read",
        handler=_adapt(handle_knowledge_get_source),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }, ["source_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.get",
        handler=_adapt(handle_knowledge_get_source),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }, ["source_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.list",
        handler=_adapt(handle_knowledge_get_source),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.chunk.list",
        handler=_adapt(handle_knowledge_get_source),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.import.file",
        handler=_adapt(handle_knowledge_search),  # placeholder — real impl in agent.modules.knowledge.tools
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
        }, ["filepath"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.import.document",
        handler=_adapt(handle_knowledge_search),  # placeholder — real impl in agent.modules.knowledge.tools
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
        }, ["filepath"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.import.artifact",
        handler=_adapt(handle_knowledge_index_artifact),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "artifact_id": _S["artifact_id"],
        }, ["artifact_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.reindex",
        handler=_adapt(handle_knowledge_reindex),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.reindex_all",
        handler=_adapt(handle_knowledge_reindex),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.disable",
        handler=_adapt(handle_knowledge_search),  # placeholder — real impl in agent.modules.knowledge.tools
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }, ["source_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.delete",
        handler=_adapt(handle_knowledge_search),  # placeholder — real impl in agent.modules.knowledge.tools
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }, ["source_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.not_found.explain",
        handler=_adapt(handle_knowledge_explain_not_found),
        input_schema=_schema({"query": _S["query"], "workspace_id": _S["workspace_id"]}, ["query"]),
    ),

    # Web
    CanonicalToolEntry(
        canonical_tool_id="web.search",
        handler=_adapt(handle_web_search),
        input_schema=_schema({
            "query": _S["query"], "limit": _S["limit"], "recency": _S["recency"],
            "language": _S["language"],
        }, ["query"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="web.docs.official_search",
        handler=_adapt(handle_web_official_doc_search),
        input_schema=_schema({
            "query": _S["query"],
            "vendor": {"type": "string", "description": "Vendor slug."},
        }, ["query"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="web.page.summarize",
        handler=_adapt(handle_web_fetch_summary),
        input_schema=_schema({"url": _S["url"]}, ["url"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="web.page.extract_links",
        handler=_adapt(handle_web_extract_links),
        input_schema=_schema({"url": _S["url"]}, ["url"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="web.page.save_artifact",
        handler=_adapt(handle_web_save_to_artifact),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "url": _S["url"], "title": _S["title"],
        }, ["url"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="web.news.search",
        handler=_adapt(handle_news_search),
        input_schema=_schema({
            "query": _S["query"],
            "top_k": _S["limit"],
            "recency": _S["recency"],
            "language": _S["language"],
        }, ["query"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="web.weather.current",
        handler=_adapt(handle_weather_current),
        input_schema=_schema({
            "location": _S["location"], "units": _S["units"],
            "language": _S["language"],
        }, ["location"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="web.weather.forecast",
        handler=_adapt(handle_weather_forecast),
        input_schema=_schema({
            "location": _S["location"], "days": _S["days"],
            "units": _S["units"], "language": _S["language"],
        }, ["location"]),
    ),

    # Runtime / Run / Session
    CanonicalToolEntry(
        canonical_tool_id="runtime.health",
        handler=_adapt(handle_runtime_health),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="runtime.diagnostics",
        handler=_adapt(handle_runtime_diagnostics),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="runtime.selfcheck",
        handler=_adapt(handle_runtime_selfcheck),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="runtime.retention.preview",
        handler=_adapt(handle_runtime_retention_preview),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="runtime.archive.preview",
        handler=_adapt(handle_runtime_archive_preview),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="run.list",
        handler=_adapt(handle_run_list_recent),
        input_schema=_schema({"workspace_id": _S["workspace_id"], "limit": _S["limit"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="run.summary.get",
        handler=_adapt(handle_run_get_summary),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "run_id": _S["run_id"],
        }, ["run_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="session.list",
        handler=_adapt(handle_session_list),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "status": _S["status"], "limit": _S["limit"],
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="session.summary.get",
        handler=_adapt(handle_session_get_summary),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
        }, ["session_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="session.snapshot.create",
        handler=_adapt(handle_session_snapshot),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
            "reason": _S["reason"],
        }, ["session_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="session.snapshot.list",
        handler=_adapt(handle_session_list_snapshots),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
        }, ["session_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="session.checkpoint",
        handler=_adapt(handle_session_checkpoint),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
        }, ["session_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="session.rewind",
        handler=_adapt(handle_session_rewind),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
            "snapshot_id": {"type": "string"}, "dry_run": _S["dry_run"],
        }, ["session_id", "snapshot_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="session.export",
        handler=_adapt(handle_session_export),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
            "format": _S["format"],
        }, ["session_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="review.item.list",
        handler=_adapt(handle_session_list_snapshots),  # placeholder — real impl in agent.modules.review
        input_schema=_schema({"workspace_id": _S["workspace_id"], "limit": _S["limit"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="review.item.update",
        handler=_adapt(handle_session_snapshot),  # placeholder — real impl in agent.modules.review
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "review_id": {"type": "string"},
            "status": {"type": "string"},
        }, ["review_id", "status"]),
    ),

    # Memory
    CanonicalToolEntry(
        canonical_tool_id="memory.search",
        handler=_adapt(handle_memory_search),
        input_schema=_schema({"query": _S["query"], "limit": _S["limit"]}, ["query"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.list",
        handler=_adapt(handle_memory_list),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "scope": {"type": "string"},
            "memory_type": {"type": "string"}, "status": {"type": "string"},
            "session_id": _S["session_id"], "limit": _S["limit"],
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.create",
        handler=_adapt(handle_memory_create),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "title": _S["title"], "content": _S["content"],
            "scope": {"type": "string", "enum": ["short_term", "project", "long_term"], "default": "long_term"},
            "memory_type": {"type": "string", "default": "knowledge_note"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "string", "default": "agent"},
            "confidence": {"type": "string", "enum": ["system_generated", "user_confirmed", "inferred"], "default": "system_generated"},
            "summary": {"type": "string"},
            "sensitivity": {"type": "string", "enum": ["internal", "sensitive"]},
            "metadata": {"type": "object"},
            "user_confirmed": {"type": "boolean", "default": False},
        }, ["title", "content"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.confirm",
        handler=_adapt(handle_memory_confirm),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "memory_id": _S["memory_id"],
        }, ["memory_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.update",
        handler=_adapt(handle_memory_update),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "memory_id": _S["memory_id"],
            "content": _S["content"],
        }, ["memory_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.delete_soft",
        handler=_adapt(handle_memory_delete_soft),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "memory_id": _S["memory_id"],
        }, ["memory_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.profile.get",
        handler=_adapt(handle_memory_get_profile),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.profile.set",
        handler=_adapt(handle_memory_set_profile),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "field": {"type": "string"},
            "value": {"type": "string"},
            "merge": {"type": "boolean", "default": True},
        }, ["field"]),
    ),

    # Report / Data / Text
    CanonicalToolEntry(
        canonical_tool_id="report.markdown.render",
        handler=_adapt(handle_report_render_markdown),
        input_schema=_schema({"content": _S["content"], "title": _S["title"]}, ["content"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="report.artifact.save",
        handler=_adapt(handle_report_save_artifact),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "title": _S["title"], "content": _S["content"],
        }, ["content"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="document.safe_summary.render",
        handler=_adapt(handle_doc_render_from_safe_summary),
        input_schema=_schema({
            "title": _S["title"],
            "summary": {"type": "string"},
        }, ["summary"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="diagram.mermaid.render",
        handler=_adapt(handle_diagram_render_mermaid),
        input_schema=_schema({"mermaid": {"type": "string"}}, ["mermaid"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="data.table.render",
        handler=_adapt(handle_table_render_markdown),
        input_schema=_schema({
            "rows": {"type": "array"},
            "headers": {"type": "array"},
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="data.table.extract",
        handler=_adapt(handle_table_extract),
        input_schema=_schema({"text": _S["text"]}, ["text"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="data.json.validate",
        handler=_adapt(handle_json_validate),
        input_schema=_schema({"text": _S["text"]}, ["text"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="data.yaml.validate",
        handler=_adapt(handle_yaml_validate),
        input_schema=_schema({"text": _S["text"]}, ["text"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="data.csv.summarize",
        handler=_adapt(handle_csv_summarize),
        input_schema=_schema({"text": _S["text"]}, ["text"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="text.redact",
        handler=_adapt(handle_text_redact),
        input_schema=_schema({"text": _S["text"]}, ["text"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="text.diff",
        handler=_adapt(handle_text_diff),
        input_schema=_schema({
            "text_a": {"type": "string"}, "text_b": {"type": "string"},
        }, ["text_a", "text_b"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="text.keywords.extract",
        handler=_adapt(handle_text_extract_keywords),
        input_schema=_schema({"text": _S["text"], "limit": _S["limit"]}, ["text"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="text.classify",
        handler=_adapt(handle_text_classify),
        input_schema=_schema({"text": _S["text"]}, ["text"]),
    ),

    # Agent / Skill / Slash
    CanonicalToolEntry(
        canonical_tool_id="agent.role.list",
        handler=_adapt(handle_agent_list_roles),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="agent.spawn",
        handler=_adapt(handle_agent_spawn),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
            "instruction": {"type": "string"},
            "allowed_tools": {"type": "array", "items": {"type": "string"}},
            "max_turns": {"type": "integer", "default": 1, "minimum": 1, "maximum": 3},
        }, ["instruction"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="agent.team.run",
        handler=_adapt(handle_agent_team),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "instruction": {"type": "string"},
            "roles": {"type": "array", "items": {"type": "string", "enum": ["planner", "worker", "reviewer"]}},
            "session_id": _S["session_id"],
            "parallel": {"type": "boolean", "description": "Run worker subtasks in parallel (up to 3 concurrent)"},
        }, ["instruction"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="agent.result.get",
        handler=_adapt(handle_agent_get_result),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "child_session_id": _S["session_id"],
        }, ["child_session_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="tool.catalog.search",
        handler=_adapt(_handler_tool_catalog_search),
        input_schema=_schema({
            "query": _S["query"],
            "context_summary": {"type": "string", "description": "Optional short summary of the current conversation, page, memory, or prior tool result."},
            "category": {"type": "string", "description": "Optional category filter such as network, workspace, knowledge, memory, web, agent."},
            "group": {"type": "string", "description": "Optional group filter such as pcap, file, skill, source."},
            "limit": {"type": "integer", "description": "Max tools to return, 1-20.", "default": 8},
        }, ["query"]),
        description="Search the full tool catalog and return loadable specialized tool_ids for the current turn.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.list",
        handler=_adapt(handle_skill_list),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.load",
        handler=_adapt(handle_skill_load),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "skill_name": _S["skill_name"], "session_id": _S["session_id"],
        }, ["skill_name"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.unload",
        handler=_adapt(handle_skill_load),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "skill_name": _S["skill_name"], "session_id": _S["session_id"],
            "unload": {"type": "boolean", "default": True},
        }, ["skill_name"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.search",
        handler=_adapt(handle_skill_find),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "query": _S["query"], "limit": _S["limit"],
        }, ["query"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.get",
        handler=_adapt(handle_skill_inspect),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "skill_name": _S["skill_name"],
        }, ["skill_name"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.create",
        handler=_adapt(handle_skill_create),
        input_schema=_schema({
            "name": {"type": "string", "description": "Skill name (alphanumeric, hyphens, underscores)"},
            "description": {"type": "string", "description": "What this skill does"},
            "capabilities": {"type": "array", "items": {"type": "string"}, "description": "List of capability IDs"},
        }, ["name"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.install",
        handler=_adapt(handle_skill_install),
        input_schema=_schema({
            "source": {"type": "string", "description": "Local dir path, archive URL (.zip/.tar.gz), or SKILL.md markdown content"},
            "skill_name": {"type": "string", "description": "Skill directory name (auto-detected if omitted)"},
        }, ["source"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="slash.command.list",
        handler=_adapt(handle_skill_list),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="slash.command.run",
        handler=_adapt(handle_slash_run),
        input_schema=_schema({
            "command": {"type": "string"},
            "args": {"type": "string"},
        }, ["command"]),
    ),
    # ── Directory-level business tools ──
    CanonicalToolEntry(
        canonical_tool_id="config.analysis.run",
        handler=_handler_config_analysis_run,
        input_schema=_schema({
            "action": {"type": "string", "description": "Action: parse, translate, extract_interfaces, extract_routes, diff, summarize.", "enum": ["parse", "translate", "extract_interfaces", "extract_routes", "diff", "summarize"]},
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
            "file_id": {"type": "string", "description": "FileStore file_id. When provided, reads config from FileStore. Takes priority over filepath."},
            "source_config": {"type": "string", "description": "Inline config text (alternative to filepath)."},
            "source_vendor": {"type": "string", "description": "Source vendor, e.g. huawei, h3c, cisco."},
            "target_vendor": {"type": "string", "description": "Target vendor for translation."},
        }, ["action"]),
        description="Unified config analysis: parse, translate, extract, diff, summarize.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="pcap.analysis.run",
        handler=_handler_pcap_analysis_run,
        input_schema=_schema({
            "action": {"type": "string", "description": "Action: parse, session, filter, align.", "enum": ["parse", "session", "filter", "align"]},
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
            "session_id": _S["session_id"],
            "src": {"type": "string", "description": "Source IP for filter."},
            "sport": {"type": "integer", "description": "Source port for filter."},
            "dst": {"type": "string", "description": "Destination IP for filter."},
            "dport": {"type": "integer", "description": "Destination port for filter."},
        }, ["action"]),
        description="Unified PCAP analysis: parse, session, filter, align.",
    ),
    # ── FileStore tools ──
    CanonicalToolEntry(
        canonical_tool_id="file.get",
        handler=lambda inv: __import__("tool_runtime.general_tools.filestore_tools", fromlist=["handle_file_get"]).handle_file_get(inv, file_id=inv.arguments.get("file_id", ""), limit=inv.arguments.get("limit", 2000)),
        input_schema=_schema({
            "file_id": {"type": "string", "description": "FileStore file_id to read."},
            "limit": {"type": "integer", "description": "Max chars to return.", "default": 2000},
        }, ["file_id"]),
        description="Read text content of a FileStore-managed file by file_id.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="file.preview",
        handler=lambda inv: __import__("tool_runtime.general_tools.filestore_tools", fromlist=["handle_file_preview"]).handle_file_preview(inv, file_id=inv.arguments.get("file_id", ""), limit=inv.arguments.get("limit", 500)),
        input_schema=_schema({
            "file_id": {"type": "string", "description": "FileStore file_id to preview."},
            "limit": {"type": "integer", "description": "Preview length.", "default": 500},
        }, ["file_id"]),
        description="Preview a FileStore file: metadata + text preview.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="file.references",
        handler=lambda inv: __import__("tool_runtime.general_tools.filestore_tools", fromlist=["handle_file_references"]).handle_file_references(inv, file_id=inv.arguments.get("file_id", "")),
        input_schema=_schema({
            "file_id": {"type": "string", "description": "FileStore file_id to query references for."},
        }, ["file_id"]),
        description="Query cross-references for a FileStore file.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="file.write_agent_output",
        handler=lambda inv: __import__("tool_runtime.general_tools.filestore_tools", fromlist=["handle_file_write_agent_output"]).handle_file_write_agent_output(inv, content=inv.arguments.get("content", ""), logical_type=inv.arguments.get("logical_type", "artifact_output"), file_kind=inv.arguments.get("file_kind", "text"), title=inv.arguments.get("title", ""), ext=inv.arguments.get("ext", "txt")),
        input_schema=_schema({
            "content": {"type": "string", "description": "Content to write."},
            "logical_type": {"type": "string", "description": "Logical type.", "default": "artifact_output"},
            "file_kind": {"type": "string", "description": "File kind.", "default": "text"},
            "title": {"type": "string", "description": "Title for the artifact."},
            "ext": {"type": "string", "description": "File extension.", "default": "txt"},
        }, ["content"]),
        description="Write output through FileStore and get file_id.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="file.import_workspace_path",
        handler=lambda inv: __import__("tool_runtime.general_tools.filestore_tools", fromlist=["handle_file_import_workspace_path"]).handle_file_import_workspace_path(inv, filepath=inv.arguments.get("filepath", "")),
        input_schema=_schema({
            "filepath": {"type": "string", "description": "Workspace-relative path to import."},
        }, ["filepath"]),
        description="Import a workspace file into FileStore and get file_id.",
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


def dispatch(canonical_tool_id: str, **kwargs) -> Any:
    entry = get_entry(canonical_tool_id)
    return entry.handler(**kwargs)


def to_tool_specs() -> list[tuple]:
    """Return list of (ToolSpec, handler) tuples for the ToolRegistry path.

    v3.0: returns a list of (spec, handler) so callers can register
    directly. Forbidden entries are skipped.
    """
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    out: list[tuple] = []
    for entry in _RAW_REGISTRY:
        gov = TOOL_GOVERNANCE.get(entry.canonical_tool_id)
        if gov is None or gov.status == "forbidden":
            continue
        ns_entry = None
        try:
            from tool_runtime.tool_namespace import get_namespace_entry
            ns_entry = get_namespace_entry(entry.canonical_tool_id)
        except Exception:
            pass
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
        spec = ToolSpec(
            tool_id=entry.canonical_tool_id,
            handler_id=entry.canonical_tool_id,
            description=description,
            category=ns_entry.category if ns_entry else "",
            risk_level=entry.risk_level,
            requires_approval=entry.requires_approval,
            permission_action=perm_action,
            callable_by_llm=True,
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
    if canonical_tool_id.startswith(("knowledge.",)):
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
            for p in ("host.", "workspace.", "web.", "knowledge.",
                       "memory.", "session.", "run.", "skill.", "slash.",
                       "runtime.", "text.", "data.", "diagram.")
        ):
            return "read"
        return action.value
    except Exception:
        return "read"
