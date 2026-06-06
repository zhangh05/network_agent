# backend/api/agent.py
"""Agent run API — routes intents through skill adapters to modules."""

from flask import request, jsonify

from backend.core.settings import BUILD_COMMIT, TRANSLATOR_ENTRY


def handle_agent_run():
    data = request.get_json(silent=True) or {}
    intent = (data.get("intent") or "").strip()

    supported_intents = [
        "translate_config",
        "topology_draw",
        "inspection_analyze",
        "knowledge_search",
        "memory_search",
    ]

    if intent == "translate_config":
        return _run_translate(data)

    if intent in supported_intents:
        return jsonify({
            "ok": False,
            "error": f"Intent '{intent}' is planned but not yet implemented (coming_soon).",
            "intent": intent,
        }), 200

    return jsonify({
        "ok": False,
        "error": f"unsupported intent: {intent or 'empty'}",
        "supported_intents": supported_intents,
    }), 400


def _run_translate(data):
    source_config = (data.get("source_config") or "").strip()
    if not source_config:
        return jsonify({"ok": False, "error": "source_config is required"}), 400

    # Route through skill adapter → module service
    from skills.config_translation.adapter import translate
    result = translate(
        source_config=source_config,
        source_vendor=data.get("source_vendor", "auto"),
        target_vendor=data.get("target_vendor", "huawei"),
    )

    if result.get("ok"):
        return jsonify({
            "ok": True,
            "intent": "translate_config",
            "skill_used": "config_translation",
            "module_used": "config_translation",
            "result": result,
            "build_commit": BUILD_COMMIT,
            "translator_entry": TRANSLATOR_ENTRY,
        })
    else:
        return jsonify({
            "ok": False,
            "intent": "translate_config",
            "error": result.get("error", "translate_config failed"),
        }), 500
