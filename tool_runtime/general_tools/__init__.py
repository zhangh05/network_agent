"""General Tools — v2.1.1 real split."""
from tool_runtime.general_tools.web_tools import handle_web_search, handle_weather_current, handle_weather_forecast, handle_news_search, handle_web_fetch_summary, handle_web_official_doc_search, handle_web_extract_links, handle_web_save_to_artifact
from tool_runtime.general_tools.memory_tools import handle_memory_search, handle_memory_create, handle_memory_list, handle_memory_confirm, handle_memory_get_profile, handle_memory_set_profile, handle_memory_update, handle_memory_delete_soft
from tool_runtime.general_tools.skill_tools import handle_skill_list, handle_skill_request_load, handle_skill_load, handle_skill_find, handle_skill_create, handle_skill_inspect
from tool_runtime.general_tools.session_tools import handle_session_list, handle_session_get_summary, handle_session_create, handle_session_archive, handle_run_list_recent, handle_run_get_summary, handle_session_snapshot, handle_session_list_snapshots, handle_session_rewind, handle_session_checkpoint, handle_session_export
from tool_runtime.general_tools.file_tools import handle_file_list, handle_file_exists, handle_file_read, handle_file_edit, handle_file_patch, handle_ws_list_files, handle_ws_read_text_preview, handle_ws_write_artifact_file, handle_ws_path_exists, handle_ws_get_metadata
from tool_runtime.general_tools.command_tools import handle_command_approved_exec, handle_powershell_approved_script, handle_slash_run, handle_python_exec
from tool_runtime.general_tools.artifact_tools import handle_artifact_search, handle_artifact_read_content_safe, handle_artifact_save_result, handle_artifact_tag, handle_artifact_delete_soft
from tool_runtime.general_tools.pdf_tools import handle_pdf_extract_text
from tool_runtime.general_tools.agent_tools import handle_agent_spawn, handle_agent_list_roles, handle_agent_team, handle_agent_get_result

# Rebuild ALL_GENERAL_TOOLS: use wrapper handlers for split tools, base handlers for uncategorized
import tool_runtime.general_tools_base as _base
_wrappers = {name: obj for name, obj in list(globals().items()) if name.startswith('handle_') and callable(obj)}

ALL_GENERAL_TOOLS = []
for spec, handler in _base.ALL_GENERAL_TOOLS:
    wrapper = _wrappers.get(handler.__name__, handler)
    ALL_GENERAL_TOOLS.append((spec, wrapper))

__all__ = ["ALL_GENERAL_TOOLS"]

# Override register_all_general_tools to use wrapper handlers
from copy import deepcopy
import tool_runtime.general_tools_base as _gt_base

def register_all_general_tools(registry):
    """Register all tools using wrapper handlers from sub-modules."""
    REMOVED = getattr(_gt_base, 'REMOVED_GENERAL_TOOL_IDS', set())
    for spec, handler in ALL_GENERAL_TOOLS:
        if spec.tool_id in REMOVED:
            continue
        registry.register_tool(deepcopy(spec), handler)
    return registry

# Re-export attributes for backward compatibility (conftest monkeypatches)
WS_ROOT = _gt_base.WS_ROOT
ROOT = _gt_base.ROOT
_generate_diff_preview = _gt_base._generate_diff_preview
_validate_workspace_path = _gt_base._validate_workspace_path
handle_agent_input_validate = getattr(_gt_base, 'handle_agent_input_validate', None)
handle_memory_create = globals().get('handle_memory_create')
handle_memory_confirm = globals().get('handle_memory_confirm')
handle_memory_get_profile = globals().get('handle_memory_get_profile')
handle_memory_set_profile = globals().get('handle_memory_set_profile')
handle_skill_list = globals().get('handle_skill_list')
handle_skill_request_load = globals().get('handle_skill_request_load')
handle_agent_team = globals().get('handle_agent_team')
REMOVED_GENERAL_TOOL_IDS = getattr(_gt_base, 'REMOVED_GENERAL_TOOL_IDS', set())
ALL_GENERAL_TOOLS = ALL_GENERAL_TOOLS  # already defined above
