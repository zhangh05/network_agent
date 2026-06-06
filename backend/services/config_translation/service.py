# backend/services/config_translation/service.py
"""Compatibility shim — forwards to modules/config_translation/backend/service.py.

This file exists only for backward compatibility.
The canonical implementation lives at modules/config_translation/backend/service.py.
"""

from modules.config_translation.backend.service import translate_config  # noqa: F401

# Re-export for old import paths
__all__ = ["translate_config"]
