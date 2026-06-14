"""Real file tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_file_list"] = _b.handle_file_list
    _HANDLERS["handle_file_exists"] = _b.handle_file_exists
    _HANDLERS["handle_file_read"] = _b.handle_file_read
    _HANDLERS["handle_file_edit"] = _b.handle_file_edit
    _HANDLERS["handle_file_patch"] = _b.handle_file_patch
    _HANDLERS["handle_ws_list_files"] = _b.handle_ws_list_files
    _HANDLERS["handle_ws_read_text_preview"] = _b.handle_ws_read_text_preview
    _HANDLERS["handle_ws_write_artifact_file"] = _b.handle_ws_write_artifact_file
    _HANDLERS["handle_ws_path_exists"] = _b.handle_ws_path_exists
    _HANDLERS["handle_ws_get_metadata"] = _b.handle_ws_get_metadata
    _IMPORTED = True

def handle_file_list(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_file_list"](*args, **kwargs)

def handle_file_exists(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_file_exists"](*args, **kwargs)

def handle_file_read(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_file_read"](*args, **kwargs)

def handle_file_edit(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_file_edit"](*args, **kwargs)

def handle_file_patch(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_file_patch"](*args, **kwargs)

def handle_ws_list_files(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_ws_list_files"](*args, **kwargs)

def handle_ws_read_text_preview(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_ws_read_text_preview"](*args, **kwargs)

def handle_ws_write_artifact_file(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_ws_write_artifact_file"](*args, **kwargs)

def handle_ws_path_exists(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_ws_path_exists"](*args, **kwargs)

def handle_ws_get_metadata(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_ws_get_metadata"](*args, **kwargs)

__all__ = ['handle_file_list', 'handle_file_exists', 'handle_file_read', 'handle_file_edit', 'handle_file_patch', 'handle_ws_list_files', 'handle_ws_read_text_preview', 'handle_ws_write_artifact_file', 'handle_ws_path_exists', 'handle_ws_get_metadata']