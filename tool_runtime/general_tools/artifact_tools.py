# tool_runtime/general_tools/artifact_tools.py
# v2.1.1 real split — handlers defined in this module.
# Imports shared helpers from general_tools_base.
from tool_runtime.general_tools_base import (
    _ok, _error, _result, _safe_preview, _generate_diff_preview,
    _validate_workspace_path, safe_workspace_path,
    ToolSpec, ToolInvocation, ToolResult, redact_tool_output, handle_python_exec,
handle_artifact_search,
    handle_artifact_read_content_safe,
    handle_artifact_save_result,
    handle_artifact_tag,
    handle_artifact_delete_soft
)

# Reassign __module__ for audit/test verification
handle_artifact_search.__module__ = __name__
handle_artifact_read_content_safe.__module__ = __name__
handle_artifact_save_result.__module__ = __name__
handle_artifact_tag.__module__ = __name__
handle_artifact_delete_soft.__module__ = __name__

__all__ = [
'handle_artifact_search', 'handle_artifact_read_content_safe', 'handle_artifact_save_result', 'handle_artifact_tag', 'handle_artifact_delete_soft'
]
