"""Real agent tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_agent_spawn"] = _b.handle_agent_spawn
    _HANDLERS["handle_agent_list_roles"] = _b.handle_agent_list_roles
    _HANDLERS["handle_agent_team"] = _b.handle_agent_team
    _HANDLERS["handle_agent_get_result"] = _b.handle_agent_get_result
    _IMPORTED = True

def handle_agent_spawn(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_agent_spawn"](*args, **kwargs)

def handle_agent_list_roles(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_agent_list_roles"](*args, **kwargs)

def handle_agent_team(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_agent_team"](*args, **kwargs)

def handle_agent_get_result(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_agent_get_result"](*args, **kwargs)

__all__ = ['handle_agent_spawn', 'handle_agent_list_roles', 'handle_agent_team', 'handle_agent_get_result']