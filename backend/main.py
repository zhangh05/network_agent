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
from backend.api.agent import handle_agent_run, handle_agent_status
from backend.api.llm_api import handle_llm_status, handle_llm_test, handle_llm_config_get, handle_llm_config_post, handle_llm_config_delete
from backend.api.skills import handle_skills, get_skill_count
from backend.api.workspace import handle_workspace_status
from backend.api.modules import handle_modules, handle_module_status, handle_registry_status, handle_capabilities
from backend.api.memory import handle_memory_status, handle_memory_write, handle_memory_search
from backend.api.memory_routes import handle_memory_confirm, handle_memory_delete, handle_memory_list
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

    @app.route("/api/agent/status")
    def api_agent_status():
        return handle_agent_status()

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

    # ── Workspace ──
    @app.route("/api/workspaces")
    def api_workspaces_list():
        from workspace.manager import list_workspaces
        return jsonify({"workspaces": list_workspaces()})

    @app.route("/api/workspaces/<ws_id>/state")
    def api_workspace_state(ws_id):
        from workspace.manager import get_workspace_state
        return jsonify(get_workspace_state(ws_id))

    @app.route("/api/workspaces/<ws_id>/runs")
    def api_workspace_runs(ws_id):
        from workspace.manager import get_workspace_runs
        return jsonify({"runs": get_workspace_runs(ws_id)})

    @app.route("/api/workspaces/<ws_id>/runs/<run_id>")
    def api_workspace_run(ws_id, run_id):
        from workspace.run_store import get_run
        result = get_run(run_id, ws_id)
        if not result:
            return jsonify({"ok": False, "error": "run not found"}), 404
        return jsonify(result)

    @app.route("/api/workspaces/<ws_id>/artifacts")
    def api_workspace_artifacts(ws_id):
        from artifacts.store import list_artifacts, save_artifact, get_artifact, read_artifact_content, delete_artifact, promote_artifact, summarize_artifact_content, get_run_artifacts
        run_id = request.args.get("run_id")
        art_type = request.args.get("artifact_type")
        scope = request.args.get("scope")
        sens = request.args.get("sensitivity")
        inc_del = request.args.get("include_deleted", "0") == "1"
        lim = int(request.args.get("limit", 100))
        return jsonify({"artifacts": list_artifacts(ws_id, run_id=run_id, artifact_type=art_type,
                        scope=scope, sensitivity=sens, include_deleted=inc_del, limit=lim)})

    @app.route("/api/workspaces/<ws_id>/artifacts", methods=["POST"])
    def api_workspace_artifact_create(ws_id):
        from artifacts.store import save_artifact, sanitize_record
        data = request.get_json(silent=True) or {}
        rec = save_artifact(
            workspace_id=ws_id, content=data.get("content", ""),
            artifact_type=data.get("artifact_type", ""),
            title=data.get("title", ""), scope=data.get("scope", "workspace"),
            sensitivity=data.get("sensitivity", ""),
            run_id=data.get("run_id", ""),
        )
        if not rec:
            return jsonify({"ok": False, "error": "artifact creation blocked"}), 400
        return jsonify({"ok": True, "artifact": sanitize_record(rec)})

    @app.route("/api/workspaces/<ws_id>/artifacts/upload", methods=["POST"])
    def api_workspace_artifact_upload(ws_id):
        import re
        from artifacts.store import save_artifact, sanitize_record, _get_max_size, _get_ws_root
        max_size = _get_max_size()

        # 1. Pre-check content_length (with multipart overhead allowance)
        if request.content_length and request.content_length > max_size + 1_048_576:
            return jsonify({"ok": False, "error": "file_too_large"}), 413

        if "file" not in request.files:
            return jsonify({"ok": False, "error": "no file provided"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"ok": False, "error": "empty filename"}), 400

        # 2. Save to quarantine
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", f.filename)[:120]
        upload_dir = _get_ws_root() / ws_id / "artifacts" / "quarantine"
        upload_dir.mkdir(parents=True, exist_ok=True)
        src_path = upload_dir / safe
        f.save(str(src_path))

        # 3. Check size on disk (don't read into memory yet)
        file_size = src_path.stat().st_size
        if file_size > max_size:
            src_path.unlink()
            return jsonify({"ok": False, "error": "file_too_large"}), 413

        # 4. Read content (safe for text files within limits)
        try:
            content = src_path.read_text(errors="replace")
        except Exception:
            src_path.unlink()
            return jsonify({"ok": False, "error": "cannot read file"}), 400

        # 5. Save artifact
        rec = save_artifact(
            workspace_id=ws_id, content=content,
            artifact_type=request.form.get("artifact_type", ""),
            title=request.form.get("title", f.filename),
            scope=request.form.get("scope", "workspace"),
            sensitivity=request.form.get("sensitivity", ""),
            run_id=request.form.get("run_id", ""),
        )
        src_path.unlink()
        if not rec:
            return jsonify({"ok": False, "error": "artifact creation blocked"}), 400
        return jsonify({"ok": True, "artifact": sanitize_record(rec)})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>")
    def api_workspace_artifact(ws_id, artifact_id):
        from artifacts.store import get_artifact
        rec = get_artifact(ws_id, artifact_id)
        if not rec:
            return jsonify({"ok": False, "error": "artifact not found"}), 404
        return jsonify({"ok": True, "artifact": sanitize_record(rec)})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>/content")
    def api_artifact_content(ws_id, artifact_id):
        from artifacts.store import read_artifact_content
        allow = request.args.get("allow_sensitive", "0") == "1"
        content = read_artifact_content(ws_id, artifact_id, allow_sensitive=allow)
        if content is None:
            return jsonify({"ok": False, "error": "content not accessible"}), 403
        return jsonify({"ok": True, "content": content})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>", methods=["DELETE"])
    def api_artifact_delete(ws_id, artifact_id):
        from artifacts.store import delete_artifact
        ok = delete_artifact(ws_id, artifact_id)
        return jsonify({"ok": ok})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>/promote", methods=["POST"])
    def api_artifact_promote(ws_id, artifact_id):
        data = request.get_json(silent=True) or {}
        target = data.get("target_scope", "workspace")
        from artifacts.store import promote_artifact
        rec = promote_artifact(ws_id, artifact_id, target)
        if not rec:
            return jsonify({"ok": False, "error": "promotion blocked"}), 400
        return jsonify({"ok": True, "artifact": sanitize_record(rec)})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>/summarize")
    def api_artifact_summarize(ws_id, artifact_id):
        from artifacts.store import summarize_artifact_content
        s = summarize_artifact_content(ws_id, artifact_id)
        return jsonify({"ok": True, "summary": s})

    @app.route("/api/workspaces/<ws_id>/runs/<run_id>/artifacts")
    def api_run_artifacts(ws_id, run_id):
        from artifacts.store import get_run_artifacts
        return jsonify({"ok": True, **get_run_artifacts(ws_id, run_id)})

    # ── Trace (Observability) ──
    @app.route("/api/workspaces/<ws_id>/runs/<run_id>/trace")
    def api_workspace_trace(ws_id, run_id):
        from observability.store import get_trace
        trace = get_trace(run_id, ws_id)
        if not trace:
            return jsonify({"ok": False, "error": "trace not found"}), 404
        return jsonify({"ok": True, "trace": trace})

    @app.route("/api/workspaces/<ws_id>/traces")
    def api_workspace_traces(ws_id):
        from observability.store import list_traces
        return jsonify({"traces": list_traces(ws_id)})

    @app.route("/api/agent/runs/<run_id>/trace")
    def api_agent_run_trace(run_id):
        from observability.store import get_trace
        trace = get_trace(run_id, "default")
        if not trace:
            return jsonify({"ok": False, "error": "trace not found"}), 404
        return jsonify({"ok": True, "trace": trace})

    # ── Reports / Export ──
    @app.route("/api/reports/create", methods=["POST"])
    def api_report_create():
        data = request.get_json(silent=True) or {}
        from reports_engine.schemas import ReportRequest
        from reports_engine.service import create_report as svc_create_report
        req = ReportRequest(
            workspace_id=data.get("workspace_id", "default"),
            run_id=data.get("run_id", ""),
            report_type=data.get("report_type", "config_translation"),
            title=data.get("title", ""),
            format=data.get("format", "markdown"),
            include_deployable_config=data.get("include_deployable_config", False),
            sensitivity=data.get("sensitivity", "internal"),
        )
        result = svc_create_report(req)
        return jsonify(result.as_dict())

    @app.route("/api/workspaces/<ws_id>/runs/<run_id>/report", methods=["POST"])
    def api_workspace_run_report(ws_id, run_id):
        data = request.get_json(silent=True) or {}
        from reports_engine.service import create_config_translation_report
        result = create_config_translation_report(
            ws_id, run_id, {},
            fmt=data.get("format", "markdown"),
            include_deployable=data.get("include_deployable_config", False),
        )
        return jsonify(result.as_dict())

    @app.route("/api/workspaces/<ws_id>/reports")
    def api_workspace_reports(ws_id):
        from artifacts.store import list_artifacts
        arts = list_artifacts(ws_id, artifact_type="report")
        return jsonify({"reports": arts})

    @app.route("/api/workspaces/<ws_id>/reports/<artifact_id>/content")
    def api_report_content(ws_id, artifact_id):
        from artifacts.store import read_artifact_content
        allow = request.args.get("allow_sensitive", "0") == "1"
        content = read_artifact_content(ws_id, artifact_id, allow_sensitive=allow)
        if content is None:
            return jsonify({"ok": False, "error": "content not accessible"}), 403
        return jsonify({"ok": True, "content": content})

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

    @app.route("/api/memory/list")
    def api_memory_list():
        return handle_memory_list()

    @app.route("/api/memory/confirm", methods=["POST"])
    def api_memory_confirm():
        return handle_memory_confirm()

    @app.route("/api/memory/<memory_id>", methods=["DELETE"])
    def api_memory_delete(memory_id):
        return handle_memory_delete(memory_id)

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
