# backend/main.py
"""
Network Agent — unified backend entry point.

Start:
    python backend/main.py --port 8010
or:
    python -m backend.main --port 8010
"""

import sys
from pathlib import Path

# Ensure backend package is importable
_NETWORK_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_NETWORK_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_NETWORK_AGENT_DIR))

from flask import Flask, send_from_directory, jsonify, request

from backend.api.version import get_version
from backend.api.modules_translate import handle_module_translate
from backend.api.llm_api import (
    handle_llm_status, handle_llm_test,
    handle_llm_config_get, handle_llm_config_post, handle_llm_config_delete,
    handle_providers_list, handle_provider_get, handle_provider_save,
    handle_provider_delete, handle_llm_activate,
)
from backend.api.skills import handle_skills
from backend.api.modules import handle_modules, handle_module_status, handle_registry_status, handle_capabilities
from backend.api.memory import handle_memory_status, handle_memory_write, handle_memory_search
from backend.api.memory_routes import handle_memory_confirm, handle_memory_delete, handle_memory_list
from backend.api.session_routes import (
    handle_session_create, handle_session_list,
    handle_session_detail, handle_session_update,
    handle_session_archive,
    handle_session_restore, handle_session_soft_delete,
    handle_session_delete_permanently,
    handle_session_messages, handle_session_default,
)
from backend.api.artifact_routes import register_artifact_routes
from backend.api.job_routes import register_job_routes
from backend.api.runtime_routes import register_runtime_routes
from backend.api.context_routes import register_context_routes
from backend.api.workspace_routes import register_workspace_routes
from backend.api.knowledge_routes import register_knowledge_routes
from backend.api.review_routes import register_review_routes
from backend.api.pcap_routes import register_pcap_routes
from backend.api.reference_routes import register_reference_routes
from backend.api.workspace_status_routes import register_workspace_status_routes
from backend.api.decision_routes import register_decision_routes
from backend.api.remote_routes import register_remote_routes
from backend.api.cmdb_routes import register_cmdb_routes
from backend.core.settings import UNIFIED_PORT, API_MODE, BUILD_COMMIT, TRANSLATOR_ENTRY
from backend.core.paths import FRONTEND_DIR
from backend.core.rate_limit import rate_limit_middleware
from workspace.ids import validate_workspace_id


