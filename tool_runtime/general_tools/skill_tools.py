"""Real skill tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_skill_list"] = _b.handle_skill_list
    _HANDLERS["handle_skill_request_load"] = _b.handle_skill_request_load
    _HANDLERS["handle_skill_load"] = _b.handle_skill_load
    _HANDLERS["handle_skill_find"] = _b.handle_skill_find
    _HANDLERS["handle_skill_create"] = _b.handle_skill_create
    _HANDLERS["handle_skill_inspect"] = _b.handle_skill_inspect
    _IMPORTED = True

def handle_skill_list(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_skill_list"](*args, **kwargs)

def handle_skill_request_load(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_skill_request_load"](*args, **kwargs)

def handle_skill_load(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_skill_load"](*args, **kwargs)

def handle_skill_find(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_skill_find"](*args, **kwargs)

def handle_skill_create(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_skill_create"](*args, **kwargs)

def handle_skill_inspect(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_skill_inspect"](*args, **kwargs)

__all__ = ['handle_skill_list', 'handle_skill_request_load', 'handle_skill_load', 'handle_skill_find', 'handle_skill_create', 'handle_skill_inspect']