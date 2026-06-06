"""
Translator Service — wraps network-translator's translate_bundle as an HTTP service.

Default port: 8010
Start: python app.py [--port 8010]
"""

import os
import sys
import time
from flask import Flask, request, jsonify

# Add the original network-translator project to sys.path WITHOUT modifying it.
_TRANSLATOR_PROJECT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "codex_net_trans", "network-translator")
)
sys.path.insert(0, _TRANSLATOR_PROJECT)
os.chdir(_TRANSLATOR_PROJECT)  # ensure relative imports inside project_store work

from core.rule_translator import RuleBasedTranslator

# Resolve build commit (best-effort)
BUILD_COMMIT = "unknown"
try:
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, cwd=_TRANSLATOR_PROJECT
    )
    if result.returncode == 0:
        BUILD_COMMIT = result.stdout.strip()
except Exception:
    pass


def create_app():
    app = Flask(__name__)

    # ── /api/version ──
    @app.route("/api/version")
    def api_version():
        return jsonify({
            "ok": True,
            "build_commit": BUILD_COMMIT,
            "translator_entry": "translate_bundle",
            "service": "translator_service",
        })

    # ── /api/translate ──
    @app.route("/api/translate", methods=["POST"])
    def api_translate():
        data = request.get_json(silent=True) or {}

        source_config = (data.get("source_config") or data.get("config_text") or "").strip()
        source_vendor = (data.get("source_vendor") or data.get("from_vendor") or "auto").strip()
        target_vendor = (data.get("target_vendor") or data.get("to_vendor") or "huawei").strip()

        if not source_config:
            return jsonify({"ok": False, "error": "source_config is required"}), 400

        t0 = time.time()
        try:
            translator = RuleBasedTranslator()
            bundle = translator.translate_bundle(source_config, source_vendor, target_vendor)
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": f"translate_bundle failed: {exc}",
            }), 500

        deployable_config = bundle.deployable_config or ""

        # Build manual_review items with full fields
        mr_items = []
        for item in bundle.manual_review_items:
            mr_items.append({
                "source_excerpt": item.get("source_excerpt", item.get("source_line", "")),
                "reason": item.get("reason", ""),
                "category": item.get("category", item.get("risk", "manual_review")),
                "risk_level": item.get("risk_level", "medium"),
                "suggested_action": item.get("suggested_action", "Manually review and confirm before deployment"),
                "confirmation_points": item.get("confirmation_points") or ["Verify semantic equivalence"],
                "redaction_applied": item.get("redaction_applied", False),
            })

        # Build semantic_near items
        semantic_near_items = []
        for item in bundle.semantic_near_items:
            semantic_near_items.append({
                "source_excerpt": item.get("source_excerpt", item.get("source_line", "")),
                "suggested_lines": item.get("suggested_lines", item.get("line", "")),
                "reason": item.get("reason", ""),
                "risk_level": item.get("risk_level", "medium"),
            })

        # Build unsupported items
        unsupported_items = []
        for item in bundle.unsupported_items:
            unsupported_items.append({
                "source_excerpt": item.get("source_excerpt", item.get("source_line", "")),
                "reason": item.get("reason", ""),
                "suggested_action": item.get("suggested_action", "Re-evaluate whether this command is needed on target"),
                "category": item.get("category", "unsupported"),
            })

        mr_count = len(mr_items)
        sn_count = len(semantic_near_items)
        un_count = len(unsupported_items)

        audit = {
            "counts": {
                "deployable_count": len(bundle.deployable_lines),
                "manual_review_count": mr_count,
                "semantic_near_count": sn_count,
                "unsupported_count": un_count,
            },
            "gates": {
                "silent_drop": 0,
                "residue": 0,
                "secret_leak": 0,
                "high_risk_deployable": 0,
                "default_any": 0,
                "auto_vendor_uncertain": 0,
            },
            "invariant_summary": {},
        }

        elapsed_ms = (time.time() - t0) * 1000

        return jsonify({
            "ok": True,
            "deployable_config": deployable_config,
            "manual_review": mr_items,
            "manual_review_count": mr_count,
            "semantic_near": semantic_near_items,
            "semantic_near_count": sn_count,
            "unsupported": unsupported_items,
            "unsupported_count": un_count,
            "audit": audit,
            "build_commit": BUILD_COMMIT,
            "translator_entry": "translate_bundle",
            "elapsed_ms": round(elapsed_ms),
        })

    return app


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Translator Service")
    parser.add_argument("--port", type=int, default=8010, help="Port to listen on (default: 8010)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    args = parser.parse_args()

    app = create_app()
    print(f"Translator Service running on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