def _invalid_workspace_response():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_workspace_id(raw="default"):
    try:
        return validate_workspace_id(raw or "default"), None
    except ValueError:
        return None, _invalid_workspace_response()


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["PORT"] = UNIFIED_PORT

    # ── v3.0.0: Register default security hooks ──
    try:
        from agent.runtime.default_hooks import register_default_hooks
        register_default_hooks()
    except Exception:
        pass

    # ── Rate limiting (before all routes) ──
    rate_limit_middleware(app)

    # ── Health ──
    @app.route("/api/health")
    def api_health():
        from backend.core.responses import ok_response
        from agent.capabilities.builtin import get_default_capability_registry
        body, _ = ok_response({
            "status": "ok",
            "api_mode": API_MODE,
            "capabilities_loaded": len(get_default_capability_registry().list_all()),
        })
        return jsonify(body)

    # ── Version ──
    @app.route("/api/version")
    def api_version():
        return get_version()

    # ── Skills ──
    @app.route("/api/skills")
    def api_skills():
        return handle_skills()

    # ── Agent —唯一主入口 ──
    @app.route("/api/agent/message", methods=["POST"])
    def api_agent_message():
        """POST /api/agent/message — v2.1.1 unified entry point."""
        from backend.api.agent_routes import agent_message
        return agent_message()

    @app.route("/api/agent/status")
    def api_agent_status():
        from backend.api.agent_status import handle_agent_status
        return handle_agent_status()

    # ── Sessions ──
    @app.route("/api/sessions", methods=["POST"])
    def api_sessions_create():
        return handle_session_create()

    @app.route("/api/sessions")
    def api_sessions_list():
        return handle_session_list()

    @app.route("/api/sessions/default")
    def api_session_default():
        return handle_session_default()

    @app.route("/api/sessions/<session_id>")
    def api_session_detail(session_id):
        return handle_session_detail(session_id)

    @app.route("/api/sessions/<session_id>", methods=["PUT"])
    def api_session_update(session_id):
        return handle_session_update(session_id)

    @app.route("/api/sessions/<session_id>/archive", methods=["POST"])
    def api_session_archive(session_id):
        return handle_session_archive(session_id)

    @app.route("/api/sessions/<session_id>/restore", methods=["POST"])
    def api_session_restore(session_id):
        return handle_session_restore(session_id)

    @app.route("/api/sessions/<session_id>/soft-delete", methods=["POST"])
    def api_session_soft_delete(session_id):
        return handle_session_soft_delete(session_id)

    @app.route("/api/sessions/<session_id>", methods=["DELETE"])
    def api_session_delete_permanently(session_id):
        return handle_session_delete_permanently(session_id)

    @app.route("/api/sessions/<session_id>/messages")
    def api_session_messages(session_id):
        return handle_session_messages(session_id)

    # ── LLM ──
    @app.route("/api/agent/llm/status")
    def api_agent_llm_status():
        return handle_llm_status()

    @app.route("/api/agent/llm/test", methods=["POST"])
    def api_agent_llm_test():
        return handle_llm_test()

    @app.route("/api/agent/llm/config")
    def api_agent_llm_config_get():
        return handle_llm_config_get()

    @app.route("/api/agent/llm/config", methods=["POST"])
    def api_agent_llm_config_post():
        return handle_llm_config_post()

    @app.route("/api/agent/llm/config", methods=["DELETE"])
    def api_agent_llm_config_delete():
        return handle_llm_config_delete()

    # ── LLM Providers (per-provider configs) ──

    @app.route("/api/agent/llm/providers")
    def api_llm_providers_list():
        return handle_providers_list()

    @app.route("/api/agent/llm/providers/<provider_id>")
    def api_llm_provider_get(provider_id):
        return handle_provider_get(provider_id)

    @app.route("/api/agent/llm/providers/<provider_id>", methods=["POST"])
    def api_llm_provider_save(provider_id):
        return handle_provider_save(provider_id)

    @app.route("/api/agent/llm/providers/<provider_id>", methods=["DELETE"])
    def api_llm_provider_delete(provider_id):
        return handle_provider_delete(provider_id)

    @app.route("/api/agent/llm/activate", methods=["POST"])
    def api_llm_activate():
        return handle_llm_activate()

    # ── Modules ──
    @app.route("/api/modules")
    def api_modules():
        return handle_modules()

    @app.route("/api/modules/<module_name>/status")
    def api_module_status(module_name):
        return handle_module_status(module_name)

    # ── Registry ──
    @app.route("/api/capabilities")
    def api_capabilities():
        return handle_capabilities()

    @app.route("/api/registry/status")
    def api_registry_status():
        return handle_registry_status()

    @app.route("/api/registry/reload", methods=["POST"])
    def api_registry_reload():
        from registry.loader import reload_all
        reload_all()
        return jsonify({"ok": True, **handle_registry_status().json})

    # ── Module: config-translation ──
    @app.route("/api/modules/config-translation/translate", methods=["POST"])
    def api_module_config_translate():
        return handle_module_translate()

    # ── Memory ──
    @app.route("/api/memory/status")
    def api_memory_status():
        return handle_memory_status()

    @app.route("/api/memory/write", methods=["POST"])
    def api_memory_write():
        return handle_memory_write()

    @app.route("/api/memory/search", methods=["POST"])
    def api_memory_search():
        return handle_memory_search()

    @app.route("/api/memory/list")
    def api_memory_list():
        return handle_memory_list()

    @app.route("/api/memory/confirm", methods=["POST"])
    def api_memory_confirm():
        return handle_memory_confirm()

    @app.route("/api/memory/<memory_id>", methods=["DELETE"])
    def api_memory_delete(memory_id):
        return handle_memory_delete(memory_id)

    # ── Sub-route registrations ──
    register_runtime_routes(app)      # /api/runtime/*, /api/workspaces/<ws>/selfcheck, retention, archive
    register_workspace_routes(app)    # /api/workspaces, /api/runs/*, /api/*/trace, /api/*/reports
    register_artifact_routes(app)     # /api/workspaces/<ws>/artifacts/*
    register_job_routes(app)          # /api/jobs/*
    register_context_routes(app)      # /api/context/*, /api/prompts/*, /api/harness/*
    register_knowledge_routes(app)    # /api/knowledge/* (sources, search, chunks)
    register_review_routes(app)       # /api/review-items/*, /api/workspaces/<ws>/review-items
    register_pcap_routes(app)        # /api/pcap/* (parse, filter, align)
    register_reference_routes(app)   # /api/workspaces/<ws>/files/<fid>/references, reference-graph
    register_workspace_status_routes(app)  # /api/workspaces/<ws>/status, /storage/health
    register_decision_routes(app)    # /api/workspaces/<ws>/runs/<run_id>/decision
    register_remote_routes(app)     # /api/remote/* (SSH/Telnet)
    register_cmdb_routes(app)      # /api/cmdb/* (Device Assets)

    # ── WebSocket routes (real-time streaming) ──
    from backend.ws.agent_ws import register_ws_routes
    register_ws_routes(app)
    from backend.ws.remote_ws import register_remote_ws
    register_remote_ws(app)

    # ── Tool approval routes ──
    from backend.api.approval_routes import register_approval_routes
    register_approval_routes(app)

    # ── Usage endpoint ──
    @app.route("/api/agent/usage")
    def api_agent_usage():
        from flask import request, jsonify
        from agent.runtime.token_tracker import get_usage
        ws_id = request.args.get("workspace_id", "default")
        sid = request.args.get("session_id", "")
        return jsonify(get_usage(ws_id, sid))

    # ── Auth middleware (after all routes registered) ──
    from backend.core.auth import register_auth_middleware
    register_auth_middleware(app)

    # ── Frontend ──
    # Allowed frontend file extensions (prevent serving non-frontend files)
    _ALLOWED_STATIC_EXTENSIONS = frozenset({
        ".html", ".js", ".css", ".json", ".svg", ".png", ".ico",
        ".jpg", ".jpeg", ".gif", ".woff", ".woff2", ".ttf", ".txt",
    })

    @app.route("/")
    @app.route("/<path:filename>")
    def serve_frontend(filename="index.html"):
        from flask import make_response
        # Security: only serve known frontend file types
        if filename != "index.html":
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in _ALLOWED_STATIC_EXTENSIONS:
                # Unknown extension — serve index.html for SPA routing
                filename = "index.html"
        try:
            resp = make_response(send_from_directory(str(FRONTEND_DIR), filename))
        except Exception:
            resp = make_response(send_from_directory(str(FRONTEND_DIR), "index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        # Prevent 304 conditional responses — force full re-download every time
        resp.headers.pop("Last-Modified", None)
        resp.headers.pop("ETag", None)
        return resp

    return app


app = create_app()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Network Agent — Unified Backend")
    parser.add_argument("--port", type=int, default=UNIFIED_PORT, help="Port to listen on (default: 8010)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    port = args.port
    app.config["PORT"] = port

    print(f"Network Agent running on http://{args.host}:{port}")
    print(f"  API mode: {API_MODE}")
    print(f"  Build: {BUILD_COMMIT}")
    print(f"  Translator entry: {TRANSLATOR_ENTRY}")

    # Signal handler: cleanup SSH/browser sessions on shutdown
    import signal
    def _graceful_shutdown(signum, frame):
        print("Shutting down gracefully...")
        try:
            from agent.modules.remote.core import _SESSIONS, _SESSIONS_LOCK
            with _SESSIONS_LOCK:
                for sid in list(_SESSIONS.keys()):
                    try:
                        _SESSIONS[sid].close()
                    except Exception:
                        pass
                _SESSIONS.clear()
            print(f"All remote sessions closed.")
        except Exception as e:
            print(f"Cleanup warning: {e}")
        import sys
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    app.run(host=args.host, port=port, debug=False)


if __name__ == "__main__":
    main()
