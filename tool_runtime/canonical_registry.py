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
from tool_runtime.schemas import ToolSpec, ToolInvocation
from tool_runtime.registry_helpers import tool_keyword_score


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


def _handle_web_page_merged(inv: ToolInvocation) -> dict:
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower()
    if action == "extract_links":
        return handle_web_extract_links(inv)
    elif action == "save_artifact":
        return handle_web_save_to_artifact(inv)
    else:
        return handle_web_fetch_summary(inv)


def _handle_data_validate_merged(inv: ToolInvocation) -> dict:
    args = inv.arguments or {}
    fmt = str(args.get("format", "")).lower()
    if fmt == "yaml":
        return handle_yaml_validate(inv)
    else:
        return handle_json_validate(inv)


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
    else:
        return handle_memory_create(inv)


def _handle_text_analyze_merged(inv: ToolInvocation) -> dict:
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower()
    if action == "diff":
        return handle_text_diff(inv)
    elif action == "keywords":
        return handle_text_extract_keywords(inv)
    elif action == "classify":
        return handle_text_classify(inv)
    elif action == "extract_entities":
        return handle_text_extract_entities(inv)
    elif action == "regex":
        return handle_text_regex(inv)
    else:
        return handle_text_redact(inv)


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
            task = inspection_service.create_task(
                workspace_id=ws,
                profile_id="",
                scope=scope if isinstance(scope, dict) else {},
                created_by=str(args.get("created_by", "user") or "user"),
                session_id=str(args.get("session_id", "") or ""),
                max_concurrency=int(args.get("max_concurrency", 3) or 3),
            )
        except Exception as exc:
            return {"ok": False, "error": f"inspection_run_failed: {type(exc).__name__}: {exc}"}
        return {
            "ok": task.status != "failed" or not task.error.startswith("unknown_profile"),
            "task_id": task.task_id,
            "status": task.status,
            "profile_id": task.profile_id,
            "scope": {
                "region": task.scope.region, "location": task.scope.location,
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
            "error": task.error,
        }

    if action == "task_list":
        limit = int(args.get("limit", 50) or 50)
        items = inspection_service.list_tasks(ws, limit=limit)
        return {"ok": True, "items": items, "count": len(items)}

    if action == "task_get":
        task_id = str(args.get("task_id", "") or "")
        task = inspection_service.get_task(ws, task_id)
        if task is None:
            return {"ok": False, "error": "task_not_found"}
        from dataclasses import asdict
        return {"ok": True, "task": asdict(task)}

    if action == "task_cancel":
        task_id = str(args.get("task_id", "") or "")
        return inspection_service.cancel_task(ws, task_id)

    if action == "report":
        task_id = str(args.get("task_id", "") or "")
        fmt = str(args.get("format", "md") or "md").lower()
        return inspection_service.render_report(ws, task_id, fmt)

    return {"ok": False, "error": f"unknown_action: {action}"}


def _handle_browser_merged(inv: ToolInvocation) -> dict:
    action, _ = _action(inv)
    return {
        "navigate": _handler_browser_navigate,
        "extract": _handler_browser_extract,
        "screenshot": _handler_browser_screenshot,
        "click": _handler_browser_click,
    }.get(action, _handler_browser_navigate)(inv)


def _handle_web_merged(inv: ToolInvocation) -> dict:
    """web.manage — action=search|weather|page."""
    action, _ = _action(inv)
    if action == "weather":
        return _weather_merged(inv)
    if action == "page":
        return _handle_web_page_merged(inv)
    # default: search (respects source=general|docs|news)
    return _handle_web_search_merged(inv)


def _handle_data_merged(inv: ToolInvocation) -> dict:
    """data.manage — action=csv_summarize|table_extract|table_render|validate|filter|deduplicate."""
    action, _ = _action(inv)
    return {
        "csv_summarize": handle_csv_summarize,
        "table_extract": handle_table_extract,
        "table_render": handle_table_render_markdown,
        "validate": _handle_data_validate_merged,
        "filter": handle_data_filter,
        "deduplicate": handle_data_deduplicate,
    }.get(action, handle_csv_summarize)(inv)


def _handle_report_merged(inv: ToolInvocation) -> dict:
    """report.manage — action=markdown_render|artifact_save|safe_summary_render|mermaid_render|html_render|diff_report."""
    action, _ = _action(inv)
    return {
        "markdown_render": handle_report_render_markdown,
        "artifact_save": handle_report_save_artifact,
        "safe_summary_render": handle_doc_render_from_safe_summary,
        "mermaid_render": handle_diagram_render_mermaid,
        "html_render": handle_report_render_html,
        "diff_report": handle_report_diff,
    }.get(action, handle_report_render_markdown)(inv)


def _handle_knowledge_merged(inv: ToolInvocation) -> dict:
    """knowledge.manage — action=search|read|source_list|chunk_list|source_manage|source_reindex|import|not_found_explain."""
    action, _ = _action(inv)
    return {
        "search": handle_knowledge_search,
        "read": _handle_knowledge_read_merged,
        "source_list": _k_source_list,
        "chunk_list": _k_chunk_list,
        "source_manage": _k_source_manage,
        "source_reindex": _handle_knowledge_reindex_merged,
        "import": _handle_knowledge_import_merged,
        "not_found_explain": handle_knowledge_explain_not_found,
    }.get(action, handle_knowledge_search)(inv)


def _handle_memory_merged(inv: ToolInvocation) -> dict:
    """memory.manage — action=search|create|update|confirm|delete|profile_get|profile_set."""
    action, _ = _action(inv)
    return {
        "search": handle_memory_search_merged,
        "create": _handle_memory_manage_merged,  # create is the manage-merged default
        "update": _handle_memory_manage_merged,
        "confirm": _handle_memory_manage_merged,
        "delete": _handle_memory_manage_merged,
        "profile_get": handle_memory_profile_merged,
        "profile_set": handle_memory_profile_merged,
    }.get(action, _handle_memory_manage_merged)(inv)


def _handle_skill_merged(inv: ToolInvocation) -> dict:
    """skill.manage — action=list|find|load|inspect."""
    action, _ = _action(inv)
    return {
        "list": handle_skill_list,
        "find": handle_skill_find,
        "load": handle_skill_load,
        "inspect": handle_skill_inspect,
    }.get(action, handle_skill_list)(inv)


def _handle_agent_merged(inv: ToolInvocation) -> dict:
    """agent.manage — action=role_list|spawn|team_run|result_get."""
    action, _ = _action(inv)
    return {
        "role_list": handle_agent_list_roles,
        "spawn": handle_agent_spawn,
        "team_run": handle_agent_team,
        "result_get": handle_agent_get_result,
    }.get(action, handle_agent_list_roles)(inv)


def _handle_system_merged(inv: ToolInvocation) -> dict:
    """system.manage — 13 actions for diagnostics/run/session/review."""
    action, _ = _action(inv)
    return {
        "diagnostics": handle_runtime_diagnostics,
        "health": handle_runtime_health,
        "selfcheck": handle_runtime_selfcheck,
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


# ─── v3.9.1: workspace.file merged handler ─────────────────────────────
# 合并 6 个原 tool: list / read / read_image / edit / patch / write_artifact
# dispatch 字段: action (list|read|read_image|edit|patch|write_artifact)
# 保留原 tool_id 作为 alias (callable_by_llm=False) 以兼容 router / baseline
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
    elif action == "delete_file":
        return handle_file_delete(inv)
    else:
        return {
            "ok": False,
            "error": f"workspace.file: unknown action={action!r}. "
                     f"Valid actions: list, read, read_image, edit, patch, write_artifact, glob, delete_file",
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
    elif action == "diff":
        return handle_text_diff(inv)
    elif action == "export":
        return handle_report_save_artifact(inv)
    else:
        return {
            "ok": False,
            "error": f"workspace.artifact: unknown action={action!r}. "
                     f"Valid actions: list, read, save, tag, delete, diff, export",
        }


def _handle_workspace_filestore_merged(inv: ToolInvocation) -> dict:
    """Route workspace.filestore(action=X) to the right FileStore handler.

    Supports FileStore references and workspace-path imports.
    """
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower().strip()

    if action == "references":
        from tool_runtime.general_tools.filestore_tools import handle_file_references

        file_id = str(args.get("file_id") or args.get("filepath") or "").strip()
        return handle_file_references(inv, file_id=file_id)
    elif action == "import":
        from tool_runtime.general_tools.filestore_tools import handle_file_import_workspace_path

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


def _handle_knowledge_reindex_merged(inv: ToolInvocation) -> dict:
    """Route knowledge.manage(action=source_reindex, source_id=ALL) to reindex_all handler."""
    args = inv.arguments or {}
    sid = str(args.get("source_id", "")).upper()
    if sid == "ALL":
        return handle_knowledge_reindex_all(inv)
    else:
        return handle_knowledge_source_reindex(inv)


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

from tool_runtime.general_tools.file_tools import (
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
from tool_runtime.general_tools.memory_tools import (
    handle_memory_search,
    handle_memory_search_merged,
    handle_memory_create,
    handle_memory_list,
    handle_memory_confirm,
    handle_memory_get_profile,
    handle_memory_set_profile,
    handle_memory_profile_merged,
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
import logging



logger = logging.getLogger(__name__)

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

def _handler_browser_navigate(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_navigate
    args = inv.arguments or {}
    return browser_navigate(str(args.get("url", "")), str(args.get("wait_selector", "")))

def _handler_browser_extract(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_extract
    args = inv.arguments or {}
    return browser_extract(str(args.get("url", "")), str(args.get("selector", "body")))

def _handler_browser_screenshot(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_screenshot
    args = inv.arguments or {}
    return browser_screenshot(str(args.get("url", "")), bool(args.get("full_page", False)))

def _handler_browser_click(inv: ToolInvocation) -> dict:
    from agent.modules.browser.core import browser_click
    args = inv.arguments or {}
    return browser_click(str(args.get("selector", "")))


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

# Dangerous command patterns — block destructive operations
_DANGEROUS_COMMAND_PATTERNS = [
    r"(?i)\breload\b", r"(?i)\breboot\b", r"(?i)\breset\b",
    r"(?i)\bformat\b", r"(?i)\bdelete\s+flash", r"(?i)\berase\s+startup",
    r"(?i)\bwrite\s+erase\b", r"(?i)\brm\s+-rf\b",
    r"(?i)\bdd\s+if=", r"(?i)\bmkfs\b",
]

# Config command patterns — require approval
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
    """Check if a command is dangerous. Returns (is_dangerous, reason)."""
    import re
    for pattern in _DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, command):
            return True, f"dangerous command blocked (policy violation)"
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
                    "output": output_text[:8000], "session_id": session_id,
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
            "output": output_text[:8000], "session_id": new_sid,
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
                    "output": _extract_output(exec_result)[:8000],
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


# ─── v3.9.7: New action handlers (P0-P2 gap fill) ─────────────────────

def handle_runtime_tasks(inv: ToolInvocation) -> dict:
    """List pending/running background tasks (v3.9.7)."""
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
    """Query audit log entries (v3.9.7)."""
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
    """Extract network entities: IP, MAC, VLAN, subnet, hostname (v3.9.7)."""
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


def handle_text_regex(inv: ToolInvocation) -> dict:
    """Apply a regex pattern to text and return matches (v3.9.7)."""
    import re
    args = inv.arguments or {}
    text = str(args.get("text", ""))
    pattern = str(args.get("pattern", ""))
    if not pattern:
        return {"ok": False, "error": "pattern is required"}
    try:
        matches = re.findall(pattern, text[:50000])
        return {"ok": True, "matches": [str(m) for m in matches[:100]], "count": len(matches)}
    except re.error as e:
        return {"ok": False, "error": f"Invalid regex: {e}"}


def handle_background_exec(inv: ToolInvocation) -> dict:
    """Launch a background command and return a job_id for polling (v3.9.7)."""
    import subprocess, uuid
    args = inv.arguments or {}
    command = str(args.get("command", ""))
    if not command:
        return {"ok": False, "error": "command is required"}
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
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def handle_stream_exec(inv: ToolInvocation) -> dict:
    """Execute command with streaming output (PTY-like, v3.9.7)."""
    import subprocess
    args = inv.arguments or {}
    command = str(args.get("command", ""))
    if not command:
        return {"ok": False, "error": "command is required"}
    timeout = args.get("timeout", 30)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:5000],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def handle_file_glob(inv: ToolInvocation) -> dict:
    """Glob file pattern matching (v3.9.7)."""
    import glob as g, os
    args = inv.arguments or {}
    subdir = str(args.get("subdir", "."))
    pattern = str(args.get("pattern", "*"))
    try:
        from tool_runtime.general_tools.shared import _workspace_path
        ws_id = _inv_workspace(inv)
        base = str(_workspace_path(ws_id, subdir))
        full_pattern = os.path.join(base, pattern)
        matches = sorted(g.glob(full_pattern, recursive=True))[:200]
        rel = [os.path.relpath(m, base) for m in matches]
        return {"ok": True, "files": rel, "count": len(rel), "directory": subdir}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def handle_file_delete(inv: ToolInvocation) -> dict:
    """Soft-delete a file (move to .trash) (v3.9.7)."""
    import shutil
    from pathlib import Path
    args = inv.arguments or {}
    filepath = str(args.get("filepath", ""))
    if not filepath:
        return {"ok": False, "error": "filepath is required"}
    try:
        from tool_runtime.general_tools.shared import _workspace_path
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


def handle_data_filter(inv: ToolInvocation) -> dict:
    """Filter rows by column conditions (v3.9.7)."""
    import json
    args = inv.arguments or {}
    rows = args.get("rows", [])
    conditions = args.get("conditions", {})
    if not rows:
        return {"ok": False, "error": "rows array is required"}
    try:
        cond = conditions if isinstance(conditions, dict) else json.loads(str(conditions))
    except Exception:
        return {"ok": False, "error": "conditions must be a JSON object"}
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        match = all(str(row.get(k, "")) == str(v) for k, v in cond.items())
        if match:
            result.append(row)
    return {"ok": True, "rows": result[:100], "filtered": len(rows) - len(result), "total": len(rows)}


def handle_data_deduplicate(inv: ToolInvocation) -> dict:
    """Deduplicate rows by a key column (v3.9.7)."""
    args = inv.arguments or {}
    rows = args.get("rows", [])
    key = str(args.get("key", ""))
    if not rows:
        return {"ok": False, "error": "rows array is required"}
    seen = set()
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        k = str(row.get(key, "")) if key else str(row)
        if k not in seen:
            seen.add(k)
            result.append(row)
    return {"ok": True, "rows": result[:100], "removed": len(rows) - len(result), "total": len(rows)}


def handle_report_render_html(inv: ToolInvocation) -> dict:
    """Render content as basic HTML (v3.9.7)."""
    import html
    args = inv.arguments or {}
    content = str(args.get("content", ""))[:20000]
    title = str(args.get("title", "Report"))
    body = html.escape(content).replace("\n", "<br>\n")
    page = (
        "<html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title></head><body>{body}</body></html>"
    )
    return {"ok": True, "html": page[:25000], "title": title}


def handle_report_diff(inv: ToolInvocation) -> dict:
    """Diff two artifacts (v3.9.7)."""
    args = inv.arguments or {}
    aid_a = str(args.get("artifact_id_a", ""))
    aid_b = str(args.get("artifact_id_b", ""))
    try:
        ws_id = _inv_workspace(inv)
        from tool_runtime.general_tools.file_tools import handle_artifact_read_content_safe
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
    """Update an existing CMDB asset (v3.9.7)."""
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
    """Export CMDB assets list (v3.9.7)."""
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
    return {"ok": result.get("ok", False),
            "summary": result.get("summary") or "",
            "output": result.get("output", {}) if isinstance(result, dict) else {},
            "errors": list(result.get("errors", []))[:5] if isinstance(result, dict) else [],
            "warnings": list(result.get("warnings", []))[:5] if isinstance(result, dict) else []}

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
        result = _handler_artifact_list(inv)
    if isinstance(result, dict):
        return result
    return {"ok": False, "error": "unexpected result type"}


# canonical_tool_id -> CanonicalToolEntry
_RAW_REGISTRY: list[CanonicalToolEntry] = [
    # ── 21-tool Codex-style registry (all visible to LLM) ──
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
            "target": {"type": "string", "enum": ["local", "ssh", "telnet"],
                       "default": "local",
                       "description": "[shell] Execution target."},
            "shell": {"type": "string",
                      "description": "[shell] Shell type: cmd or powershell.", "default": "cmd"},
            "command": {"type": "string", "description": "[shell] Shell command to execute."},
            "code": {"type": "string", "description": "[python] Python code (AST-sandboxed)."},
            "host": {"type": "string"}, "port": {"type": "integer"},
            "asset_id": {"type": "string", "description": "[ssh|telnet] Resolve host/user/password from CMDB asset without exposing credentials."},
            "username": {"type": "string"}, "password": {"type": "string"},
            "vendor": {"type": "string"},
            "session_id": {"type": "string", "description": "[ssh] Reuse existing SSH session."},
            "close_session": {"type": "boolean", "description": "[ssh] Close session after execution."},
            "working_dir": {"type": "string"},
            "env_vars": {"type": "object"},
            "timeout": {"type": "integer"},
            "command_name": {"type": "string", "description": "[slash] Slash command name."},
            "args": {"type": "string", "description": "[slash] Slash command args."},
        }),
        risk_level="high", permission_action="exec",
        description=(
            "Unified exec tool. action=shell (default; target=local|ssh|telnet, "
            "shell=cmd|powershell), action=python (AST-sandboxed), action=slash (registered slash command), "
            "action=background (async, returns job_id), action=stream (PTY streaming). "
            "All require approval. NEVER use for destructive commands (reload/erase/format/rm -rf). "
            "Do NOT store or expose credentials in output."
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
            "search": {"type": "string", "description": "[list] Fuzzy search name/vendor/host/model/region/location."},
            "filter": {"type": "string", "description": '[list] JSON filter, e.g. {"type":"switch","region":"华东"}.'},
            "sort_by": {"type": "string", "description": "[list] Sort field: name/type/vendor/region/location/host/updated_at."},
            "asset_id": {"type": "string", "description": "[get|delete|update] Asset ID."},
            "name": {"type": "string"}, "host": {"type": "string"},
            "type": {"type": "string", "enum": ["switch", "router", "firewall", "server", "other"],
                     "default": "switch"},
            "vendor": {"type": "string"},
            "model": {"type": "string"},
            "region": {"type": "string", "description": "[list|add|update] Logical area/region, e.g. 华东, 华南, 核心, 接入."},
            "location": {"type": "string", "description": "[list|add|update] Physical site/rack/room location."},
            "protocol": {"type": "string", "enum": ["ssh", "telnet"], "default": "ssh"},
            "port": {"type": "integer", "default": 22},
            "username": {"type": "string"},
            "password": {"type": "string", "description": "[add] Optional saved credential; never returned by get/list/export."},
            "description": {"type": "string"},
            "format": {"type": "string", "enum": ["json", "csv"], "default": "json",
                       "description": "[export] Output format."},
        }, ["action"]),
        risk_level="medium", requires_approval=False,  # add/delete require approval at runtime
        description=(
            "Unified CMDB device tool. action=list, get (reads); "
            "action=add, delete, update (writes, require approval); action=export (read). "
            "Do not fabricate assets; do not expose credentials."
        ),
    ),

    # 4. browser.manage — navigate / extract / screenshot / click
    CanonicalToolEntry(
        canonical_tool_id="browser.manage",
        handler=_adapt(_handle_browser_merged),
        input_schema=_schema({
            "action": {"type": "string", "enum": ["navigate", "extract", "screenshot", "click"]},
            "url": {"type": "string", "description": "[navigate|extract|screenshot] URL."},
            "wait_selector": {"type": "string", "default": "", "description": "[navigate] Wait for CSS selector."},
            "selector": {"type": "string", "default": "body",
                         "description": "[extract] CSS selector; [click] selector of element."},
            "full_page": {"type": "boolean", "default": False, "description": "[screenshot] Capture full page."},
        }, ["action"]),
        description=(
            "Unified Playwright browser tool. action=navigate, extract, screenshot (reads); "
            "action=click (write). Do not access private/login-walled URLs without permission."
        ),
    ),

    # 5. web.manage — search / weather / page
    CanonicalToolEntry(
        canonical_tool_id="web.manage",
        handler=_adapt(_handle_web_merged),
        input_schema=_schema({
            "action": {"type": "string", "enum": ["search", "weather", "page"]},
            "query": {"type": "string", "description": "[search] Search query."},
            "source": {"type": "string", "enum": ["general", "docs", "news"],
                       "default": "general",
                       "description": "[search] Search source: general web, vendor docs, or news."},
            "limit": _S["limit"],
            "recency": _S["recency"],
            "language": _S["language"],
            "location": _S["location"],
            "days": {"type": "integer", "default": 1,
                     "description": "[weather] 1=current, 2-10=forecast."},
            "units": _S["units"],
            "url": _S["url"],
            "workspace_id": _S["workspace_id"],
            "title": _S["title"],
        }, ["action"]),
        description=(
            "Unified web tool. action=search (source=general|docs|news), action=weather (forecast), "
            "action=page (summarize/extract_links/save_artifact)."
        ),
    ),

    # 6. data.manage — csv / table / validate
    CanonicalToolEntry(
        canonical_tool_id="data.manage",
        handler=_adapt(_handle_data_merged),
        input_schema=_schema({
            "action": {"type": "string", "enum": ["csv_summarize", "table_extract", "table_render", "validate", "filter", "deduplicate"]},
            "text": _S["text"],
            "rows": {"type": "array"}, "headers": {"type": "array"},
            "format": {"type": "string", "enum": ["json", "yaml"], "default": "json",
                       "description": "[validate] Data format."},
            "conditions": {"type": "object", "description": "[filter] Filter criteria, e.g. {\"column\":\"value\"}."},
            "key": {"type": "string", "description": "[deduplicate] Column name to deduplicate by."},
        }, ["action"]),
        description=(
            "Unified data tool. action=csv_summarize, table_extract, table_render, validate, filter, deduplicate. "
            "Do not execute embedded code in user-supplied data."
        ),
    ),

    # 7. report.manage — markdown / safe_summary / mermaid / artifact.save
    CanonicalToolEntry(
        canonical_tool_id="report.manage",
        handler=_adapt(_handle_report_merged),
        input_schema=_schema({
            "action": {"type": "string", "enum": ["markdown_render", "artifact_save", "safe_summary_render", "mermaid_render", "html_render", "diff_report"]},
            "content": _S["content"],
            "title": _S["title"],
            "summary": {"type": "string", "description": "[safe_summary_render] Redacted summary."},
            "mermaid": {"type": "string", "description": "[mermaid_render] Mermaid source."},
            "workspace_id": _S["workspace_id"],
            "artifact_id_a": {"type": "string", "description": "[diff_report] First artifact ID to compare."},
            "artifact_id_b": {"type": "string", "description": "[diff_report] Second artifact ID to compare."},
        }, ["action"]),
        description=(
            "Unified report tool. action=markdown_render, safe_summary_render, mermaid_render, "
            "html_render (reads); action=artifact_save (write); action=diff_report (compare)."
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
        description="Unified config analysis: parse, translate, extract, diff, summarize.",
    ),

    # 9. pcap.manage — unified packet capture analysis
    CanonicalToolEntry(
        canonical_tool_id="pcap.manage",
        handler=_adapt(_handler_pcap_analysis_run),
        input_schema=_schema({
            "action": {"type": "string", "enum": ["parse", "session", "filter", "align"]},
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
            "session_id": _S["session_id"],
            "src": {"type": "string"}, "sport": {"type": "integer"},
            "dst": {"type": "string"}, "dport": {"type": "integer"},
        }, ["action"]),
        description="Unified PCAP analysis: parse, session, filter, align.",
    ),

    # 10. knowledge.manage — 8 KB tools merged
    CanonicalToolEntry(
        canonical_tool_id="knowledge.manage",
        handler=_adapt(_handle_knowledge_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string",
                       "enum": ["search", "read", "source_list", "chunk_list",
                                "source_manage", "source_reindex", "import", "not_found_explain"]},
            "query": _S["query"],
            "limit": _S["limit"],
            "level": {"type": "string", "enum": ["chunk", "source", "parent"], "default": "chunk"},
            "chunk_id": _S["chunk_id"],
            "source_id": _S["source_id"],
            "action_source": {"type": "string",
                              "description": "[source_manage] disable|delete|reindex.",
                              "enum": ["disable", "delete", "reindex"]},
            "filepath": _S["filepath"],
            "artifact_id": _S["artifact_id"],
            "title": {"type": "string", "description": "[import] Document title."},
        }, ["action"]),
        description=(
            "Unified knowledge tool. action=search, read, source_list, chunk_list, not_found_explain (reads); "
            "action=source_manage, source_reindex, import (writes). Do not return unredacted full text."
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
                                "profile_get", "profile_set"]},
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
            "summary": {"type": "string"},
            "metadata": {"type": "object"},
            "field": {"type": "string", "description": "[profile_set] Profile field name."},
            "value": {"type": "string", "description": "[profile_set] Field value."},
            "merge": {"type": "boolean", "default": True, "description": "[profile_set] Merge with existing."},
        }, ["action"]),
        risk_level="medium",
        description=(
            "Unified memory tool. action=search, profile_get (reads); "
            "action=create, update, confirm, delete, profile_set (writes). Do not store secrets."
        ),
    ),

    # 12. skill.manage — list / find / load / inspect
    CanonicalToolEntry(
        canonical_tool_id="skill.manage",
        handler=_adapt(_handle_skill_merged),
        input_schema=_schema({
            "action": {"type": "string", "enum": ["list", "find", "load", "inspect"],
                       "default": "list",
                       "description": "list (default) | find | load | inspect."},
            "query": _S["query"],
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 20},
            "skill_name": _S["skill_name"],
        }),
        description=(
            "Unified skill tool. action=list, find, load, inspect. "
            "Read-only discovery; loading does not execute the business task."
        ),
    ),

    # 13. agent.manage — role_list / spawn / team_run / result_get
    CanonicalToolEntry(
        canonical_tool_id="agent.manage",
        handler=_adapt(_handle_agent_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["role_list", "spawn", "team_run", "result_get"]},
            "session_id": _S["session_id"],
            "instruction": {"type": "string",
                            "description": "[spawn|team_run] Task instruction."},
            "allowed_tools": {"type": "array", "items": {"type": "string"},
                              "description": "[spawn] Sub-agent allowed tools."},
            "max_turns": {"type": "integer", "default": 1, "minimum": 1, "maximum": 3,
                          "description": "[spawn] Sub-agent max turns."},
            "roles": {"type": "array", "items": {"type": "string", "enum": ["planner", "worker", "reviewer"]},
                      "description": "[team_run] Roles."},
            "parallel": {"type": "boolean", "description": "[team_run] Run up to 3 workers in parallel."},
            "child_session_id": _S["session_id"],
        }, ["action"]),
        risk_level="medium",
        description=(
            "Unified agent tool. action=role_list, result_get (reads); "
            "action=spawn, team_run (execute). max_turns enforced; "
            "do not return unredacted child payloads."
        ),
    ),

    # 14. system.manage — 9 system tools merged
    CanonicalToolEntry(
        canonical_tool_id="system.manage",
        handler=_adapt(_handle_system_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string",
                       "enum": ["diagnostics", "health", "selfcheck", "tasks", "audit_log",
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
            "Unified system introspection. action=diagnostics, health, selfcheck, tasks, "
            "audit_log, run_get, session_get, session_snapshot (reads); "
            "action=review_update, session_checkpoint, session_export (writes); "
            "action=session_rewind (destructive, requires approval)."
        ),
    ),

    # 15. text.analyze
    CanonicalToolEntry(
        canonical_tool_id="text.analyze",
        handler=_adapt(_handle_text_analyze_merged),
        input_schema=_schema({
            "text": _S["text"],
            "action": {"type": "string", "enum": ["redact", "diff", "keywords", "classify", "extract_entities", "regex"],
                       "default": "redact"},
            "text_b": {"type": "string", "description": "Second text for diff."},
            "pattern": {"type": "string", "description": "[regex] Regular expression pattern."},
            "limit": _S["limit"],
        }, ["text"]),
        description=(
            "Analyze text. action=redact, diff, keywords, classify, extract_entities (IP/MAC/VLAN), "
            "regex (pattern match)."
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
                                                  "glob", "delete_file"]},
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
            "action=edit, patch, write_artifact (writes); action=delete_file (delete)."
        ),
    ),

    # 18. workspace.artifact
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["list", "read", "save", "tag",
                                                  "delete", "diff", "export"]},
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
            "artifact_a": {"type": "string", "description": "[diff] First artifact id."},
            "artifact_b": {"type": "string", "description": "[diff] Second artifact id."},
            "destination": {"type": "string", "description": "[export] Destination path."},
        }, ["action"]),
        permission_action="",
        description=(
            "Unified workspace artifact tool. action=list, read, diff, export (reads); "
            "action=save, tag, delete (writes, delete requires approval)."
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
    ),

    # 21. workspace.document.pdf.extract_text
    CanonicalToolEntry(
        canonical_tool_id="workspace.document.pdf.extract_text",
        handler=_adapt(handle_pdf_extract_text),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "page_range": _S["page_range"],
        }, ["filepath"]),
    ),

    # 22. inspection.manage (CMDB-driven device health inspection)
    CanonicalToolEntry(
        canonical_tool_id="inspection.manage",
        handler=_adapt(_handle_inspection_managed),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {
                "type": "string",
                "enum": ["run", "task_list", "task_get", "task_cancel", "report"],
            },
            "scope": {
                "type": "object",
                "description": (
                    "[run] CMDB scope filter. Properties: region (string), "
                    "location (string), type (switch|router|firewall|server|"
                    "load_balancer|wireless|other), vendor (string), "
                    "tags (string[]), asset_ids (string[]), "
                    "limit (int 1-500, default 50). All fields are "
                    "optional; pass an empty object to inspect every "
                    "device in the workspace."
                ),
            },
            "created_by": {"type": "string", "description": "[run] user|job|system."},
            "session_id": {"type": "string", "description": "[run] Session id."},
            "max_concurrency": {"type": "integer", "description": "[run] Per-task device concurrency (default 3)."},
            "task_id": {"type": "string",
                "description": "[task_get|task_cancel|report] Task id from action=run."},
            "limit": {"type": "integer", "description": "[task_list] Max items (default 50)."},
            "format": {"type": "string", "enum": ["md", "json", "html"], "description": "[report] Report format."},
        }, ["action"]),
        description=(
            "CMDB-driven device health inspection. action=run / task_list / "
            "task_get / task_cancel / report. The backend chooses scripts "
            "from each CMDB asset's vendor and type -- callers do not need "
            "to choose a template. Pass profile_id='auto' (or omit it) "
            "and the runner picks the right profile per device; the five "
            "fixed profiles basic_health / interface_health / routing_health "
            "/ config_backup / full_basic are also accepted for explicit "
            "override. Commands come from a fixed per-vendor map -- the LLM "
            "never assembles them. "
            "Credentials are resolved server-side via exec.run(asset_id=...)."
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
            from tool_runtime.tool_namespace import get_namespace_entry
            ns_entry = get_namespace_entry(entry.canonical_tool_id)
        except Exception:
            # Unknown id: skip — no governance needed; it just isn't visible.
            logger.debug("to_tool_specs: <continue>", exc_info=True)
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
            from tool_runtime.manifest_registry import get_manifest
            manifest = get_manifest(entry.canonical_tool_id)
        except Exception:
            logger.debug("to_tool_specs: <fallback-assign>", exc_info=True)
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
