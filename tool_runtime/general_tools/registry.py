"""Registry for split general tools."""
from copy import deepcopy
from tool_runtime.schemas import ToolSpec
from tool_runtime.general_tools.shared import *
from tool_runtime.general_tools.artifact_tools import handle_artifact_search, handle_artifact_read_content_safe, handle_artifact_save_result, handle_artifact_tag, handle_artifact_delete_soft
from tool_runtime.general_tools.web_tools import handle_web_search, handle_weather_current, handle_weather_forecast, handle_news_search, handle_web_fetch_summary, handle_web_official_doc_search, handle_web_extract_links, handle_web_save_to_artifact
from tool_runtime.general_tools.session_tools import handle_session_list, handle_session_get_summary, handle_session_create, handle_session_archive, handle_run_list_recent, handle_run_get_summary, handle_session_snapshot, handle_session_list_snapshots, handle_session_rewind, handle_session_checkpoint, handle_session_export
from tool_runtime.general_tools.memory_tools import handle_memory_search, handle_memory_create, handle_memory_list, handle_memory_confirm, handle_memory_get_profile, handle_memory_set_profile, handle_memory_update, handle_memory_delete_soft
from tool_runtime.general_tools.skill_tools import handle_skill_list, handle_skill_request_load, handle_skill_load, handle_skill_find, handle_skill_create, handle_skill_inspect
from tool_runtime.general_tools.pdf_tools import handle_pdf_extract_text
from tool_runtime.general_tools.file_tools import handle_file_list, handle_file_exists, handle_file_read, handle_file_edit, handle_file_patch, handle_ws_list_files, handle_ws_read_text_preview, handle_ws_write_artifact_file, handle_ws_path_exists, handle_ws_get_metadata
from tool_runtime.general_tools.command_tools import handle_command_approved_exec, handle_powershell_approved_script, handle_slash_run, handle_python_exec
from tool_runtime.general_tools.agent_tools import handle_agent_spawn, handle_agent_list_roles, handle_agent_team, handle_agent_get_result
from tool_runtime.general_tools.runtime_tools import handle_knowledge_index_artifact, handle_knowledge_reindex, handle_knowledge_search, handle_knowledge_get_source, handle_knowledge_get_chunk_summary, handle_knowledge_explain_not_found, handle_runtime_health, handle_runtime_selfcheck, handle_runtime_diagnostics, handle_runtime_retention_preview, handle_runtime_archive_preview, handle_report_render_markdown, handle_report_save_artifact, handle_doc_render_from_safe_summary, handle_table_render_markdown, handle_diagram_render_mermaid, handle_text_redact, handle_text_diff, handle_text_extract_keywords, handle_text_classify, handle_json_validate, handle_yaml_validate, handle_csv_summarize, handle_table_extract

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
    "memory_id": {"type": "string", "description": "Memory entry id."},
    "old_string": {"type": "string", "description": "Text to replace."},
    "new_string": {"type": "string", "description": "Replacement text."},
    "patch_text": {"type": "string", "description": "Unified diff patch text."},
    "skill_name": {"type": "string", "description": "Skill directory name, e.g. network-troubleshooting."},
    "description": {"type": "string", "description": "Short description of the item or resource."},
    "capabilities": {"type": "array", "description": "List of capability identifiers for this skill.", "items": {"type": "string"}},
    "page_range": {"type": "string", "description": "Optional page range, e.g. 1-3 or 5. If omitted, all pages are read."},
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
    "skill.find_skills": _schema({
        "workspace_id": S["workspace_id"],
        "query": S["query"],
        "limit": S["limit"],
    }, ["query"]),
    "skill.load": _schema({
        "workspace_id": S["workspace_id"],
        "skill_name": S["skill_name"],
        "session_id": S["session_id"],
    }, ["skill_name"]),
    "skill.create": _schema({
        "workspace_id": S["workspace_id"],
        "name": S["skill_name"],
        "description": S["description"],
        "capabilities": S["capabilities"],
    }, ["name"]),
    "skill.inspect": _schema({
        "workspace_id": S["workspace_id"],
        "skill_name": S["skill_name"],
    }, ["skill_name"]),
    "pdf.extract_text": _schema({
        "workspace_id": S["workspace_id"],
        "filepath": S["filepath"],
        "page_range": S["page_range"],
    }, ["filepath"]),

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
    "agent.list_roles": _schema({
        "workspace_id": S["workspace_id"],
    }),
    "agent.get_result": _schema({
        "workspace_id": S["workspace_id"],
        "child_session_id": S["session_id"],
    }, ["child_session_id"]),
    "slash.run": _schema({
        "command": {"type": "string", "description": "Slash command name, e.g. /help, /skills, /context."},
        "args": {"type": "string", "description": "Optional command arguments."},
    }, ["command"]),
    "agent.team": _schema({
        "workspace_id": S["workspace_id"],
        "instruction": {"type": "string", "description": "Task instruction for the team."},
        "roles": {"type": "array", "description": "Roles to use: planner, worker, reviewer. Default: ['planner', 'worker'].", "items": {"type": "string", "enum": ["planner", "worker", "reviewer"]}},
        "session_id": S["session_id"],
    }, ["instruction"]),

    # File
    "file.list": _schema({
        "workspace_id": S["workspace_id"],
        "subdir": {"type": "string", "description": "Workspace-relative subdirectory to list."},
    }),
    "file.exists": _schema({
        "workspace_id": S["workspace_id"],
        "filepath": S["filepath"],
    }, ["filepath"]),
    "file.read": _schema({
        "workspace_id": S["workspace_id"],
        "filepath": S["filepath"],
        "limit": {"type": "integer", "description": "Max chars to read, default 50000.", "default": 50000},
    }, ["filepath"]),
    "file.edit": _schema({
        "workspace_id": S["workspace_id"],
        "filepath": S["filepath"],
        "old_string": S["old_string"],
        "new_string": S["new_string"],
        "replace_all": {"type": "boolean", "description": "Replace all occurrences. Default false.", "default": False},
    }, ["filepath", "old_string", "new_string"]),
    "file.patch": _schema({
        "workspace_id": S["workspace_id"],
        "filepath": S["filepath"],
        "patch_text": S["patch_text"],
    }, ["filepath", "patch_text"]),

    # Memory
    "memory.update": _schema({
        "workspace_id": S["workspace_id"],
        "memory_id": S["memory_id"],
        "content": S["content"],
    }, ["memory_id", "content"]),
    "memory.delete_soft": _schema({
        "workspace_id": S["workspace_id"],
        "memory_id": S["memory_id"],
    }, ["memory_id"]),

    # Session
    "session.checkpoint": _schema({
        "workspace_id": S["workspace_id"],
        "session_id": S["session_id"],
        "reason": S["reason"],
    }, ["session_id"]),
    "session.export": _schema({
        "workspace_id": S["workspace_id"],
        "session_id": S["session_id"],
        "format": {"type": "string", "description": "Export format: json or md.", "enum": ["json", "md"], "default": "md"},
    }, ["session_id"]),
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
         enabled=True, dry_run_supported=True, permission_action=""):
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
        permission_action=permission_action,
    )
    ALL_GENERAL_TOOLS.append((spec, _wrap_general_handler(tool_id, handler)))
    return spec


