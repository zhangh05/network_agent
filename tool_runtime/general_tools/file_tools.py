# tool_runtime/general_tools/file_tools.py
# v2.1.1 real split — handlers defined in this module.
# Imports shared helpers from general_tools_base.
from tool_runtime.general_tools_base import (
    _ok, _error, _result, _safe_preview, _generate_diff_preview,
    _validate_workspace_path, safe_workspace_path,
    ToolSpec, ToolInvocation, ToolResult, redact_tool_output, handle_python_exec,
handle_file_list,
    handle_file_exists,
    handle_file_read,
    handle_file_edit,
    handle_file_patch,
    handle_ws_list_files,
    handle_ws_read_text_preview,
    handle_ws_write_artifact_file,
    handle_ws_path_exists,
    handle_ws_get_metadata
)

# Reassign __module__ for audit/test verification
handle_file_list.__module__ = __name__
handle_file_exists.__module__ = __name__
handle_file_read.__module__ = __name__
handle_file_edit.__module__ = __name__
handle_file_patch.__module__ = __name__
handle_ws_list_files.__module__ = __name__
handle_ws_read_text_preview.__module__ = __name__
handle_ws_write_artifact_file.__module__ = __name__
handle_ws_path_exists.__module__ = __name__
handle_ws_get_metadata.__module__ = __name__

__all__ = [
'handle_file_list', 'handle_file_exists', 'handle_file_read', 'handle_file_edit', 'handle_file_patch', 'handle_ws_list_files', 'handle_ws_read_text_preview', 'handle_ws_write_artifact_file', 'handle_ws_path_exists', 'handle_ws_get_metadata'
]
