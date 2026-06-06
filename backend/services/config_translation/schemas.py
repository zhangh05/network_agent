# backend/services/config_translation/schemas.py
"""Compatibility shim — forwards to modules/config_translation/backend/schemas.py.

The canonical schemas live at modules/config_translation/backend/schemas.py.
"""

from modules.config_translation.backend.schemas import (  # noqa: F401
    TranslateRequest,
    TranslateResponse,
)

__all__ = ["TranslateRequest", "TranslateResponse"]