# ── A. Artifact Tools ──
_reg("artifact.search", "Artifact Search", "artifact", "low",
     "Search workspace artifacts by title/type. Use before reading an artifact when the user references prior outputs, reports, translated configs, or saved web pages.", handle_artifact_search, permission_action="read")
_reg("artifact.read_content_safe", "Read Content Safe", "artifact", "low",
     "Read a size-limited safe preview of artifact content. Use only after artifact.search/list identifies an artifact_id; sensitive artifacts return metadata instead of full content.", handle_artifact_read_content_safe, permission_action="read")
_reg("artifact.save_result", "Save Result", "artifact", "medium",
     "Save useful generated text as an artifact for later reference. Medium risk because it writes workspace state; avoid credential values or raw device configs unless explicitly intended.", handle_artifact_save_result, writes_artifact=True, permission_action="write")
_reg("artifact.tag", "Tag Artifact", "artifact", "low",
     "Add tags to an artifact", handle_artifact_tag, permission_action="write")
_reg("artifact.delete_soft", "Soft Delete", "artifact", "medium",
     "Soft-delete an artifact", handle_artifact_delete_soft, writes_artifact=True, permission_action="write")

# ── B. Knowledge Tools ──
_reg("knowledge.index_artifact", "Index Artifact", "knowledge", "medium",
     "Index a safe artifact into the workspace knowledge base so future answers can retrieve it. Medium risk because it changes retrieval state.", handle_knowledge_index_artifact, writes_artifact=True, permission_action="write")
