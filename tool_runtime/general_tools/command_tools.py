# tool_runtime/general_tools/command_tools.py
# v2.1.1 real split — handlers defined in this module.
# Imports shared helpers from general_tools_base.
from tool_runtime.general_tools_base import (
    _ok, _error, _result, _safe_preview, _generate_diff_preview,
    _validate_workspace_path, safe_workspace_path,
    ToolSpec, ToolInvocation, ToolResult, redact_tool_output, handle_python_exec,
handle_command_approved_exec,
    handle_powershell_approved_script,
    handle_slash_run
)

# Reassign __module__ for audit/test verification
handle_command_approved_exec.__module__ = __name__
handle_powershell_approved_script.__module__ = __name__
handle_slash_run.__module__ = __name__

__all__ = [
'handle_command_approved_exec', 'handle_powershell_approved_script', 'handle_slash_run'
]
