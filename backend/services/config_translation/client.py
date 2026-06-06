# backend/services/config_translation/client.py
"""Compatibility shim — forwards to modules/config_translation/backend/client.py.

The canonical client lives at modules/config_translation/backend/client.py.
"""

from modules.config_translation.backend.client import request_translate  # noqa: F401

__all__ = ["request_translate"]