_reg("knowledge.reindex", "Reindex", "knowledge", "medium",
     "Rebuild chunks for a knowledge source when search results look stale or incomplete. Medium risk because it updates the knowledge index.", handle_knowledge_reindex, writes_artifact=True, permission_action="write")
_reg("knowledge.search", "Knowledge Search", "knowledge", "low",
     "Search the local workspace knowledge base for safe chunks and citations. Use before answering questions about imported docs, prior project knowledge, vendor notes, or user-specific network material.", handle_knowledge_search, permission_action="read")
_reg("knowledge.get_source", "Get Source", "knowledge", "low",
     "Get metadata for a knowledge source id returned by knowledge.search. Does not expose raw source content.", handle_knowledge_get_source, permission_action="read")
_reg("knowledge.get_chunk_summary", "Get Chunk Summary", "knowledge", "low",
     "Get a safe summary for a specific knowledge chunk id when search results need more local context.", handle_knowledge_get_chunk_summary, permission_action="read")
_reg("knowledge.explain_not_found", "Explain Not Found", "knowledge", "low",
     "Explain why search returned no results", handle_knowledge_explain_not_found, permission_action="read")

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
     handle_web_search, input_schema=WEB_SEARCH_INPUT_SCHEMA, permission_action="network")
_reg("web.fetch_summary", "Fetch Summary", "web", "medium",
     "Fetch and summarize a public http(s) webpage after web.search or when the user provides a URL. Blocks private/local URLs; use returned URL/title/summary for cited answers.", handle_web_fetch_summary, permission_action="network")
_reg("web.official_doc_search", "Official Doc Search", "web", "low",
     "Search official vendor documentation by restricting web search to known vendor domains when possible. Use for Cisco/Huawei/H3C/Ruijie/Arista commands, protocols, release behavior, and standards-facing references.", handle_web_official_doc_search, permission_action="network")
_reg("web.extract_links", "Extract Links", "web", "medium",
     "Extract public http(s) links from a webpage when the user asks for references, downloads, related docs, or navigation targets. Blocks private/local URLs.", handle_web_extract_links, permission_action="network")
_reg("web.save_to_artifact", "Save to Artifact", "web", "medium",
     "Fetch a public webpage and save its readable text as a knowledge_doc artifact for later indexing or citation. Medium risk because it writes workspace state; blocks private/local URLs.", handle_web_save_to_artifact, writes_artifact=True, permission_action="network")

# ── D. Session / Run / Memory Tools ──
_reg("session.list", "List Sessions", "session", "low",
     "List workspace sessions", handle_session_list, permission_action="read")
_reg("session.get_summary", "Session Summary", "session", "low",
     "Get session summary (no full content)", handle_session_get_summary, permission_action="read")
_reg("session.create", "Create Session", "session", "medium",
     "Create a new session", handle_session_create, permission_action="write")
_reg("session.archive", "Archive Session", "session", "medium",
     "Soft-archive a session", handle_session_archive, permission_action="write")
_reg("run.list_recent", "Recent Runs", "session", "low",
     "List recent runs (summary only)", handle_run_list_recent, permission_action="read")
_reg("run.get_summary", "Run Summary", "session", "low",
     "Get run summary (no config)", handle_run_get_summary, permission_action="read")

