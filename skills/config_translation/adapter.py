# skills/config_translation/adapter.py
"""Adapter for config_translation skill — calls module service directly.

No HTTP. No legacy translate API. No external dependency.
Calls modules.config_translation.backend.service.translate_config.
"""

from modules.config_translation.backend.schemas import TranslateRequest
from modules.config_translation.backend.service import translate_config


def translate(
    source_config: str,
    source_vendor: str = "auto",
    target_vendor: str = "huawei",
) -> dict:
    """Translate using the embedded config_translation module.

    Returns a dict with keys: ok, deployable_config, manual_review, audit, etc.
    """
    req = TranslateRequest(
        source_config=source_config,
        source_vendor=source_vendor,
        target_vendor=target_vendor,
    )
    try:
        result = translate_config(req)
        return {"ok": True, **result.as_dict()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
