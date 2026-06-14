"""Real command tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_command_approved_exec"] = _b.handle_command_approved_exec
    _HANDLERS["handle_powershell_approved_script"] = _b.handle_powershell_approved_script
    _HANDLERS["handle_slash_run"] = _b.handle_slash_run
    _HANDLERS["handle_python_exec"] = _b.handle_python_exec
    _IMPORTED = True

def handle_command_approved_exec(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_command_approved_exec"](*args, **kwargs)

def handle_powershell_approved_script(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_powershell_approved_script"](*args, **kwargs)

def handle_slash_run(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_slash_run"](*args, **kwargs)

def handle_python_exec(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_python_exec"](*args, **kwargs)

__all__ = ['handle_command_approved_exec', 'handle_powershell_approved_script', 'handle_slash_run', 'handle_python_exec']