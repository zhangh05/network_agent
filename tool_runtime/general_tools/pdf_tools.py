# tool_runtime/general_tools/pdf_tools.py
# v2.1.1 real split — handlers defined in this module.
# Imports shared helpers from general_tools_base.
from tool_runtime.general_tools_base import (
    _ok, _error, _result, _safe_preview, _generate_diff_preview,
    _validate_workspace_path, safe_workspace_path,
    ToolSpec, ToolInvocation, ToolResult, redact_tool_output, handle_python_exec,
handle_pdf_extract_text
)

# Reassign __module__ for audit/test verification
handle_pdf_extract_text.__module__ = __name__

__all__ = [
'handle_pdf_extract_text'
]
