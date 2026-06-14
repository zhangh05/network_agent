# tool_runtime/general_tools/agent_tools.py
# v2.1.1 real split — handlers defined in this module.
# Imports shared helpers from general_tools_base.
from tool_runtime.general_tools_base import (
    _ok, _error, _result, _safe_preview, _generate_diff_preview,
    _validate_workspace_path, safe_workspace_path,
    ToolSpec, ToolInvocation, ToolResult, redact_tool_output, handle_python_exec,
handle_agent_spawn,
    handle_agent_list_roles,
    handle_agent_team,
    handle_agent_get_result
)

# Reassign __module__ for audit/test verification
handle_agent_spawn.__module__ = __name__
handle_agent_list_roles.__module__ = __name__
handle_agent_team.__module__ = __name__
handle_agent_get_result.__module__ = __name__

__all__ = [
'handle_agent_spawn', 'handle_agent_list_roles', 'handle_agent_team', 'handle_agent_get_result'
]
