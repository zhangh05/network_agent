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


# ── FileStore tool helpers ──

def _make_filestore_handler(tool_id: str, param_names: list[str]):
    """Create a handler that extracts named params from inv.arguments."""
    def handler(inv: ToolInvocation):
        args = (inv.arguments or {})
        kwargs = {n: args.get(n, "") for n in param_names}
        from tool_runtime.general_tools.filestore_tools import (
            handle_file_get, handle_file_preview, handle_file_references,
            handle_file_write_agent_output, handle_file_import_workspace_path,
        )
        handlers = {
            "workspace.file.read": handle_file_get,
            "workspace.file.preview": handle_file_preview,
            "file.references": handle_file_references,
            "workspace.file.write_artifact": handle_file_write_agent_output,
            "file.import_workspace_path": handle_file_import_workspace_path,
        }
        return handlers[tool_id](inv, **kwargs)
    return handler


def _adapt(handler: Callable[[ToolInvocation], dict]) -> Callable[..., Any]:
    """Adapter: existing handlers take (inv: ToolInvocation)."""
    def _callable(*args: Any, **kwargs: Any) -> Any:
        if args and isinstance(args[0], ToolInvocation):
            return handler(args[0])
        inv = ToolInvocation(arguments=dict(kwargs), tool_id="")
        return handler(inv)
    return _callable


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
    else:
        return {
            "ok": False,
            "error": f"workspace.file: unknown action={action!r}. "
                     f"Valid actions: list, read, read_image, edit, patch, write_artifact",
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

    Merges file.references + file.import_workspace_path.
    """
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower().strip()

    if action == "references":
        # file.references takes file_id, but we accept both file_id and filepath
        new_inv = inv
        if "file_id" in args and "filepath" not in args:
            new_inv = ToolInvocation(
                tool_id=inv.tool_id,
                arguments={**args, "filepath": args.get("file_id", "")},
                workspace_id=inv.workspace_id,
                session_id=inv.session_id,
                run_id=inv.run_id,
                task_id=inv.task_id,
                job_id=inv.job_id,
                dry_run=inv.dry_run,
                requested_by=inv.requested_by,
                approval_id=inv.approval_id,
            )
        return _make_filestore_handler("file.references", ["filepath"])(new_inv)
    elif action == "import":
        return _make_filestore_handler("file.import_workspace_path", ["filepath"])(inv)
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
    """Route memory.profile(action=get|set) to the right handler."""
    args = inv.arguments or {}
    action = str(args.get("action", "")).lower()
    if action == "set":
        return handle_memory_set_profile(inv)
    else:
        return handle_memory_get_profile(inv)


def _handle_memory_search_merged(inv: ToolInvocation) -> dict:
    """Route memory.search(list=true|false) to search or list handler."""
    args = inv.arguments or {}
    if args.get("list"):
        return handle_memory_list(inv)
    else:
        return handle_memory_search(inv)


def _handle_knowledge_reindex_merged(inv: ToolInvocation) -> dict:
    """Route knowledge.source.reindex(source_id=ALL) to reindex_all handler."""
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
    from agent.modules.cmdb.tools import tool_list_assets
    args = inv.arguments or {}
    workspace_id = _inv_workspace(inv)
    return tool_list_assets(
        workspace_id=workspace_id,
        filter=str(args.get("filter", "")),
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
    host = str(args.get("host", "")).strip()
    port = _safe_int(args.get("port"), 22)
    username = str(args.get("username", "")).strip()
    password = str(args.get("password", "")).strip()
    command = str(args.get("command", "")).strip()
    vendor = str(args.get("vendor", "generic")).strip()
    session_id = str(args.get("session_id", "")).strip()
    close_session = bool(args.get("close_session", False))
    sudo = bool(args.get("sudo", False))

    # Close session request
    if session_id and (close_session or not command):
        try:
            disconnect(session_id)
        except Exception:
            pass
        return {"ok": True, "session_closed": True, "session_id": session_id}

    # Reuse existing session
    if session_id:
        try:
            existing = get_session(session_id)
            if existing and getattr(existing, "connected", False):
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
                    pass
        except Exception:
            pass

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
        session = ssh_connect(new_sid, host, port, username, password, vendor)
        exec_result = exec_command(new_sid, command)
        if isinstance(exec_result, dict) and not exec_result.get("ok"):
            # Command failed — clean up session
            try:
                disconnect(new_sid)
            except Exception:
                pass
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
                pass
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
    host = str(args.get("host", "")).strip()
    port = _safe_int(args.get("port"), 23)
    username = str(args.get("username", "")).strip()
    password = str(args.get("password", "")).strip()
    command = str(args.get("command", "")).strip()
    vendor = str(args.get("vendor", "generic")).strip()
    session_id = str(args.get("session_id", "")).strip()
    close_session = bool(args.get("close_session", False))

    # Close session
    if session_id and (close_session or not command):
        try:
            disconnect(session_id)
        except Exception:
            pass
        return {"ok": True, "session_closed": True, "session_id": session_id}

    # Reuse existing session
    if session_id:
        try:
            existing = get_session(session_id)
            if existing and getattr(existing, "connected", False):
                exec_result = exec_command(session_id, command)
                return {
                    "ok": True, "host": host, "command": command,
                    "output": _extract_output(exec_result)[:8000],
                    "session_id": session_id,
                }
        except Exception:
            pass

    if not host:
        return {"ok": False, "error": "host is required"}
    if not command:
        return {"ok": False, "error": "command is required"}

    is_dangerous, reason = _is_dangerous_command(command)
    if is_dangerous:
        return {"ok": False, "error": reason}

    try:
        new_sid = session_id or f"telnet_{int(__import__('time').time())}_{host.replace('.', '_')}"
        telnet_connect(new_sid, host, port, username, password, vendor)
        exec_result = exec_command(new_sid, command)
        return {
            "ok": True, "host": host, "command": command,
            "output": _extract_output(exec_result)[:8000],
            "session_id": new_sid,
        }
    except Exception as e:
        return {"ok": False, "error": f"Telnet failed: {e}"}


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
    import time
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    started = time.perf_counter()
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
        try:
            from tool_runtime.manifest_registry import get_manifest
            manifest = get_manifest(tool_id)
        except Exception:
            manifest = None
        haystack = " ".join(str(part or "") for part in (
            tool_id, ns.category, ns.group, ns.action, ns.display_name,
            ns.short_label, ns.usage_hint, ns.not_for, entry.description,
        )).lower()
        score = _catalog_score(tool_id, ns.category, ns.group, haystack, tokens, search_text)
        if score <= 0:
            continue
        scored.append((score, tool_id, {
            "tool_id": tool_id,
            "display_name": ns.display_name,
            "category": ns.category,
            "group": ns.group,
            "action": ns.action,
            "risk_level": manifest.risk_level if manifest else entry.risk_level,
            "requires_approval": manifest.requires_approval if manifest else entry.requires_approval,
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
        "catalog_size": len(TOOL_NAMESPACE),
        "query_token_count": len(tokens),
        "ranking_version": "catalog_rank.v2",
        "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "truncated": len(scored) > len(matches),
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
        "设备": ["cmdb", "asset"], "资产": ["cmdb", "asset"], "cmdb": ["cmdb"],
        # SSH / Telnet
        "ssh": ["ssh", "network"], "telnet": ["telnet", "network"],
        "远程": ["network", "ssh"], "连接": ["network"],
        "登录设备": ["ssh", "network"],
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
        (("json",), "data.validate", 34),
        (("yaml",), "data.validate", 34),
        (("csv",), "data.csv.summarize", 34),
        (("report", "报告"), "report.", 26),
        (("cmdb", "设备", "资产", "资产管理"), "cmdb.", 40),
        # Network device SSH / Telnet
        (("ssh", "network"), "exec.run", 42),
        (("telnet",), "exec.run", 42),
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
        return {"ok": False, "tool_id": "system.review.item.list", "status": "failed",
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
        return {"ok": False, "tool_id": "system.review.item.update", "status": "failed",
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
            pass
    return {
        "ok": ok, "tool_id": r.get("tool_id", ""),
        "status": "succeeded" if ok else "failed",
        "summary": str(r.get("summary", "")),
        "errors": r.get("errors", []), "content": content,
    }


def _ws_artifact_list_merged(inv: ToolInvocation) -> dict:
    """Merged handler for workspace.artifact.list — dispatches to list or search."""
    if inv.arguments.get("query", "").strip():
        result = handle_artifact_search(inv)
    else:
        result = _handler_artifact_list(inv)
    if isinstance(result, dict):
        return result
    return {"ok": False, "error": "unexpected result type"}


# canonical_tool_id -> CanonicalToolEntry
_RAW_REGISTRY: list[CanonicalToolEntry] = [
    # Exec — unified command execution
    CanonicalToolEntry(
        canonical_tool_id="exec.run",
        handler=_adapt(_handle_exec_run_merged),
        input_schema=_schema({
            "target": {"type": "string", "enum": ["local", "ssh", "telnet"],
                       "description": "Target: local (default, this host), ssh, or telnet.", "default": "local"},
            "shell": {"type": "string", "enum": ["cmd", "powershell"],
                      "description": "Shell type for local target.", "default": "cmd"},
            "command": {"type": "string", "description": "Command to execute."},
            "host": {"type": "string", "description": "Remote host IP/hostname (ssh/telnet)."},
            "port": {"type": "integer", "description": "Remote port (ssh default 22, telnet default 23)."},
            "username": {"type": "string", "description": "Login username (ssh/telnet)."},
            "password": {"type": "string", "description": "Login password (ssh/telnet)."},
            "vendor": {"type": "string", "description": "Device vendor (ssh/telnet).", "default": "generic"},
            "working_dir": {"type": "string", "description": "Working directory for local commands.", "default": ""},
            "env_vars": {"type": "object", "description": "Extra environment variables for the command.", "default": {}},
            "timeout": {"type": "integer", "description": "Timeout seconds (default 30, max 120).", "default": 30},
            "workspace_id": _S["workspace_id"],
        }, ["command"]),
        risk_level="high", requires_approval=True,
        permission_action="exec",
        description="Execute command on target machine: local shell (with working_dir/env_vars), SSH remote, or Telnet remote. Dangerous commands blocked automatically.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="exec.python",
        handler=_adapt(handle_python_exec),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "code": _S["code"],
            "timeout": {"type": "integer", "description": "Max execution seconds (1-60, default 30).", "default": 30},
        }, ["code"]),
        risk_level="high", requires_approval=True,
        permission_action="exec",
        description="Run a Python snippet on the local host. AST-sandboxed.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="exec.slash",
        handler=_adapt(handle_slash_run),
        input_schema=_schema({
            "command": {"type": "string", "description": "Slash command name."},
            "args": {"type": "string", "description": "Optional command arguments."},
        }, ["command"]),
        description="Run a registered slash command.",
    ),

    # ── v3.9.1: workspace.file (merged) ────────────────────────────────
    # 6 个原 tool 合并为单一入口: workspace.file(action=X)
    # 老 tool_id 保留为 alias (callable_by_llm=False) 兜底 router / baseline / 测试
    CanonicalToolEntry(
        canonical_tool_id="workspace.file",
        handler=_adapt(_handle_workspace_file_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["list", "read", "read_image",
                                                  "edit", "patch", "write_artifact"],
                       "description": "Operation: list, read, read_image, edit, patch, or write_artifact."},
            "subdir": {"type": "string", "description": "[list] Workspace-relative subdirectory."},
            "filepath": _S["filepath"],
            "limit": {"type": "integer", "default": 50000,
                      "description": "[read] Max chars to return."},
            "offset": {"type": "integer", "default": 0,
                       "description": "[read] Start reading from line N (0-based pagination)."},
            "old_string": _S["old_string"],
            "new_string": _S["new_string"],
            "replace_all": {"type": "boolean", "default": False,
                            "description": "[edit] Replace all occurrences."},
            "dry_run": {"type": "boolean", "default": False,
                        "description": "[edit] Preview diff without writing to file."},
            "patch_text": _S["patch_text"],
            "filename": {"type": "string", "description": "[write_artifact] Output filename."},
            "content": _S["content"],
        }, ["action"]),
        permission_action="",  # Mixed read/write; inferred from action at runtime
        description=(
            "Unified workspace file tool. action=list (list files / check exists), "
            "action=read (read text file with offset+limit pagination), "
            "action=read_image (read image dimensions+format), "
            "action=edit (string replace; supports replace_all/dry_run), "
            "action=patch (apply unified diff text), "
            "action=write_artifact (write named artifact file). "
            "Old tool_ids (workspace.file.read etc.) are deprecated aliases."
        ),
    ),
    # Aliases (callable_by_llm=False) — kept for router / baseline / test compat
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.list",
        handler=_adapt(_handle_workspace_file_merged),  # routes via action=list
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "subdir": {"type": "string"},
            "filepath": _S["filepath"],
        }),
        callable_by_llm=False,
        description="[DEPRECATED alias for workspace.file] Use workspace.file(action=list).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.read",
        handler=_adapt(_handle_workspace_file_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "limit": {"type": "integer", "default": 50000},
            "offset": {"type": "integer", "default": 0},
        }, ["filepath"]),
        callable_by_llm=False,
        description="[DEPRECATED alias for workspace.file] Use workspace.file(action=read).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.read_image",
        handler=_adapt(_handle_workspace_file_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
        }, ["filepath"]),
        callable_by_llm=False,
        description="[DEPRECATED alias for workspace.file] Use workspace.file(action=read_image).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.edit",
        handler=_adapt(_handle_workspace_file_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "old_string": _S["old_string"], "new_string": _S["new_string"],
            "replace_all": {"type": "boolean", "default": False},
            "dry_run": {"type": "boolean", "default": False},
        }, ["filepath", "old_string", "new_string"]),
        risk_level="medium", requires_approval=False,
        callable_by_llm=False,
        description="[DEPRECATED alias for workspace.file] Use workspace.file(action=edit).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.patch",
        handler=_adapt(_handle_workspace_file_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "filepath": _S["filepath"],
            "patch_text": _S["patch_text"],
        }, ["filepath", "patch_text"]),
        callable_by_llm=False,
        description="[DEPRECATED alias for workspace.file] Use workspace.file(action=patch).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.file.write_artifact",
        handler=_adapt(_handle_workspace_file_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "filename": {"type": "string"},
            "content": _S["content"],
        }, ["filename", "content"]),
        callable_by_llm=False,
        description="[DEPRECATED alias for workspace.file] Use workspace.file(action=write_artifact).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.metadata.get",
        handler=_adapt(handle_ws_get_metadata),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),

# ─── v3.9.1: workspace.artifact (merged) ────────────────────────────
# 7 个原 tool 合并: list / read / save / tag / delete_soft / diff / export
# 老 tool_id 保留为 alias (callable_by_llm=False) 兜底
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["list", "read", "save", "tag",
                                                  "delete", "diff", "export"],
                       "description": "Operation: list, read, save, tag, delete (soft), diff, or export."},
            "status": _S["status"],
            "query": _S["query"],
            "limit": _S["limit"],
            "artifact_id": _S["artifact_id"],
            "title": _S["title"],
            "content": _S["content"],
            "artifact_type": {"type": "string",
                               "description": "[save] Artifact type (e.g. report, analysis, log)."},
            "sensitivity": {"type": "string", "enum": ["internal", "sensitive"],
                            "default": "internal"},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "[tag] Tags to apply."},
            "artifact_a": {"type": "string", "description": "[diff] First artifact id."},
            "artifact_b": {"type": "string", "description": "[diff] Second artifact id."},
            "destination": {"type": "string",
                            "description": "[export] Workspace-relative destination path."},
        }, ["action"]),
        permission_action="",  # Mixed read/write; inferred at runtime
        description=(
            "Unified workspace artifact tool. action=list (list/search), "
            "action=read (read content), action=save (create new artifact), "
            "action=tag (apply tags), action=delete (soft-delete, requires approval), "
            "action=diff (compare two artifacts), action=export (export to file). "
            "Old tool_ids (workspace.artifact.read etc.) are deprecated aliases."
        ),
    ),
    # Aliases
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.list",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "status": _S["status"],
            "query": _S["query"], "limit": _S["limit"],
        }),
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.artifact(action=list).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.read",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "artifact_id": _S["artifact_id"],
        }, ["artifact_id"]),
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.artifact(action=read).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.save",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "title": _S["title"], "content": _S["content"],
            "artifact_type": {"type": "string"},
            "sensitivity": {"type": "string", "enum": ["internal", "sensitive"], "default": "internal"},
        }, ["content"]),
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.artifact(action=save).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.tag",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "artifact_id": _S["artifact_id"],
            "tags": {"type": "array", "items": {"type": "string"}},
        }, ["artifact_id", "tags"]),
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.artifact(action=tag).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.delete_soft",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "artifact_id": _S["artifact_id"],
        }, ["artifact_id"]),
        risk_level="medium", requires_approval=True,
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.artifact(action=delete).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.diff",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "artifact_a": {"type": "string"},
            "artifact_b": {"type": "string"},
        }, ["artifact_a", "artifact_b"]),
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.artifact(action=diff).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="workspace.artifact.export",
        handler=_adapt(_handle_workspace_artifact_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "artifact_id": {"type": "string"},
            "destination": {"type": "string"},
        }, ["artifact_id", "destination"]),
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.artifact(action=export).",
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
        canonical_tool_id="knowledge.source.list",
        handler=_adapt(_k_source_list),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.chunk.list",
        handler=_adapt(_k_chunk_list),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.import",
        handler=_adapt(_handle_knowledge_import_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
            "artifact_id": _S["artifact_id"],
            "title": {"type": "string", "description": "Document title."},
        }),
        description="Import a file or artifact into the knowledge base. Auto-detects format.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.reindex",
        handler=_adapt(_handle_knowledge_reindex_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "source_id": _S["source_id"],
        }),
        description="Reindex a specific knowledge source or all sources.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.manage",
        handler=_adapt(_k_source_manage),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
            "action": {"type": "string", "description": "Action: disable, delete, or reindex.", "enum": ["disable", "delete", "reindex"]},
        }, ["source_id", "action"]),
        description="Manage a knowledge source: disable (hide from search), delete (permanently remove), or reindex (rebuild index).",
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
        canonical_tool_id="web.weather",
        handler=_adapt(_weather_merged),
        input_schema=_schema({
            "location": _S["location"],
            "days": {"type": "integer", "description": "Days: 1=current weather, 2-10=forecast.", "default": 1},
            "units": _S["units"], "language": _S["language"],
        }, ["location"]),
        description="Get weather for a location. days=1 returns current conditions; days=2-10 returns daily forecast. Uses Open-Meteo structured API with web search fallback.",
    ),

    # Runtime / Run / Session
    CanonicalToolEntry(
        canonical_tool_id="system.diagnostics",
        handler=_adapt(handle_runtime_diagnostics),
        input_schema=_schema({"workspace_id": _S["workspace_id"]}),
    ),
    # v3.2: stub tools removed — use system.diagnostics for all health checks
    CanonicalToolEntry(
        canonical_tool_id="system.run.get",
        handler=_adapt(handle_run_get_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "run_id": _S["run_id"],
            "limit": _S["limit"],
        }),
        description="List recent runs or get a specific run summary.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="system.session.get",
        handler=_adapt(handle_session_get_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "session_id": _S["session_id"],
            "status": _S["status"],
            "limit": _S["limit"],
        }),
        description="List sessions or get a specific session summary.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="system.session.checkpoint",
        handler=_adapt(handle_session_checkpoint),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
        }, ["session_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="system.session.rewind",
        handler=_adapt(handle_session_rewind),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
            "snapshot_id": {"type": "string"}, "dry_run": _S["dry_run"],
        }, ["session_id", "snapshot_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="system.session.export",
        handler=_adapt(handle_session_export),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
            "format": _S["format"],
        }, ["session_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="system.review.item.list",
        handler=_adapt(_review_item_list),
        input_schema=_schema({"workspace_id": _S["workspace_id"], "limit": _S["limit"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="system.review.item.update",
        handler=_adapt(_review_item_update),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "review_id": {"type": "string"},
            "status": {"type": "string"},
        }, ["review_id", "status"]),
    ),

    # Memory
    CanonicalToolEntry(
        canonical_tool_id="memory.search",
        handler=_adapt(handle_memory_search_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "query": _S["query"],
            "scope": {"type": "string"},
            "memory_type": {"type": "string"},
            "status": {"type": "string"},
            "session_id": _S["session_id"],
            "limit": _S["limit"],
        }),
        description="Search memories by query or list all retrievable memories.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.profile",
        handler=_adapt(handle_memory_profile_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "field": {"type": "string"},
            "value": {"type": "string"},
            "merge": {"type": "boolean", "default": True},
        }),
        description="Get user profile or set a profile field.",
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
        canonical_tool_id="data.csv.summarize",
        handler=_adapt(handle_csv_summarize),
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
        risk_level="medium",
        permission_action="exec",
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
        input_schema=_schema({}),
        description="List available capability-backed skills.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.find",
        handler=_adapt(handle_skill_find),
        input_schema=_schema({
            "query": _S["query"],
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 20},
        }, ["query"]),
        description="Search available capability-backed skills.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.load",
        handler=_adapt(handle_skill_load),
        input_schema=_schema({
            "skill_name": _S["skill_name"],
        }, ["skill_name"]),
        description="Load a capability-backed skill and return its modules/tools/prompt hints.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="skill.inspect",
        handler=_adapt(handle_skill_inspect),
        input_schema=_schema({
            "skill_name": _S["skill_name"],
        }, ["skill_name"]),
        description="Inspect a capability-backed skill.",
    ),
    # Skill creation/installation remains disabled in the canonical LLM surface.
    # Define CapabilityPackage entries instead of allowing runtime skill mutation.
    # Slash command tools removed — use exec.slash for slash execution.
    # ── Directory-level business tools ──
    CanonicalToolEntry(
        canonical_tool_id="config.analysis.run",
        handler=_adapt(_handler_config_analysis_run),
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
        handler=_adapt(_handler_pcap_analysis_run),
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
    # ── v3.4: Git tools ──
    CanonicalToolEntry(
        canonical_tool_id="git.status",
        handler=_adapt(_handler_git_status),
        input_schema=_schema({
            "repo_path": {"type": "string", "description": "Path to git repository. Default: current directory.", "default": "."},
        }),
        description="Check git status — shows modified, staged, and untracked files with branch info.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="git.diff",
        handler=_adapt(_handler_git_diff),
        input_schema=_schema({
            "repo_path": {"type": "string", "description": "Path to git repository.", "default": "."},
            "staged": {"type": "boolean", "description": "Show staged changes only.", "default": False},
            "file_path": {"type": "string", "description": "Limit diff to specific file.", "default": ""},
        }),
        description="Show git diff — unstaged or staged changes, optionally scoped to a file.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="git.log",
        handler=_adapt(_handler_git_log),
        input_schema=_schema({
            "repo_path": {"type": "string", "description": "Path to git repository.", "default": "."},
            "n": {"type": "integer", "description": "Number of recent commits.", "default": 10},
            "file_path": {"type": "string", "description": "Limit log to specific file.", "default": ""},
        }),
        description="View git commit history with one-line summaries.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="git.commit",
        handler=_adapt(_handler_git_commit),
        input_schema=_schema({
            "repo_path": {"type": "string", "description": "Path to git repository.", "default": "."},
            "message": {"type": "string", "description": "Commit message."},
            "files": {"type": "array", "items": {"type": "string"}, "description": "Specific files to stage and commit. Omit to stage all (-A)."},
        }, ["message"]),
        risk_level="medium", requires_approval=True,
        description="Stage changes and create a commit. Requires approval. Use git.status and git.diff first to review what will be committed.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="git.push",
        handler=_adapt(_handler_git_push),
        input_schema=_schema({
            "repo_path": {"type": "string", "description": "Path to git repository.", "default": "."},
            "remote": {"type": "string", "description": "Remote name.", "default": "origin"},
            "branch": {"type": "string", "description": "Branch to push.", "default": ""},
        }),
        risk_level="medium", requires_approval=True,
        description="Push commits to remote. Requires approval.",
    ),
    # ── v3.4: Code search ──
    CanonicalToolEntry(
        canonical_tool_id="code.search",
        handler=_adapt(_handler_code_search),
        input_schema=_schema({
            "pattern": {"type": "string", "description": "Search pattern (regex or literal). Example: 'import.*paramiko', 'class DeviceSession'."},
            "directory": {"type": "string", "description": "Directory to search. Default: current project root.", "default": "."},
            "file_type": {"type": "string", "description": "File type filter: py, ts, js, yaml, json, md, etc.", "default": ""},
            "max_results": {"type": "integer", "description": "Max matching lines.", "default": 50},
        }, ["pattern"]),
        description="Search the codebase using ripgrep (fast) or Python fallback. Returns matching lines with file paths and line numbers. Use for finding functions, classes, imports, patterns across the codebase.",
    ),
    # ── v3.4: Browser tools ──
    CanonicalToolEntry(
        canonical_tool_id="browser.navigate",
        handler=_adapt(_handler_browser_navigate),
        input_schema=_schema({
            "url": {"type": "string", "description": "Full URL to navigate to (https://...)."},
            "wait_selector": {"type": "string", "description": "Optional CSS selector to wait for.", "default": ""},
        }, ["url"]),
        description="Open a browser, navigate to a URL, and return page title + visible text content. Use for reading documentation, inspecting web apps, or scraping public pages.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="browser.extract",
        handler=_adapt(_handler_browser_extract),
        input_schema=_schema({
            "url": {"type": "string", "description": "Full URL to open."},
            "selector": {"type": "string", "description": "CSS selector for element to extract. Default: body.", "default": "body"},
        }, ["url"]),
        description="Extract text content from a specific element on a web page. Use for targeted scraping or reading specific sections of documentation.",
    ),
    # ── v3.7: Browser screenshot & click ──
    CanonicalToolEntry(
        canonical_tool_id="browser.screenshot",
        handler=_adapt(_handler_browser_screenshot),
        input_schema=_schema({
            "url": {"type": "string", "description": "Full URL to screenshot."},
            "full_page": {"type": "boolean", "description": "Capture full page or just viewport.", "default": False},
        }, ["url"]),
        description="Take a screenshot of a web page and return a base64-encoded PNG image. Use to visually inspect a page.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="browser.click",
        handler=_adapt(_handler_browser_click),
        input_schema=_schema({
            "selector": {"type": "string", "description": "CSS selector of the element to click."},
        }, ["selector"]),
        description="Click an element on the currently loaded browser page. Navigate to a URL first using browser.navigate.",
    ),
    # ── CMDB device asset tools ──
    CanonicalToolEntry(
        canonical_tool_id="device.list",
        handler=_adapt(_handler_cmdb_list_assets),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "search": {"type": "string", "description": "Fuzzy search by name, vendor, host, or model. Example: 'AR1' or 'huawei'."},
            "filter": {"type": "string", "description": "JSON filter string. Example: '{\"type\": \"switch\"}' or '{\"vendor\": \"cisco\"}'."},
            "sort_by": {"type": "string", "description": "Sort field: name (default), type, vendor, host, updated_at."},
        }),
        description="List and search CMDB device assets. Supports fuzzy text search and JSON filtering by type/vendor. Returns asset list plus overall statistics (total count, breakdown by type/vendor/protocol).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="device.get",
        handler=_adapt(_handler_cmdb_get_asset),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "asset_id": {"type": "string", "description": "Asset ID to look up."},
        }, ["asset_id"]),
        description="Get full detail for a single CMDB asset by asset_id.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="device.add",
        handler=_adapt(_handler_cmdb_add_asset),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "name": {"type": "string", "description": "Device name."},
            "host": {"type": "string", "description": "Management IP or hostname."},
            "type": {"type": "string", "description": "Device type: switch, router, firewall.", "enum": ["switch", "router", "firewall", "server", "other"], "default": "switch"},
            "vendor": {"type": "string", "description": "Vendor: h3c, huawei, cisco, etc."},
            "protocol": {"type": "string", "description": "Connection protocol: ssh, telnet.", "enum": ["ssh", "telnet"], "default": "ssh"},
            "port": {"type": "integer", "description": "Connection port.", "default": 22},
            "username": {"type": "string", "description": "Login username."},
        }, ["name", "host"]),
        risk_level="medium", requires_approval=True,
        description="Add a new device asset to the CMDB. Passwords are not persisted. Requires approval.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="device.delete",
        handler=_adapt(_handler_cmdb_delete_asset),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "asset_id": {"type": "string", "description": "Asset ID to delete."},
        }, ["asset_id"]),
        risk_level="medium", requires_approval=True,
        description="Soft-delete a CMDB asset (tombstone, recoverable). Requires approval.",
    ),
    # ── FileStore tools ──
    # ── v3.9.1: workspace.filestore (merged) ──────────────────────────
    # 2 个原 tool 合并: file.references / file.import_workspace_path
    # 老 tool_id 保留为 alias (callable_by_llm=False) 兜底
    CanonicalToolEntry(
        canonical_tool_id="workspace.filestore",
        handler=_adapt(_handle_workspace_filestore_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["references", "import"],
                       "description": "Operation: references (query cross-refs) or import (import to FileStore)."},
            "file_id": {"type": "string",
                        "description": "[references] FileStore file_id to query."},
            "filepath": {"type": "string",
                         "description": "[references|import] Workspace-relative path."},
        }, ["action"]),
        description=(
            "Unified FileStore tool. action=references (query cross-references for a file), "
            "action=import (import a workspace-relative file into FileStore and get file_id). "
            "Old tool_ids (file.references / file.import_workspace_path) are deprecated aliases."
        ),
    ),
    # Aliases
    CanonicalToolEntry(
        canonical_tool_id="file.references",
        handler=_make_filestore_handler("file.references", ["file_id"]),
        input_schema=_schema({
            "file_id": {"type": "string"},
        }, ["file_id"]),
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.filestore(action=references).",
    ),
    CanonicalToolEntry(
        canonical_tool_id="file.import_workspace_path",
        handler=_make_filestore_handler("file.import_workspace_path", ["filepath"]),
        input_schema=_schema({
            "filepath": {"type": "string"},
        }, ["filepath"]),
        callable_by_llm=False,
        description="[DEPRECATED] Use workspace.filestore(action=import).",
    ),
    # ── v3.5 Merged tools ──
    CanonicalToolEntry(
        canonical_tool_id="web.page.process",
        handler=_adapt(_handle_web_page_merged),
        input_schema=_schema({
            "url": _S["url"],
            "action": {"type": "string", "enum": ["summarize", "extract_links", "save_artifact"],
                       "description": "summarize (default), extract_links, or save_artifact.", "default": "summarize"},
            "workspace_id": _S["workspace_id"], "title": _S["title"],
        }, ["url"]),
        description="Process a web page: summarize, extract links, or save as artifact.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="data.validate",
        handler=_adapt(_handle_data_validate_merged),
        input_schema=_schema({
            "text": _S["text"],
            "format": {"type": "string", "enum": ["json", "yaml"], "description": "Data format.", "default": "json"},
        }, ["text"]),
        description="Validate JSON or YAML data structure.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.read",
        handler=_adapt(_handle_knowledge_read_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "level": {"type": "string", "enum": ["chunk", "source", "parent"],
                      "description": "chunk (default), source, or parent.", "default": "chunk"},
            "chunk_id": _S["chunk_id"], "source_id": _S["source_id"],
        }, ["workspace_id"]),
        description="Read knowledge: chunk, source, or parent document.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="memory.manage",
        handler=_adapt(_handle_memory_manage_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "action": {"type": "string", "enum": ["create", "update", "confirm", "delete"],
                       "description": "create (default), update, confirm, or delete.", "default": "create"},
            "title": _S["title"], "content": _S["content"], "memory_id": _S["memory_id"],
            "scope": {"type": "string", "enum": ["short_term", "project", "long_term"], "default": "long_term"},
            "memory_type": {"type": "string", "default": "knowledge_note"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"}, "metadata": {"type": "object"},
        }, ["action"]),
        description="Manage memory: create, update, confirm, or delete records.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="text.analyze",
        handler=_adapt(_handle_text_analyze_merged),
        input_schema=_schema({
            "text": _S["text"],
            "action": {"type": "string", "enum": ["redact", "diff", "keywords", "classify"],
                       "description": "redact (default), diff (needs text_b), keywords, or classify.", "default": "redact"},
            "text_b": {"type": "string", "description": "Second text for diff action."},
            "limit": _S["limit"],
        }, ["text"]),
        description="Analyze text: redact, diff, extract keywords, or classify.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="system.session.snapshot",
        handler=_adapt(_handle_session_snapshot_merged),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "session_id": _S["session_id"],
            "action": {"type": "string", "enum": ["create", "list"],
                       "description": "create (default) or list.", "default": "create"},
            "reason": _S["reason"],
        }, ["session_id"]),
        description="Create or list session snapshots for audit.",
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
        try:
            from tool_runtime.manifest_registry import get_manifest
            manifest = get_manifest(entry.canonical_tool_id)
        except Exception:
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