# ── Real-time data tools backed by public web search ──
_reg("weather.current", "Current Weather", "web", "medium",
     "Get current weather for a location using public web results. Medium risk because weather changes quickly; cite returned sources and avoid claiming sensor-grade precision.",
     handle_weather_current, permission_action="network")
_reg("weather.forecast", "Weather Forecast", "web", "medium",
     "Get a short weather forecast for a location using public web results. Medium risk because forecasts change; cite returned sources and mention uncertainty.",
     handle_weather_forecast, permission_action="network")
_reg("news.search", "News Search", "web", "medium",
     "Search recent public news using web search with optional recency/domain filters. Medium risk because news can be incomplete or stale; compare sources before firm claims.",
     handle_news_search, permission_action="network")
_reg("memory.search", "Memory Search", "session", "low",
     "Search memory store", handle_memory_search, permission_action="read")
_reg("skill.list", "List Skills", "skill", "low",
     "List registered agent skills with names and capabilities.",
     handle_skill_list, permission_action="read")
_reg("memory.create", "Create Memory", "memory", "low",
     "Create a long-term memory entry. Do not store secrets, tokens, or passwords.",
     handle_memory_create, permission_action="write")
_reg("memory.list", "List Memories", "memory", "low",
     "List memory entries in the workspace. Returns id + summary only.",
     handle_memory_list, permission_action="read")
_reg("memory.get_profile", "Get Profile", "memory", "low",
     "Get the current workspace user profile.",
     handle_memory_get_profile, permission_action="read")
_reg("memory.set_profile", "Set Profile", "memory", "low",
     "Set a user profile preference. Use for long-term preferences, not secrets.",
     handle_memory_set_profile, permission_action="write")
_reg("skill.request_load", "Request Skill Load", "skill", "low",
     "Request loading a skill. Does NOT directly inject skill into system prompt. "
     "Only records the request for future runtime-controlled loading.",
     handle_skill_request_load, permission_action="write")
_reg("skill.find_skills", "Find Skills", "skill", "low",
     "Search for skills by keyword in their descriptions. Returns matching skill names and metadata.",
     handle_skill_find, permission_action="read")
_reg("skill.load", "Load Skill", "skill", "medium",
     "Load a skill into the current session runtime. Checks skill exists, records as loaded, "
     "and returns SKILL.md content. Does NOT directly inject into system prompt — the context "
     "builder reads loaded skills from session metadata.",
     handle_skill_load, permission_action="write")
_reg("skill.create", "Create Skill", "skill", "medium",
     "Create a new skill skeleton with SKILL.md and skill.yaml. Status is pending_review — does NOT auto-enable.",
     handle_skill_create, writes_artifact=True, permission_action="write")
_reg("skill.inspect", "Inspect Skill", "skill", "low",
     "Read and return a skill's SKILL.md content without loading it into the system prompt.",
     handle_skill_inspect, permission_action="read")
_reg("pdf.extract_text", "Extract PDF Text", "file", "medium",
     "Extract text from a workspace PDF file. Uses PyPDF2 if available.",
     handle_pdf_extract_text, permission_action="read")
_reg("memory.confirm", "Confirm Memory", "memory", "low",
     "Confirm a pending_confirmation memory entry. Changes status from pending to confirmed.",
     handle_memory_confirm, permission_action="write")

# ── E. Runtime Tools ──
_reg("runtime.health", "Runtime Health", "runtime", "low",
     "Check runtime health", handle_runtime_health, permission_action="read")
_reg("runtime.selfcheck", "Self Check", "runtime", "low",
     "Run self-check diagnostics", handle_runtime_selfcheck, permission_action="read")
_reg("runtime.diagnostics", "Diagnostics", "runtime", "low",
     "Get runtime diagnostic report", handle_runtime_diagnostics, permission_action="read")
_reg("runtime.retention_preview", "Retention Preview", "runtime", "low",
     "Preview retention candidates (read-only)", handle_runtime_retention_preview, permission_action="read")
