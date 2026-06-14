# tool_runtime/general_tools/web_tools.py
"""Web tools — search, weather, news, fetch, extract links."""

from tool_runtime.general_tools_base import (
    handle_web_search,
    handle_weather_current,
    handle_weather_forecast,
    handle_news_search,
    handle_web_fetch_summary,
    handle_web_official_doc_search,
    handle_web_extract_links,
    handle_web_save_to_artifact,
)

__all__ = [
    "handle_web_search",
    "handle_weather_current",
    "handle_weather_forecast",
    "handle_news_search",
    "handle_web_fetch_summary",
    "handle_web_official_doc_search",
    "handle_web_extract_links",
    "handle_web_save_to_artifact",
]
