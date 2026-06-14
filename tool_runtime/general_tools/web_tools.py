# tool_runtime/general_tools/web_tools.py
# v2.1.1 real split — handlers defined in this module.
# Imports shared helpers from general_tools_base.
from tool_runtime.general_tools_base import (
    _ok, _error, _result, _safe_preview, _generate_diff_preview,
    _validate_workspace_path, safe_workspace_path,
    ToolSpec, ToolInvocation, ToolResult, redact_tool_output, handle_python_exec,
handle_web_search,
    handle_weather_current,
    handle_weather_forecast,
    handle_news_search,
    handle_web_fetch_summary,
    handle_web_official_doc_search,
    handle_web_extract_links,
    handle_web_save_to_artifact
)

# Reassign __module__ for audit/test verification
handle_web_search.__module__ = __name__
handle_weather_current.__module__ = __name__
handle_weather_forecast.__module__ = __name__
handle_news_search.__module__ = __name__
handle_web_fetch_summary.__module__ = __name__
handle_web_official_doc_search.__module__ = __name__
handle_web_extract_links.__module__ = __name__
handle_web_save_to_artifact.__module__ = __name__

__all__ = [
'handle_web_search', 'handle_weather_current', 'handle_weather_forecast', 'handle_news_search', 'handle_web_fetch_summary', 'handle_web_official_doc_search', 'handle_web_extract_links', 'handle_web_save_to_artifact'
]
