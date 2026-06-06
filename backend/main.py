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

from flask import Flask, send_from_directory

from backend.api.version import get_version
from backend.api.modules_translate import handle_module_translate
from backend.api.agent import handle_agent_run
from backend.api.skills import handle_skills, get_skill_count
from backend.api.workspace import handle_workspace_status
from backend.api.modules import handle_modules, handle_module_status
from backend.api.memory import handle_memory_status, handle_memory_write, handle_memory_search
from backend.core.settings import UNIFIED_PORT, API_MODE, BUILD_COMMIT, TRANSLATOR_ENTRY
from backend.core.paths import FRONTEND_DIR


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["PORT"] = UNIFIED_PORT

    # ── Health ──
    @app.route("/api/health")
    def api_health():
        return {
            "status": "ok",
            "api_mode": API_MODE,
            "skills_loaded": get_skill_count(),
        }

    # ── Version ──
    @app.route("/api/version")
    def api_version():
        return get_version()

    # ── Skills ──
    @app.route("/api/skills")
    def api_skills():
        return handle_skills()

    # ── Agent Run ──
    @app.route("/api/agent/run", methods=["POST"])
    def api_agent_run():
        return handle_agent_run()

    # ── Workspace ──
    @app.route("/api/workspace/status")
    def api_workspace_status():
        return handle_workspace_status()

    # ── Modules ──
    @app.route("/api/modules")
    def api_modules():
        return handle_modules()

    @app.route("/api/modules/<module_name>/status")
    def api_module_status(module_name):
        return handle_module_status(module_name)

    # ── Module: config-translation (sole translate API) ──
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

    # ── Frontend ──
    @app.route("/")
    @app.route("/<path:filename>")
    def serve_frontend(filename="index.html"):
        if "." in filename:
            return send_from_directory(str(FRONTEND_DIR), filename)
        return send_from_directory(str(FRONTEND_DIR), "index.html")

    return app


app = create_app()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Network Agent — Unified Backend")
    parser.add_argument("--port", type=int, default=UNIFIED_PORT, help="Port to listen on (default: 8010)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    args = parser.parse_args()

    port = args.port
    app.config["PORT"] = port

    print(f"Network Agent running on http://{args.host}:{port}")
    print(f"  API mode: {API_MODE}")
    print(f"  Build: {BUILD_COMMIT}")
    print(f"  Translator entry: {TRANSLATOR_ENTRY}")
    app.run(host=args.host, port=port, debug=False)


if __name__ == "__main__":
    main()
