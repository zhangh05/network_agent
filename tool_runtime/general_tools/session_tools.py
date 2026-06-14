"""Real session tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_session_list"] = _b.handle_session_list
    _HANDLERS["handle_session_get_summary"] = _b.handle_session_get_summary
    _HANDLERS["handle_session_create"] = _b.handle_session_create
    _HANDLERS["handle_session_archive"] = _b.handle_session_archive
    _HANDLERS["handle_run_list_recent"] = _b.handle_run_list_recent
    _HANDLERS["handle_run_get_summary"] = _b.handle_run_get_summary
    _HANDLERS["handle_session_snapshot"] = _b.handle_session_snapshot
    _HANDLERS["handle_session_list_snapshots"] = _b.handle_session_list_snapshots
    _HANDLERS["handle_session_rewind"] = _b.handle_session_rewind
    _HANDLERS["handle_session_checkpoint"] = _b.handle_session_checkpoint
    _HANDLERS["handle_session_export"] = _b.handle_session_export
    _IMPORTED = True

def handle_session_list(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_list"](*args, **kwargs)

def handle_session_get_summary(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_get_summary"](*args, **kwargs)

def handle_session_create(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_create"](*args, **kwargs)

def handle_session_archive(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_archive"](*args, **kwargs)

def handle_run_list_recent(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_run_list_recent"](*args, **kwargs)

def handle_run_get_summary(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_run_get_summary"](*args, **kwargs)

def handle_session_snapshot(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_snapshot"](*args, **kwargs)

def handle_session_list_snapshots(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_list_snapshots"](*args, **kwargs)

def handle_session_rewind(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_rewind"](*args, **kwargs)

def handle_session_checkpoint(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_checkpoint"](*args, **kwargs)

def handle_session_export(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_session_export"](*args, **kwargs)

__all__ = ['handle_session_list', 'handle_session_get_summary', 'handle_session_create', 'handle_session_archive', 'handle_run_list_recent', 'handle_run_get_summary', 'handle_session_snapshot', 'handle_session_list_snapshots', 'handle_session_rewind', 'handle_session_checkpoint', 'handle_session_export']