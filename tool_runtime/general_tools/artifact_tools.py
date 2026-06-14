"""Real artifact tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_artifact_search"] = _b.handle_artifact_search
    _HANDLERS["handle_artifact_read_content_safe"] = _b.handle_artifact_read_content_safe
    _HANDLERS["handle_artifact_save_result"] = _b.handle_artifact_save_result
    _HANDLERS["handle_artifact_tag"] = _b.handle_artifact_tag
    _HANDLERS["handle_artifact_delete_soft"] = _b.handle_artifact_delete_soft
    _IMPORTED = True

def handle_artifact_search(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_artifact_search"](*args, **kwargs)

def handle_artifact_read_content_safe(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_artifact_read_content_safe"](*args, **kwargs)

def handle_artifact_save_result(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_artifact_save_result"](*args, **kwargs)

def handle_artifact_tag(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_artifact_tag"](*args, **kwargs)

def handle_artifact_delete_soft(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_artifact_delete_soft"](*args, **kwargs)

__all__ = ['handle_artifact_search', 'handle_artifact_read_content_safe', 'handle_artifact_save_result', 'handle_artifact_tag', 'handle_artifact_delete_soft']