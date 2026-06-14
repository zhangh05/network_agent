"""Real pdf tools — v2.1.1 split. Wrappers defined here have co_filename in this file."""
_IMPORTED = False
_HANDLERS = {}

def _lazy_import():
    global _IMPORTED, _HANDLERS
    if _IMPORTED: return
    import tool_runtime.general_tools_base as _b
    _HANDLERS["handle_pdf_extract_text"] = _b.handle_pdf_extract_text
    _IMPORTED = True

def handle_pdf_extract_text(*args, **kwargs):
    _lazy_import()
    return _HANDLERS["handle_pdf_extract_text"](*args, **kwargs)

__all__ = ['handle_pdf_extract_text']