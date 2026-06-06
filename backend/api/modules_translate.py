# backend/api/modules_translate.py
"""Module-specific config translation API.

Endpoint: POST /api/modules/config-translation/translate
Canonical implementation: modules/config_translation/backend/service.py
"""

from flask import request, jsonify

from modules.config_translation.backend.schemas import TranslateRequest
from modules.config_translation.backend.service import translate_config


def handle_module_translate():
    """Handle POST /api/modules/config-translation/translate."""
    data = request.get_json(silent=True) or {}

    source_config = (data.get("source_config") or data.get("config_text") or "").strip()
    if not source_config:
        return jsonify({"ok": False, "error": "source_config is required"}), 400

    req = TranslateRequest(
        source_config=source_config,
        source_vendor=(data.get("source_vendor") or data.get("from_vendor") or "auto").strip(),
        target_vendor=(data.get("target_vendor") or data.get("to_vendor") or "huawei").strip(),
        source_domain=(data.get("source_domain") or "auto").strip(),
        target_domain=(data.get("target_domain") or "auto").strip(),
        source_platform=(data.get("source_platform") or "auto").strip(),
        target_platform=(data.get("target_platform") or "auto").strip(),
    )

    try:
        result = translate_config(req)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"translate_config failed: {exc}"}), 500

    return jsonify({
        "ok": True,
        **result.as_dict(),
    })
