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
    _handler_parser_parse_config_text,
    _handler_parser_extract_interfaces,
    _handler_parser_extract_routes,
)


def _schema(properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
    }


_S = {
    "workspace_id": {"type": "string", "description": "Workspace id."},
    "query": {"type": "string", "description": "Search or filter text."},
    "limit": {"type": "integer", "description": "Maximum items to return.", "default": 10},
    "artifact_id": {"type": "string", "description": "Artifact id."},
    "source_id": {"type": "string", "description": "Knowledge source id."},
    "chunk_id": {"type": "string", "description": "Knowledge chunk id."},
    "url": {"type": "string", "description": "Public http(s) URL."},
    "title": {"type": "string", "description": "Human-readable title."},
    "content": {"type": "string", "description": "Text content."},
    "text": {"type": "string", "description": "Text to inspect or transform."},
    "session_id": {"type": "string", "description": "Session id."},
    "run_id": {"type": "string", "description": "Run id."},
    "filepath": {"type": "string", "description": "Workspace-relative file path."},
    "days": {"type": "integer", "description": "Forecast horizon in days, 1-10.", "default": 3},
    "recency": {"type": "string", "description": "Time filter.", "default": "week"},
    "format": {"type": "string", "description": "Output format.", "enum": ["txt", "md"]},
    "language": {"type": "string", "description": "Preferred language code.", "default": "zh-CN"},
    "command": {"type": "string", "description": "Shell command string."},
    "status": {"type": "string", "description": "Filter by status."},
    "location": {"type": "string", "description": "City or location name."},
    "units": {"type": "string", "description": "Temperature units.", "enum": ["metric", "imperial"], "default": "metric"},
    "code": {"type": "string", "description": "Python source code."},
    "reason": {"type": "string", "description": "Human-readable reason or note."},
    "dry_run": {"type": "boolean", "description": "Preview without making changes.", "default": True},
    "memory_id": {"type": "string", "description": "Memory entry id."},
    "old_string": {"type": "string", "description": "Text to replace."},
    "new_string": {"type": "string", "description": "Replacement text."},
    "patch_text": {"type": "string", "description": "Unified diff patch text."},
    "skill_name": {"type": "string", "description": "Skill directory name."},
    "description": {"type": "string", "description": "Short description."},
    "capabilities": {"type": "array", "description": "Capability identifiers.", "items": {"type": "string"}},
    "page_range": {"type": "string", "description": "Optional page range, e.g. 1-3."},
}


# canonical_tool_id -> CanonicalToolEntry
_RAW_REGISTRY: list[CanonicalToolEntry] = [
    # Host
    CanonicalToolEntry(
        canonical_tool_id="host.shell.exec",
        handler=_adapt(handle_command_approved_exec),
        input_schema=_schema({"command": _S["command"]}, ["command"]),
        risk_level="high", requires_approval=True,
        permission_action="host.shell.exec",
        description="Run a shell command on the local host. Requires approval.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="host.powershell.exec",
        handler=_adapt(handle_powershell_approved_script),
        input_schema=_schema({"command": _S["command"]}, ["command"]),
        risk_level="high", requires_approval=True,
        permission_action="host.powershell.exec",
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
        permission_action="host.python.exec",
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
        canonical_tool_id="knowledge.query",
        handler=_adapt(handle_knowledge_search),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "query": _S["query"], "limit": _S["limit"],
        }, ["query"]),
    ),
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
        handler=_adapt(handle_knowledge_search),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"],
            "filepath": _S["filepath"],
        }, ["filepath"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.import.document",
        handler=_adapt(handle_knowledge_search),
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
        handler=_adapt(handle_knowledge_search),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }, ["source_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.source.delete",
        handler=_adapt(handle_knowledge_search),
        input_schema=_schema({
            "workspace_id": _S["workspace_id"], "source_id": _S["source_id"],
        }, ["source_id"]),
    ),
    CanonicalToolEntry(
        canonical_tool_id="knowledge.not_found.explain",
        handler=_adapt(handle_knowledge_explain_not_found),
        input_schema=_schema({"query": _S["query"], "workspace_id": _S["workspace_id"]}, ["query"]),
    ),

    # Network
    CanonicalToolEntry(
        canonical_tool_id="network.config.parse",
        handler=_adapt(_handler_parser_parse_config_text),
        input_schema=_schema({
            "text": _S["text"],
            "vendor": {"type": "string", "description": "Vendor slug, e.g. cisco, huawei."},
        }, ["text"]),
        description="Offline parse of a network device configuration.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="network.interface.extract",
        handler=_adapt(_handler_parser_extract_interfaces),
        input_schema=_schema({"text": _S["text"]}, ["text"]),
        description="Extract interface entries from a configuration.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="network.route.extract",
        handler=_adapt(_handler_parser_extract_routes),
        input_schema=_schema({"text": _S["text"]}, ["text"]),
        description="Extract route entries from a configuration.",
    ),
    CanonicalToolEntry(
        canonical_tool_id="network.config.translate",
        handler=_adapt(handle_knowledge_search),
        input_schema=_schema({
            "parsed_config": {"type": "object"},
            "target_format": {"type": "string", "description": "Target vendor slug."},
        }, ["parsed_config"]),
        description="Translate a parsed configuration between formats.",
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
        handler=_adapt(handle_session_list_snapshots),
        input_schema=_schema({"workspace_id": _S["workspace_id"], "limit": _S["limit"]}),
    ),
    CanonicalToolEntry(
        canonical_tool_id="review.item.update",
        handler=_adapt(handle_session_snapshot),
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
        spec = ToolSpec(
            tool_id=entry.canonical_tool_id,
            handler_id=entry.canonical_tool_id,
            description=entry.description,
            category=ns_entry.category if ns_entry else "",
            risk_level=entry.risk_level,
            requires_approval=entry.requires_approval,
            permission_action=entry.permission_action or entry.canonical_tool_id,
            callable_by_llm=True,
            enabled=True,
            input_schema=entry.input_schema,
        )
        out.append((spec, entry.handler))
    return out
