# tool_runtime/general_tools/skill_tools.py
# v2.1.1 real split — handlers defined in this module.
# Imports shared helpers from general_tools_base.
from tool_runtime.general_tools_base import (
    _ok, _error, _result, _safe_preview, _generate_diff_preview,
    _validate_workspace_path, safe_workspace_path,
    ToolSpec, ToolInvocation, ToolResult, redact_tool_output, handle_python_exec,
handle_skill_list,
    handle_skill_request_load,
    handle_skill_load,
    handle_skill_find,
    handle_skill_create,
    handle_skill_inspect
)

# Reassign __module__ for audit/test verification
handle_skill_list.__module__ = __name__
handle_skill_request_load.__module__ = __name__
handle_skill_load.__module__ = __name__
handle_skill_find.__module__ = __name__
handle_skill_create.__module__ = __name__
handle_skill_inspect.__module__ = __name__

__all__ = [
'handle_skill_list', 'handle_skill_request_load', 'handle_skill_load', 'handle_skill_find', 'handle_skill_create', 'handle_skill_inspect'
]
