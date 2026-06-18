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
from tool_runtime.general_tools.file_tools import handle_file_list, handle_file_exists, handle_file_read, handle_file_edit, handle_file_patch, handle_ws_list_files, handle_ws_read_text_preview, handle_ws_write_artifact_file, handle_ws_path_exists, handle_ws_get_metadata, handle_file_read_image
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
    "filepath": {"type": "string", "description": "Workspace-relative file path, e.g. sys/state.json or files/report.md."},
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
    "new_string": {"type": "string", "description": "New text to insert in place of the old text."},
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
    "workspace.artifact.save": _schema({
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
    "web.docs.official_search": _schema({
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
    "session.summary.get": _schema({"workspace_id": S["workspace_id"], "session_id": S["session_id"]}, ["session_id"]),
    "session.create": _schema({"workspace_id": S["workspace_id"], "title": S["title"]}),
    "session.archive": _schema({"workspace_id": S["workspace_id"], "session_id": S["session_id"]}, ["session_id"]),
    "run.list": _schema({"workspace_id": S["workspace_id"], "limit": S["limit"]}),
    "run.summary.get": _schema({"workspace_id": S["workspace_id"], "run_id": S["run_id"]}, ["run_id"]),
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
    "workspace.file.list": _schema({"workspace_id": S["workspace_id"], "subdir": {"type": "string", "description": "Workspace-relative subdirectory."}}),
    "workspace.file.preview": _schema({"workspace_id": S["workspace_id"], "filepath": {"type": "string", "description": "Workspace-relative text file path."}}, ["filepath"]),
    "workspace.write_artifact_file": _schema({"workspace_id": S["workspace_id"], "filename": {"type": "string", "description": "Output filename, e.g. report.md or output.json."}, "content": S["content"]}, ["filename", "content"]),
    "workspace.file.exists": _schema({"workspace_id": S["workspace_id"], "filepath": S["filepath"]}, ["filepath"]),
    "workspace.get_metadata": _schema({"workspace_id": S["workspace_id"]}),

    # Approved high-risk surfaces
    "host.shell.exec": _schema({"command": {"type": "string", "description": "Bash command. For Linux/macOS. On Windows, use powershell.exec."}}, ["command"]),
    "host.powershell.exec": _schema({"command": {"type": "string", "description": "PowerShell command. For Windows. On Linux/macOS, use shell.exec."}}, ["command"]),

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
    "workspace.file.list": _schema({
        "workspace_id": S["workspace_id"],
        "subdir": {"type": "string", "description": "Workspace-relative subdirectory to list."},
    }),
    "workspace.file.exists": _schema({
        "workspace_id": S["workspace_id"],
        "filepath": S["filepath"],
    }, ["filepath"]),
    "workspace.file.read": _schema({
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
        "artifact": ["如需正文，下一步用 artifact.read_content_safe 读取 artifact_id；如需索引到知识库，用 knowledge.index_artifact。"],
        "knowledge": ["根据返回的 chunk/source id 继续调用 knowledge.get_chunk_summary 或 knowledge.get_source。如无结果，尝试 artifact.search、web.search 或让用户上传资料。"],
        "web": ["用返回的 citation/URL 回答并引用来源。需要正文细节时调用 web.fetch_summary。如 web.search 无结果，尝试 web.official_doc_search 或让用户提供 URL。"],
        "weather": ["直接使用 current/forecast_daily 字段回答，并引用来源 URL 和更新时间。"],
        "news": ["交叉比较前几条来源的发布时间和作者，避免把单一网页当最终事实。区分官方公告与媒体报道。"],
        "session": ["如需展开某条记录，继续调用对应 get_summary 工具。如找不到 session，检查 session.list。"],
        "run": ["如需展开某条运行记录，继续调用 run.get_summary。如找不到 run，检查 run.list_recent。"],
        "memory": ["如结果不足，换更具体关键词重试。如无相关记忆，说明当前知识库无此记录，建议用户明确告知。"],
        "skill": ["根据返回的 skill 名称和描述判断是否匹配用户需求。如需加载，使用 skill.load。"],
        "runtime": ["根据 diagnostics/health 的组件状态给出下一步排查建议。如工具注册有问题，检查 registry 状态。"],
        "report": ["将生成内容直接返回用户，或用 report.save_artifact 保存到 workspace。"],
        "doc": ["将生成文档内容直接返回用户，或保存为 artifact。"],
        "table": ["用表格内容直接回答；如为空，说明没有可提取的表格数据。"],
        "diagram": ["把 Mermaid 文本返回用户或嵌入 Markdown 报告。用户需要渲染时建议用 Mermaid 兼容查看器。"],
        "text": ["基于转换/分析结果继续回答用户。如分类有误，重新传入文本调整。"],
        "json": ["根据 valid/error 告诉用户 JSON 是否可用。如无效，指出具体错误位置和建议修复。"],
        "yaml": ["根据 valid/error 告诉用户 YAML 是否可用。如无效，指出缩进/语法问题。"],
        "csv": ["用 rows/columns/header 总结 CSV 结构。如需深度分析，用 python.exec 做数据处理（需审批）。"],
        "workspace": ["根据 workspace 文件状态继续读取或写入输出文件。如路径不存在，用 workspace.path_exists 验证。"],
        "command": ["只使用 allowlisted 只读结果，不要声称执行了未批准命令。如被拒绝，告知用户待审批的具体命令。"],
        "powershell": ["只使用 allowlisted 只读结果，不要声称执行了未批准脚本。如被拒绝，告知用户可在本地 PowerShell 手动执行。"],
        "shell": ["只使用 allowlisted 只读结果，不要声称执行了未批准命令。如被拒绝，告知用户待审批命令或手动执行。"],
        "python": ["只使用沙箱内返回结果。如被拒绝，可将代码发给用户手动运行。"],
        "parser": ["基于解析结果继续分析。如解析失败，让用户粘贴原始配置，尝试 text.extract_keywords 或保存到 artifact 再处理。"],
        "file": ["基于文件内容回答。如读取失败，用 file.list 确认路径，或用 file.exists 验证。替换路径不能解决问题时询问用户。"],
        "agent": ["子 agent 结果已返回，可直接用于回答。如需更多细节，用 agent.get_result 获取。如子 agent 超时，减少 max_turns。"],
        "pdf": ["基于提取的文本回答。如提取失败（非 PDF、加密 PDF），告知用户支持的格式并建议转换。"],
        "slash": ["返回命令输出给用户。如命令未识别，用 /help 查看可用命令列表。"],
    }
    return defaults.get(group, ["使用工具返回的数据继续回答用户。如数据不足，选择同场景的相邻工具重试。"])


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
     "Search workspace artifacts by title/type/keywords. Use when: user references prior outputs, reports, translated configs, or saved web pages. Not for: raw file system search (use file.list). Returns artifact_id, title, type, tags for each match. Read-only. Keep query specific.", handle_artifact_search, permission_action="read")
_reg("artifact.read_content_safe", "Read Content Safe", "artifact", "low",
     "Read a size-limited safe preview of artifact content. Use ONLY after artifact.search/list identifies an artifact_id. Sensitive artifacts return metadata-only. Not for: reading raw files (use file.read). Read-only. Returns text preview or metadata block.", handle_artifact_read_content_safe, permission_action="read")
_reg("workspace.artifact.save", "Save Result", "artifact", "medium",
     "Save generated text/analysis as a workspace artifact for later reference or knowledge indexing. Use when: user asks to export, save, generate report, keep result. Not for: transient chat answers. Medium risk (writes workspace state). Do NOT store passwords, tokens, or raw device configs. Returns artifact_id.", handle_artifact_save_result, writes_artifact=True, permission_action="write")
_reg("artifact.tag", "Tag Artifact", "artifact", "low",
     "Add tags to an existing artifact for categorization. Use when: user wants to label/categorize an artifact. Read-only for artifacts (write for metadata). Returns updated tag list.", handle_artifact_tag, permission_action="write")
_reg("artifact.delete_soft", "Soft Delete", "artifact", "medium",
     "Soft-delete an artifact (marks as deleted, recoverable). Use when: user explicitly asks to delete/remove an artifact. WARNING: This is a delete operation — confirm with user. Returns confirmation. Requires explicit approval in v2.1.2.", handle_artifact_delete_soft, writes_artifact=True, permission_action="write")

# ── B. Knowledge Tools ──
_reg("knowledge.index_artifact", "Index Artifact", "knowledge", "medium",
     "Index a safe artifact into the workspace knowledge base so future answers can retrieve it. Use when: user wants to make an artifact searchable. Medium risk (changes retrieval state). Returns indexing confirmation with chunk count.", handle_knowledge_index_artifact, writes_artifact=True, permission_action="write")
_reg("knowledge.reindex", "Reindex", "knowledge", "medium",
     "Rebuild chunks for a knowledge source when search results look stale or incomplete. Use when: knowledge search returns unexpected/empty results. Medium risk (updates index). Returns reindexing status.", handle_knowledge_reindex, writes_artifact=True, permission_action="write")
_reg("knowledge.search", "Knowledge Search", "knowledge", "low",
     "Search the local workspace knowledge base for safe chunks and citations. Use when: user asks about imported docs, prior project knowledge, vendor notes, or user-specific network material. Not for: web search (use web.search), memory search (use memory.search). Read-only. Returns ranked chunks with source citations [K1] etc.", handle_knowledge_search, permission_action="read")
_reg("knowledge.get_source", "Get Source", "knowledge", "low",
     "Get metadata for a knowledge source id returned by knowledge.search. Use when: user asks about the origin/date/type of a knowledge source. Does NOT expose raw source content. Read-only. Returns source metadata dict.", handle_knowledge_get_source, permission_action="read")
_reg("knowledge.get_chunk_summary", "Get Chunk Summary", "knowledge", "low",
     "Get a safe summary for a specific knowledge chunk id. Use when: search results need more local context around a specific chunk. Read-only. Returns chunk text summary with surrounding context hints.", handle_knowledge_get_chunk_summary, permission_action="read")
_reg("knowledge.explain_not_found", "Explain Not Found", "knowledge", "low",
     "Explain why knowledge search returned no results — analyzes query terms, available sources, and indexing status. Use when: knowledge.search returns empty. Read-only. Returns diagnostic explanation and suggestions (try different keywords, upload docs, use web search instead).", handle_knowledge_explain_not_found, permission_action="read")

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
     "Search public web pages for current or external information. Use when: user asks to look up public information, product docs, vendor examples, recent releases, GitHub projects, or any fact that may have changed. Not for: local workspace files, uploaded configs, private URLs, or official vendor docs (use web.official_doc_search). Returns ranked results with title/URL/domain/snippet/source-quality. Medium risk (network call, results may vary). Requires network permission.", handle_web_search, input_schema=WEB_SEARCH_INPUT_SCHEMA, permission_action="network")
_reg("web.fetch_summary", "Fetch Summary", "web", "medium",
     "Fetch and summarize a public http(s) webpage. Use after web.search or when user provides a URL. Blocks private/local URLs (localhost, 192.168.x, 10.x). Not for: workspace files (use file.read), artifacts (use artifact.read_content_safe). Returns URL, title, and text summary. Medium risk (network call).", handle_web_fetch_summary, permission_action="network")
_reg("web.docs.official_search", "Official Doc Search", "web", "low",
     "Search official vendor documentation by restricting to known vendor domains (cisco.com, huawei.com, h3c.com, juniper.net, arista.com, ietf.org, rfc-editor.org). Use when: user asks for vendor commands, protocol specs, release behavior, standards. Not for: general web search (use web.search), community forums. Low risk (domain-restricted). Read-only. Returns official doc results with domain markers.", handle_web_official_doc_search, permission_action="network")
_reg("web.extract_links", "Extract Links", "web", "medium",
     "Extract public http(s) links from a webpage. Use when: user asks for references, downloads, related docs, or navigation targets from a page. Blocks private/local URLs. Returns list of links with text/title. Medium risk (network call).", handle_web_extract_links, permission_action="network")
_reg("web.save_to_artifact", "Save to Artifact", "web", "medium",
     "Fetch a public webpage and save its readable text as a knowledge_doc artifact for later indexing or citation. Use when: user wants to preserve a page for offline reference. Medium risk (writes workspace state, network call). Blocks private/local URLs. Returns artifact_id.", handle_web_save_to_artifact, writes_artifact=True, permission_action="network")

# ── D. Session / Run / Memory Tools ──
_reg("session.list", "List Sessions", "session", "low",
     "List all sessions in the workspace with summary metadata (title, created_at, message_count, status). Use when: user asks about past sessions, wants to switch context, or needs an overview. Read-only. Returns session list with ids.", handle_session_list, permission_action="read")
_reg("session.summary.get", "Session Summary", "session", "low",
     "Get a session's summary metadata WITHOUT exposing full message content. Use when: user asks about a specific session's context. Read-only. Returns title, timestamps, run count, tags.", handle_session_get_summary, permission_action="read")
_reg("session.create", "Create Session", "session", "medium",
     "Create a new conversation session. Use when: user wants a fresh context or new topic. Medium risk (creates persistent state). Returns new session_id.", handle_session_create, permission_action="write")
_reg("session.archive", "Archive Session", "session", "medium",
     "Soft-archive a session (marks as archived, recoverable). Use when: user wants to clean up old sessions. Medium risk (modifies session state). Returns confirmation.", handle_session_archive, permission_action="write")
_reg("run.list", "Recent Runs", "session", "low",
     "List recent agent runs with summary metadata (tool_calls count, status, duration, timestamp). Use when: user asks about recent activity, wants to inspect a past run, or debug agent behavior. Read-only. Returns run list with run_ids.", handle_run_list_recent, permission_action="read")
_reg("run.summary.get", "Run Summary", "session", "low",
     "Get a specific run's summary including tool calls, warnings, errors, trace metadata, and final response. Use when: user asks why a previous answer behaved a certain way, what tools were called, or to debug an agent turn. Read-only (no config exposure). Returns run detail dict with tool_calls array.", handle_run_get_summary, permission_action="read")

# ── Real-time data tools backed by public web search ──
_reg("weather.current", "Current Weather", "web", "medium",
     "Get current weather for a location using public web results. Use when: user asks about current weather. Not for: forecasting (use weather.forecast), climate data, or hyper-local precision. Medium risk (results change rapidly, source dependent). Read-only. Cite returned sources and note uncertainty.", handle_weather_current, permission_action="network")
_reg("weather.forecast", "Weather Forecast", "web", "medium",
     "Get a short weather forecast (1-10 days) for a location. Use when: user asks about upcoming weather. Not for: current conditions (use weather.current), long-term climate. Medium risk (forecasts change). Read-only. Cite sources and mention forecast uncertainty.", handle_weather_forecast, permission_action="network")
_reg("news.search", "News Search", "web", "medium",
     "Search recent public news with optional recency and domain filters. Use when: user asks about current events, industry news, vendor announcements. Not for: academic research, historical facts, opinion verification. Medium risk (news may be incomplete or biased). Read-only. Compare multiple sources before firm claims.", handle_news_search, permission_action="network")
_reg("memory.search", "Memory Search", "session", "low",
     "Search the persistent memory store for user preferences, past decisions, and long-term facts. Use when: user says '我之前说过', '记住的', or asks about previously stored information. Not for: knowledge base search (use knowledge.search), session history (use run.list_recent). Read-only. Returns ranked memory entries with ids.", handle_memory_search, permission_action="read")
_reg("skill.list", "List Skills", "skill", "low",
     "List all registered agent skills with names, descriptions, capabilities, and enabled status. Use when: user asks what skills are available or wants to load a skill. Read-only. Returns skill catalog with skill_name identifiers.", handle_skill_list, permission_action="read")
_reg("memory.create", "Create Memory", "memory", "low",
     "Create a long-term memory entry. Use when: user explicitly asks to remember/save a preference, decision, or important fact. NOT for: secrets, tokens, passwords, one-time facts, or ephemeral data. Writes to persistent memory store. Returns memory_id. Do NOT create memories without user confirmation.", handle_memory_create, permission_action="write")
_reg("memory.list", "List Memories", "memory", "low",
     "List memory entries for the workspace. Returns id and summary only — no full content. Use when: user wants to browse stored memories. Read-only. Filterable by scope, type, status.", handle_memory_list, permission_action="read")
_reg("memory.get_profile", "Get Profile", "memory", "low",
     "Get the current workspace user profile (preferences, expertise, context). Use when: establishing user context before answering. Read-only. Returns profile dict with explicit_preferences.", handle_memory_get_profile, permission_action="read")
_reg("memory.set_profile", "Set Profile", "memory", "low",
     "Set a user profile preference. Use for: long-term preferences (language, expertise level, output style). NOT for: secrets, API keys, passwords. Writes to profile. Returns confirmation.", handle_memory_set_profile, permission_action="write")
_reg("skill.request_load", "Request Skill Load", "skill", "low",
     "Request loading a skill into the current session. Does NOT directly inject skill into system prompt — only records the request for future runtime-controlled loading. Use when: user asks to enable a skill. Returns request confirmation.", handle_skill_request_load, permission_action="write")
_reg("skill.find_skills", "Find Skills", "skill", "low",
     "Search for skills by keyword in their descriptions. Use when: user asks about available skills matching a topic. Read-only. Returns matching skill names and metadata.", handle_skill_find, permission_action="read")
_reg("skill.load", "Load Skill", "skill", "medium",
     "Load a skill into the current session runtime. Checks skill exists, records as loaded, and returns SKILL.md content. The context builder reads loaded skills from session metadata — NOT directly injected. Use when: user explicitly confirms skill loading. Medium risk (changes runtime behavior).", handle_skill_load, permission_action="write")
_reg("skill.create", "Create Skill", "skill", "medium",
     "Create a new skill skeleton with SKILL.md and skill.yaml. Status is pending_review — does NOT auto-enable. Use when: user wants to create a new custom skill. Medium risk (creates workspace files). Returns created skill metadata.", handle_skill_create, writes_artifact=True, permission_action="write")
_reg("skill.inspect", "Inspect Skill", "skill", "low",
     "Read and return a skill's SKILL.md content WITHOUT loading it into the system prompt. Use when: user wants to review a skill before loading it. Read-only. Returns full SKILL.md text.", handle_skill_inspect, permission_action="read")
_reg("pdf.extract_text", "Extract PDF Text", "file", "medium",
     "Extract text from a workspace PDF file using PyPDF2 (if available). Use when: user uploads or references a PDF document in the workspace. Not for: non-PDF files (use file.read), password-protected PDFs. Medium risk (file I/O). Read-only. Returns extracted text with page markers. Supports page_range for large documents.", handle_pdf_extract_text, permission_action="read")
_reg("memory.confirm", "Confirm Memory", "memory", "low",
     "Confirm a pending_confirmation memory entry. Changes status from pending to confirmed, making it active for RAG retrieval. Use when: user agrees to store a suggested memory. Returns confirmation status.", handle_memory_confirm, permission_action="write")

# ── E. Runtime Tools ──
_reg("runtime.health", "Runtime Health", "runtime", "low",
     "Check the overall runtime health status including component availability, tool registry status, and service connectivity. Use when: user asks about system status or if something seems broken. Read-only. Returns health check dict with component statuses.", handle_runtime_health, permission_action="read")
_reg("runtime.selfcheck", "Self Check", "runtime", "low",
     "Run comprehensive self-check diagnostics across all runtime components. Use for: systematic debugging of runtime issues. Read-only. Returns diagnostic report with pass/fail per component.", handle_runtime_selfcheck, permission_action="read")
_reg("runtime.diagnostics", "Diagnostics", "runtime", "low",
     "Get a detailed runtime diagnostic report including tool registry counts, active sessions, recent errors, and configuration status. Use when: debugging agent behavior, checking tool availability, or investigating errors. Read-only. Returns structured diagnostic data.", handle_runtime_diagnostics, permission_action="read")
_reg("runtime.retention_preview", "Retention Preview", "runtime", "low",
     "Preview which sessions/runs/artifacts are candidates for retention cleanup. Read-only preview — does NOT modify data. Returns candidate list with ages and sizes.", handle_runtime_retention_preview, permission_action="read")
_reg("runtime.archive_preview", "Archive Preview", "runtime", "low",
     "Preview current archive state including archived count and storage usage. Read-only. Returns archive statistics.", handle_runtime_archive_preview, permission_action="read")

# ── F. Report / Document Tools ──
_reg("report.render_markdown", "Render Markdown", "report", "low",
     "Render Markdown content from a safe text summary. Use when: you need to format analysis results, findings, or structured output as a proper Markdown document. Read-only. Returns formatted Markdown string. Use report.save_artifact to persist.", handle_report_render_markdown, permission_action="read")
_reg("report.save_artifact", "Save Report", "report", "medium",
     "Save a generated report as a workspace artifact for later reference or sharing. Use when: user asks to save/export a report. Medium risk (writes workspace state). Returns artifact_id. Prefer after report.render_markdown.", handle_report_save_artifact, writes_artifact=True, permission_action="write")
_reg("doc.render_from_safe_summary", "Render Document", "report", "low",
     "Render a document from a sanitized safe summary (no raw configs accepted). Use when: converting analysis into a readable document format. Read-only. Returns rendered document text.", handle_doc_render_from_safe_summary, permission_action="read")
_reg("table.render_markdown", "Render Table", "report", "low",
     "Render structured data as a Markdown table. Use when: comparing data, showing structured results, or presenting tabular findings. Not for: raw data dumps without structure. Read-only. Returns Markdown table string. Use with report.render_markdown for full documents.", handle_table_render_markdown, permission_action="read")
_reg("diagram.render_mermaid", "Render Mermaid", "report", "low",
     "Generate Mermaid diagram source text for network topology, flow charts, or architecture diagrams. Use when: user asks for topology visualization, data flow diagram, or architecture illustration. Read-only. Returns Mermaid text — NOT a rendered image. The text can be used in Markdown or dedicated viewers.", handle_diagram_render_mermaid, permission_action="read")

# ── G. Text / Data Tools ──
_reg("text.redact", "Redact Text", "text", "low",
     "Remove sensitive information from text (IP addresses, passwords, tokens, credentials). Use when: user wants to share config/log safely or before saving sensitive data. Read-only transformation. Returns redacted text with masking indicators. Always run before sharing outputs externally.", handle_text_redact, permission_action="read")
_reg("text.diff", "Text Diff", "text", "low",
     "Compute a safe text diff between two text inputs. Use when: comparing config versions, checking changes, or reviewing edits. Read-only. Returns unified diff with additions/removals highlighted. Requires text_a (original) and text_b (changed).", handle_text_diff, permission_action="read")
_reg("text.extract_keywords", "Extract Keywords", "text", "low",
     "Extract key technical terms, commands, and identifiers from text. Use when: analyzing config text, identifying key elements, or preparing search queries. Read-only. Returns ranked keyword list. Good first step before web.search or knowledge.search.", handle_text_extract_keywords, permission_action="read")
_reg("text.classify", "Classify Text", "text", "low",
     "Classify text type (network config, log, general prose, code, documentation). Use when: you need to determine what kind of content you're working with BEFORE choosing a parser strategy. Read-only. Returns classification with confidence score. Helps route to correct parser.", handle_text_classify, permission_action="read")
_reg("json.validate", "Validate JSON", "text", "low",
     "Validate JSON syntax without dangerous eval. Use when: checking if a JSON string is well-formed. Read-only. Returns valid/invalid with exact error position. Safe — no code execution.", handle_json_validate, permission_action="read")
_reg("yaml.validate", "Validate YAML", "text", "low",
     "Validate YAML syntax using safe_load only. Use when: checking YAML configs or data files. Read-only. Returns valid/invalid with error details. Safe — no arbitrary code execution.", handle_yaml_validate, permission_action="read")
_reg("csv.summarize", "CSV Summarize", "text", "low",
     "Summarize CSV data structure: columns, row count, data types, sample values. Use when: user uploads spreadsheet data or needs to understand CSV structure before deeper analysis. Read-only. Returns column headers, types, and row statistics.", handle_csv_summarize, permission_action="read")
_reg("table.extract", "Extract Table", "text", "low",
     "Extract structured table data from Markdown text. Use when: you need to parse tabular data from formatted content. Read-only. Returns extracted rows and columns as structured data. Use with table.render_markdown to reformat.", handle_table_extract, permission_action="read")

# ── H. Workspace Safe File Tools ──
_reg("workspace.file.list", "List Files", "workspace", "low",
     "List files in a workspace subdirectory (no path traversal outside workspace). Use when: user asks what files are available in the workspace. Read-only. Returns filename, size, and suffix for each file. Max 50 files.", handle_ws_list_files, permission_action="read")
_reg("workspace.file.preview", "Read Text Preview", "workspace", "low",
     "Read a size-limited preview of a workspace text file. Use when: you need a quick preview before full file.read. Read-only. Returns first N chars of text content. For full content use file.read.", handle_ws_read_text_preview, permission_action="read")
_reg("workspace.write_artifact_file", "Write File", "workspace", "medium",
     "Write content to a workspace output file. Use when: user wants to save generated content to the workspace filesystem. Medium risk (writes to disk). Only writes to workspaces/<ws>/files/. Returns filepath confirmation.", handle_ws_write_artifact_file, writes_artifact=True, permission_action="write")
_reg("workspace.file.exists", "Path Exists", "workspace", "low",
     "Check whether a workspace-relative path exists. Use when: validating paths before file operations. Read-only. Returns exists/is_file/is_dir/size. Not for: listing files (use workspace.list_files), reading content (use file.read).", handle_ws_path_exists, permission_action="read")
_reg("workspace.get_metadata", "Workspace Metadata", "workspace", "low",
     "Get workspace metadata including creation date, file count, session count, and artifact count. Use when: user asks about workspace overview. Read-only. Returns metadata dict.", handle_ws_get_metadata, permission_action="read")

# ── I. Shell / PowerShell Tools (HIGH RISK, approval gated) ──
_reg("host.shell.exec", "Shell Exec", "shell", "high",
     "Execute a bash/shell command ON THE LOCAL HOST running this Agent (Linux/macOS). Use when: user asks for local OS info, IP address, hostname, DNS, listening ports, process status, file system checks, or to run read-only diagnostics. NOT for: remote network device commands (SSH/Telnet not available). HIGH RISK — requires user approval via popup bubble (you just call it, the system handles approval). 30s timeout, 10000 chars max output. On Windows, use powershell.exec instead.", handle_command_approved_exec, requires_approval=True, permission_action="exec")
_reg("host.powershell.exec", "PowerShell Exec", "powershell", "high",
     "Execute a PowerShell command ON THE LOCAL HOST running this Agent (Windows). Use when: user asks for local Windows OS info, IP configuration, process status, or system diagnostics. NOT for: remote device access, executing scripts from internet. HIGH RISK — requires user approval via popup bubble (you just call it, the system handles approval). 15s timeout, 10000 chars max output. On Linux/macOS, use shell.exec instead.", handle_powershell_approved_script, requires_approval=True, permission_action="exec")

# ── J. Python Exec Tool (HIGH RISK, AST-sandboxed, approval gated) ──
_reg("python.exec", "Python Exec", "python", "high",
     "Execute Python code in an AST-sandboxed subprocess ON THE LOCAL HOST. Use when: user needs data processing, text analysis, or calculations that require Python. Code is checked for forbidden imports (os, subprocess, socket, etc.), forbidden builtins (eval, exec, open, etc.), and dunder access. HIGH RISK — requires user approval via popup bubble (you just call it, the system handles approval). 10s timeout. NOT for: file system operations, network connections, or code with side effects.", handle_python_exec, requires_approval=True, permission_action="exec")

# ── K. Session Snapshot / Rewind Tools ──
_reg("session.snapshot", "Session Snapshot", "session", "low",
     "Create a snapshot of the current session's messages for later recovery or rewind. Use when: user wants to checkpoint before a large operation or enable rollback. Read-only for current state (writes snapshot). Returns snapshot_id. Use with session.rewind to restore.", handle_session_snapshot, permission_action="read")
_reg("session.list_snapshots", "List Snapshots", "session", "low",
     "List all snapshots for a session WITHOUT full message content. Use when: user wants to see available recovery points. Read-only. Returns snapshot list with timestamps and reasons.", handle_session_list_snapshots, permission_action="read")
_reg("session.rewind", "Session Rewind", "session", "medium",
     "Rewind/restore a session to a previous snapshot. Use when: user wants to undo recent conversation changes or return to a known good state. Use dry_run=True to preview without applying. Use dry_run=False to actually restore. Not for: creating snapshots (use session.snapshot). Medium risk (modifies session state). WARNING: current messages after the snapshot will be replaced.", handle_session_rewind, permission_action="write")

# ── L. Agent Spawn (Sub-Agent) Tool ──
_reg("agent.spawn", "Spawn Sub-Agent", "session", "medium",
     "Spawn a sub-agent with restricted read-only tool access to research, summarize, or validate data independently. Use when: task requires parallel research or multi-step data gathering without blocking the main conversation. Returns compressed results. Max 3 turns, only low-risk tools. Sub-agents CANNOT spawn further sub-agents. Medium risk (creates child session).", handle_agent_spawn, requires_approval=False, permission_action="read")
_reg("agent.list_roles", "List Agent Roles", "session", "low",
     "List available agent roles (planner/worker/reviewer) with descriptions and default tool sets. Use when: user wants to understand agent team capabilities. Read-only. Returns role catalog.", handle_agent_list_roles, permission_action="read")
_reg("agent.get_result", "Get Sub-Agent Result", "session", "low",
     "Get the complete result of a previously spawned sub-agent by its child_session_id. Use when: user wants to see detailed output from a background research task. Read-only. Returns full sub-agent result with tool_calls and final_response.", handle_agent_get_result, permission_action="read")
_reg("agent.team", "Multi-Agent Team", "session", "medium",
     "PREVIEW: Multi-agent team with planner/worker/reviewer roles. Planner breaks tasks down, worker executes them, reviewer (optional) reviews worker output. Use when: task is complex and benefits from structured decomposition. Max 3 agents, 2 turns each. High-risk tools forbidden. Medium risk (creates multiple child sessions).", handle_agent_team, permission_action="read")

# ── Slash Command Tool ──
_reg("slash.run", "Run Slash Command", "runtime", "low",
     "Execute a built-in slash command (e.g. /help, /skills, /context, /tools). Use when: user types a /command or asks about available commands. Read-only. Returns command output. See /help for the full command list.", handle_slash_run, permission_action="read")

# ── File Tools ──
_reg("workspace.file.list", "List Files", "file", "low",
     "List files in a workspace subdirectory. Use when: user wants to see available files before reading. Read-only. Returns filename, size, suffix for up to 50 files. Use with file.read to inspect specific files.", handle_file_list, permission_action="read")
_reg("workspace.file.exists", "File Exists", "file", "low",
     "Check whether a workspace file or directory exists. Use when: validating file paths before reading or editing. Not for: listing directory contents (use file.list), path validation in different namespace (use workspace.path_exists). Read-only. Returns exists/is_file/is_dir/size.", handle_file_exists, permission_action="read")
_reg("workspace.file.read", "Read File", "file", "low",
     "Read a workspace text file safely with a 50000 char limit. Use when: user asks to inspect an uploaded file, generated artifact, config, log, or report stored in the workspace. NOT for: binary files (will be rejected), paths outside workspace. Read-only. Returns file text content. Paths are workspace-relative and protected.", handle_file_read, permission_action="read")
_reg("workspace.file.read_image", "Read Image Metadata", "file", "low",
     "Read image file metadata (dimensions, format, size) from workspace. Use when: user uploads or references an image file (.png/.jpg/.gif/.webp). DOES NOT do OCR — ask user to describe the image content. Read-only. Returns filename, dimensions, size, format. NOT for: text files (use file.read), non-image files.", handle_file_read_image, permission_action="read")
_reg("file.edit", "Edit File", "file", "medium",
     "Edit a workspace file by exact string replacement. Use when: user asks to modify a file's content. Only writes to workspaces/<ws>/files/. Medium risk (modifies files). Returns lines_changed count. Requires old_string + new_string — exact match required.", handle_file_edit, writes_artifact=True, permission_action="write")
_reg("file.patch", "Apply Patch", "file", "medium",
     "Apply a unified diff patch to a workspace file. Use when: user provides a diff/patch to apply. Medium risk (modifies files). Returns lines_added and lines_removed. Use file.read to verify result.", handle_file_patch, writes_artifact=True, permission_action="write")

# ── Memory Update / Delete Tools ──
_reg("memory.update", "Update Memory", "memory", "medium",
     "Update an existing memory entry's content. Checks for secrets before writing. Use when: user wants to modify a stored preference or fact. Medium risk (modifies persistent memory). Requires memory_id from memory.search or memory.list. Returns confirmation.", handle_memory_update, permission_action="write")
_reg("memory.delete_soft", "Soft Delete Memory", "memory", "medium",
     "Soft-delete a memory entry (marks as deleted, recoverable). Use when: user explicitly asks to remove/forget a stored memory. WARNING: Request explicit confirmation before deleting. Medium risk (modifies memory state). Returns confirmation.", handle_memory_delete_soft, permission_action="write")

# ── Session Checkpoint / Export Tools ──
_reg("session.checkpoint", "Session Checkpoint", "session", "low",
     "Create a checkpoint of the current session state with message_count, run_refs, and artifact_refs. Use when: user wants to preserve current state before a potentially risky operation. Not for: message-level snapshots for rewind (use session.snapshot). Writes checkpoint metadata. Returns checkpoint_id.", handle_session_checkpoint, permission_action="write")
_reg("session.export", "Export Session", "session", "low",
     "Export session messages as JSON dict or Markdown string. Use when: user wants to download, share, or archive a conversation. Not for: browsing session content (use session.get_summary). Read-only export. Returns formatted session data.", handle_session_export, permission_action="write")


def register_all_general_tools(registry):
    """Register all general tools into a ToolRegistry.

    v3.0: this is a thin pass-through to the canonical registry, which is
    the v3.0 truth source for tool metadata and dispatch. The older
    `ALL_GENERAL_TOOLS` list is kept for backward compatibility with
    consumers that still iterate it, but new registrations come from
    the canonical registry.
    """
    from copy import deepcopy
    from tool_runtime.canonical_registry import to_tool_specs
    for spec, handler in to_tool_specs():
        try:
            registry.register_tool(deepcopy(spec), handler)
        except ValueError:
            # Already registered (e.g. by register_builtin_tools) — skip.
            continue
    return registry
