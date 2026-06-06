"""
Agent Service — skill registry + agent runner.

Default port: 8020
Start: python app.py [--port 8020] [--translator-url http://127.0.0.1:8010]
"""

import os
import sys
import json
import time
from flask import Flask, request, jsonify

# Load skill registry
_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "skills")
_REGISTRY_PATH = os.path.join(_SKILLS_DIR, "registry.json")

import yaml
try:
    with open(_REGISTRY_PATH) as f:
        _SKILL_REGISTRY = json.load(f)
except Exception:
    _SKILL_REGISTRY = {"skills": [], "version": "0.1.0"}


def _find_skill(name):
    for s in _SKILL_REGISTRY.get("skills", []):
        if s.get("skill_name") == name:
            return s
    return None


def create_app():
    app = Flask(__name__)
    app.config["TRANSLATOR_URL"] = os.environ.get(
        "TRANSLATOR_SERVICE_URL", "http://127.0.0.1:8010"
    )

    # ── /health ──
    @app.route("/health")
    def health():
        return jsonify({"ok": True, "service": "agent_service"})

    # ── /skills ──
    @app.route("/skills")
    def list_skills():
        return jsonify(_SKILL_REGISTRY)

    # ── /agent/run ──
    @app.route("/agent/run", methods=["POST"])
    def agent_run():
        data = request.get_json(silent=True) or {}
        intent = (data.get("intent") or "").strip()

        if intent == "translate_config":
            return _run_config_translate(data)

        return jsonify({
            "ok": False,
            "error": f"unsupported intent: {intent or 'empty'}",
            "supported_intents": ["translate_config"],
        }), 400

    return app


def _run_config_translate(data):
    source_config = (data.get("source_config") or "").strip()
    source_vendor = (data.get("source_vendor") or "auto").strip()
    target_vendor = (data.get("target_vendor") or "huawei").strip()

    if not source_config:
        return jsonify({"ok": False, "error": "source_config is required"}), 400

    skill = _find_skill("config_translate")
    if not skill:
        return jsonify({"ok": False, "error": "config_translate skill not found in registry"}), 500

    translator_url = skill.get("endpoint", "http://127.0.0.1:8010/api/translate")

    import urllib.request
    import urllib.error

    payload = json.dumps({
        "source_config": source_config,
        "source_vendor": source_vendor,
        "target_vendor": target_vendor,
    }).encode("utf-8")

    req = urllib.request.Request(
        translator_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return jsonify({
            "ok": False,
            "error": f"translator_service unreachable: {exc}",
            "translator_url": translator_url,
        }), 502
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": f"translate call failed: {exc}",
        }), 500

    elapsed_ms = (time.time() - t0) * 1000

    return jsonify({
        "ok": True,
        "skill": "config_translate",
        "deployable_config": result.get("deployable_config", ""),
        "manual_review": result.get("manual_review", []),
        "manual_review_count": result.get("manual_review_count", 0),
        "semantic_near": result.get("semantic_near", []),
        "semantic_near_count": result.get("semantic_near_count", 0),
        "unsupported": result.get("unsupported", []),
        "unsupported_count": result.get("unsupported_count", 0),
        "audit": result.get("audit", {}),
        "build_commit": result.get("build_commit", "unknown"),
        "translator_entry": result.get("translator_entry", "translate_bundle"),
        "elapsed_ms": round(elapsed_ms),
    })


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent Service")
    parser.add_argument("--port", type=int, default=8020, help="Port to listen on (default: 8020)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument(
        "--translator-url",
        type=str,
        default="http://127.0.0.1:8010/api/translate",
        help="Translator service URL",
    )
    args = parser.parse_args()

    os.environ["TRANSLATOR_SERVICE_URL"] = args.translator_url

    app = create_app()
    print(f"Agent Service running on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
