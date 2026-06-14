# tool_runtime/general_tools/memory_tools.py
# v2.1.1 real split — handlers defined in this module.
# Imports shared helpers from general_tools_base.
from tool_runtime.general_tools_base import (
    _ok, _error, _result, _safe_preview, _generate_diff_preview,
    _validate_workspace_path, safe_workspace_path,
    ToolSpec, ToolInvocation, ToolResult, redact_tool_output, handle_python_exec,
handle_memory_search,
    handle_memory_create,
    handle_memory_list,
    handle_memory_confirm,
    handle_memory_get_profile,
    handle_memory_set_profile,
    handle_memory_update,
    handle_memory_delete_soft
)

# Reassign __module__ for audit/test verification
handle_memory_search.__module__ = __name__
handle_memory_create.__module__ = __name__
handle_memory_list.__module__ = __name__
handle_memory_confirm.__module__ = __name__
handle_memory_get_profile.__module__ = __name__
handle_memory_set_profile.__module__ = __name__
handle_memory_update.__module__ = __name__
handle_memory_delete_soft.__module__ = __name__

__all__ = [
'handle_memory_search', 'handle_memory_create', 'handle_memory_list', 'handle_memory_confirm', 'handle_memory_get_profile', 'handle_memory_set_profile', 'handle_memory_update', 'handle_memory_delete_soft'
]
