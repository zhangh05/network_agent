# backend/api/modules_translate.py
"""Module-specific config translation API.

Endpoint: POST /api/modules/config-translation/translate
Canonical implementation: modules/config_translation/backend/service.py
"""

import logging

from flask import request, jsonify

from backend.core.limits import source_config_too_large
from modules.config_translation.backend.schemas import TranslateRequest
from modules.config_translation.backend.service import translate_config
from workspace.ids import validate_workspace_id

logger = logging.getLogger(__name__)


def handle_module_translate():
    """Handle POST /api/modules/config-translation/translate."""
    data = request.get_json(silent=True) or {}

    ws_id = data.get("workspace_id", "")
    if ws_id:
        try:
            ws_id = validate_workspace_id(ws_id)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400

    source_config = (data.get("source_config") or data.get("config_text") or "").strip()
    if not source_config:
        return jsonify({"ok": False, "error": "source_config is required"}), 400
    if source_config_too_large(source_config):
        return jsonify({"ok": False, "error": "source_config_too_large"}), 413

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
        logger.error("translate_config failed: %s", exc, exc_info=True)
        return jsonify({"ok": False, "error": "translate_config failed"}), 500

    return jsonify({
        "ok": True,
        **result.as_dict(),
    })
