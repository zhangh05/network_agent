"""Real memory tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_memory_search"] = _b.handle_memory_search
    _HANDLERS["handle_memory_create"] = _b.handle_memory_create
    _HANDLERS["handle_memory_list"] = _b.handle_memory_list
    _HANDLERS["handle_memory_confirm"] = _b.handle_memory_confirm
    _HANDLERS["handle_memory_get_profile"] = _b.handle_memory_get_profile
    _HANDLERS["handle_memory_set_profile"] = _b.handle_memory_set_profile
    _HANDLERS["handle_memory_update"] = _b.handle_memory_update
    _HANDLERS["handle_memory_delete_soft"] = _b.handle_memory_delete_soft
    _IMPORTED = True

def handle_memory_search(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_memory_search"](*args, **kwargs)

def handle_memory_create(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_memory_create"](*args, **kwargs)

def handle_memory_list(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_memory_list"](*args, **kwargs)

def handle_memory_confirm(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_memory_confirm"](*args, **kwargs)

def handle_memory_get_profile(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_memory_get_profile"](*args, **kwargs)

def handle_memory_set_profile(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_memory_set_profile"](*args, **kwargs)

def handle_memory_update(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_memory_update"](*args, **kwargs)

def handle_memory_delete_soft(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_memory_delete_soft"](*args, **kwargs)

__all__ = ['handle_memory_search', 'handle_memory_create', 'handle_memory_list', 'handle_memory_confirm', 'handle_memory_get_profile', 'handle_memory_set_profile', 'handle_memory_update', 'handle_memory_delete_soft']