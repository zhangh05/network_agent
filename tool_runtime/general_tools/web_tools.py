"""Real web tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_web_search"] = _b.handle_web_search
    _HANDLERS["handle_weather_current"] = _b.handle_weather_current
    _HANDLERS["handle_weather_forecast"] = _b.handle_weather_forecast
    _HANDLERS["handle_news_search"] = _b.handle_news_search
    _HANDLERS["handle_web_fetch_summary"] = _b.handle_web_fetch_summary
    _HANDLERS["handle_web_official_doc_search"] = _b.handle_web_official_doc_search
    _HANDLERS["handle_web_extract_links"] = _b.handle_web_extract_links
    _HANDLERS["handle_web_save_to_artifact"] = _b.handle_web_save_to_artifact
    _IMPORTED = True

def handle_web_search(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_web_search"](*args, **kwargs)

def handle_weather_current(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_weather_current"](*args, **kwargs)

def handle_weather_forecast(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_weather_forecast"](*args, **kwargs)

def handle_news_search(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_news_search"](*args, **kwargs)

def handle_web_fetch_summary(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_web_fetch_summary"](*args, **kwargs)

def handle_web_official_doc_search(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_web_official_doc_search"](*args, **kwargs)

def handle_web_extract_links(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_web_extract_links"](*args, **kwargs)

def handle_web_save_to_artifact(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_web_save_to_artifact"](*args, **kwargs)

__all__ = ['handle_web_search', 'handle_weather_current', 'handle_weather_forecast', 'handle_news_search', 'handle_web_fetch_summary', 'handle_web_official_doc_search', 'handle_web_extract_links', 'handle_web_save_to_artifact']