_reg("runtime.archive_preview", "Archive Preview", "runtime", "low",
     "Preview archive state (read-only)", handle_runtime_archive_preview, permission_action="read")

# ── F. Report / Document Tools ──
_reg("report.render_markdown", "Render Markdown", "report", "low",
     "Render markdown from safe summary", handle_report_render_markdown, permission_action="read")
_reg("report.save_artifact", "Save Report", "report", "medium",
     "Save report as artifact", handle_report_save_artifact, writes_artifact=True, permission_action="write")
_reg("doc.render_from_safe_summary", "Render Document", "report", "low",
     "Render document from safe summary", handle_doc_render_from_safe_summary, permission_action="read")
_reg("table.render_markdown", "Render Table", "report", "low",
     "Render table as markdown", handle_table_render_markdown, permission_action="read")
_reg("diagram.render_mermaid", "Render Mermaid", "report", "low",
     "Output Mermaid diagram text", handle_diagram_render_mermaid, permission_action="read")

# ── G. Text / Data Tools ──
_reg("text.redact", "Redact Text", "text", "low",
     "Redact sensitive info from text", handle_text_redact, permission_action="read")
_reg("text.diff", "Text Diff", "text", "low",
     "Compute safe text diff", handle_text_diff, permission_action="read")
_reg("text.extract_keywords", "Extract Keywords", "text", "low",
     "Extract keywords from text", handle_text_extract_keywords, permission_action="read")
_reg("text.classify", "Classify Text", "text", "low",
     "Classify text type (config, general)", handle_text_classify, permission_action="read")
_reg("json.validate", "Validate JSON", "text", "low",
     "Validate JSON syntax (no eval)", handle_json_validate, permission_action="read")
_reg("yaml.validate", "Validate YAML", "text", "low",
     "Validate YAML syntax (safe_load only)", handle_yaml_validate, permission_action="read")
_reg("csv.summarize", "CSV Summarize", "text", "low",
     "Summarize CSV data", handle_csv_summarize, permission_action="read")
_reg("table.extract", "Extract Table", "text", "low",
     "Extract table from markdown", handle_table_extract, permission_action="read")

# ── H. Workspace Safe File Tools ──
_reg("workspace.list_files", "List Files", "workspace", "low",
     "List files in workspace (no path traversal)", handle_ws_list_files, permission_action="read")
_reg("workspace.read_text_preview", "Read Text Preview", "workspace", "low",
     "Read text file preview (size-limited)", handle_ws_read_text_preview, permission_action="read")
_reg("workspace.write_artifact_file", "Write File", "workspace", "medium",
     "Write file to workspace output dir", handle_ws_write_artifact_file, writes_artifact=True, permission_action="write")
_reg("workspace.path_exists", "Path Exists", "workspace", "low",
     "Check if workspace path exists", handle_ws_path_exists, permission_action="read")
_reg("workspace.get_metadata", "Workspace Metadata", "workspace", "low",
     "Get workspace metadata", handle_ws_get_metadata, permission_action="read")

# ── I. Shell / PowerShell Tools (HIGH RISK, approval gated) ──
_reg("shell.exec", "Shell Exec", "shell", "high",
     "Execute shell commands (bash). Use this on Linux/macOS. On Windows use powershell.exec instead. 30s timeout, 10000 chars output. Requires user approval.",
     handle_command_approved_exec, requires_approval=True, permission_action="exec")
_reg("powershell.exec", "PowerShell Exec", "powershell", "high",
     "Execute PowerShell commands. Use this on Windows. On Linux/macOS use shell.exec instead. 15s timeout, 10000 chars output. Requires user approval.",
     handle_powershell_approved_script, requires_approval=True, permission_action="exec")

# ── J. Python Exec Tool (HIGH RISK, AST-sandboxed, approval gated) ──
_reg("python.exec", "Python Exec", "python", "high",
     "Execute Python code in an AST-sandboxed subprocess. Code is checked for forbidden imports (os, subprocess, socket, etc.), forbidden builtins (eval, exec, open, etc.), and dunder access before execution. 10s timeout. Requires user approval.",
     handle_python_exec, requires_approval=True, permission_action="exec")

