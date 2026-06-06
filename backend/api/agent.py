# backend/api/agent.py

import json
import urllib.request
import urllib.error

from flask import request, jsonify, current_app

from backend.core.settings import BUILD_COMMIT, TRANSLATOR_ENTRY


def handle_agent_run():
    data = request.get_json(silent=True) or {}
    intent = (data.get("intent") or "").strip()
    payload = data.get("payload", data)

    if intent != "translate_config":
        return jsonify({
            "ok": False,
            "error": f"unsupported intent: {intent or 'empty'}",
            "supported_intents": ["translate_config"],
        }), 400

    source_config = (payload.get("source_config") or "").strip()
    if not source_config:
        return jsonify({"ok": False, "error": "source_config is required"}), 400

    # Call our own /api/translate endpoint
    translator_url = "http://127.0.0.1:{port}/api/translate".format(
        port=current_app.config.get("PORT", 8010)
    )

    req_data = json.dumps({
        "source_config": source_config,
        "source_vendor": payload.get("source_vendor", "auto"),
        "target_vendor": payload.get("target_vendor", "huawei"),
    }).encode("utf-8")

    req = urllib.request.Request(
        translator_url, data=req_data,
        headers={"Content-Type": "application/json"}, method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return jsonify({"ok": False, "error": f"translate call failed: {exc}"}), 502
    except urllib.error.HTTPError as e:
        result = json.loads(e.read().decode("utf-8"))

    return jsonify({
        "ok": True,
        "intent": "translate_config",
        "skill_used": "config_translation",
        "result": result,
        "build_commit": BUILD_COMMIT,
        "translator_entry": TRANSLATOR_ENTRY,
    })