# ── K. Session Snapshot / Rewind Tools ──
_reg("session.snapshot", "Session Snapshot", "session", "low",
     "Create a snapshot of the current session messages for later recovery or rewind.",
     handle_session_snapshot, permission_action="read")
_reg("session.list_snapshots", "List Snapshots", "session", "low",
     "List all snapshots for a session without full message content.",
     handle_session_list_snapshots, permission_action="read")
_reg("session.rewind", "Session Rewind", "session", "medium",
     "Rewind a session to a previous snapshot. Set dry_run=True to preview without applying. Set dry_run=False to restore messages from the snapshot.",
     handle_session_rewind, permission_action="write")

# ── L. Agent Spawn (Sub-Agent) Tool ──
_reg("agent.spawn", "Spawn Sub-Agent", "session", "medium",
     "Spawn a sub-agent with restricted read-only tool access to research, summarize, or validate data. Returns compressed results. Max 3 turns with only low-risk tools.",
     handle_agent_spawn, requires_approval=False, permission_action="read")
_reg("agent.list_roles", "List Agent Roles", "session", "low",
     "List available agent roles (planner/worker/reviewer) with descriptions and default tools.",
     handle_agent_list_roles, permission_action="read")
_reg("agent.get_result", "Get Sub-Agent Result", "session", "low",
     "Get the result of a previously spawned sub-agent by its child_session_id.",
     handle_agent_get_result, permission_action="read")
_reg("agent.team", "Multi-Agent Team", "session", "medium",
     "PREVIEW: demo implementation only. Multi-agent team with planner/worker/reviewer roles. "
     "Planner breaks tasks down, worker executes them, reviewer (optional) reviews worker output. "
     "Max 3 agents, max 2 turns each. High-risk tools forbidden.",
     handle_agent_team, permission_action="read")

# ── Slash Command Tool ──
_reg("slash.run", "Run Slash Command", "runtime", "low",
     "Execute a slash command (e.g. /help, /skills, /context). See /help for available commands.",
     handle_slash_run, permission_action="read")

# ── File Tools ──
_reg("file.list", "List Files", "file", "low",
     "List files in a workspace subdirectory. Max 50 files. Returns filename, size, suffix.",
     handle_file_list, permission_action="read")
_reg("file.exists", "File Exists", "file", "low",
     "Check whether a workspace file or directory exists. Returns exists, is_file, is_dir, size.",
     handle_file_exists, permission_action="read")
_reg("file.read", "Read File", "file", "low",
     "Read a workspace text file with a generous 50000 char limit. Rejects binary files and paths outside workspace.",
     handle_file_read, permission_action="read")
_reg("file.edit", "Edit File", "file", "medium",
     "Edit a workspace file by string replacement. Only writes to workspaces/<ws>/output/ directory. Returns lines_changed.",
     handle_file_edit, writes_artifact=True, permission_action="write")
_reg("file.patch", "Apply Patch", "file", "medium",
     "Apply a unified diff patch to a workspace file. Returns lines_added and lines_removed.",
     handle_file_patch, writes_artifact=True, permission_action="write")

# ── Memory Update / Delete Tools ──
_reg("memory.update", "Update Memory", "memory", "medium",
     "Update an existing memory entry's content. Checks for secrets before writing.",
     handle_memory_update, permission_action="write")
_reg("memory.delete_soft", "Soft Delete Memory", "memory", "medium",
     "Soft-delete a memory entry. Marks as deleted, does not remove from store.",
     handle_memory_delete_soft, permission_action="write")

# ── Session Checkpoint / Export Tools ──
_reg("session.checkpoint", "Session Checkpoint", "session", "low",
     "Create a checkpoint of the current session state with message_count, run_refs, and artifact_refs.",
     handle_session_checkpoint, permission_action="write")
_reg("session.export", "Export Session", "session", "low",
     "Export session messages as JSON dict or markdown string.",
     handle_session_export, permission_action="write")


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
