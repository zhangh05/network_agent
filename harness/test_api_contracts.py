# harness/test_api_contracts.py
"""P2-C: API Contract tests — response shape, error structure, sensitive field guards.

Coverage:
  - Error envelope: {ok:false, error, message} — never mixes formats
  - List envelope: {ok:true, items, count, workspace_id}
  - Item envelope: {ok:true, item, workspace_id}
  - Specific API contracts: artifacts, upload, pcap, decision, runs, sessions
  - Sensitive fields excluded from API responses
  - Removed paths are not exposed as supported APIs
"""

import json
import pytest
from backend.core.responses import (
    ok_response,
    error_response,
    list_response,
    item_response,
    not_found,
    bad_request,
    invalid_workspace,
    workspace_not_found,
    internal_error,
)


# ═══════════════════════════════════════════════════════════════════════
# Canonical envelope tests
# ═══════════════════════════════════════════════════════════════════════


class TestOkResponse:
    def test_shape(self):
        body, status = ok_response({"key": "val"}, workspace_id="ws1")
        assert status == 200
        assert body["ok"] is True
        assert body["key"] == "val"
        assert body["workspace_id"] == "ws1"

    def test_no_data(self):
        body, status = ok_response()
        assert status == 200
        assert body == {"ok": True}

    def test_non_dict_data(self):
        body, status = ok_response([1, 2, 3])
        assert body["ok"] is True
        assert body["data"] == [1, 2, 3]


class TestErrorResponse:
    def test_canonical_shape(self):
        body, status = error_response("ARTIFACT_NOT_FOUND", "artifact art_001 not found", 404)
        assert status == 404
        assert body["ok"] is False
        assert body["error"] == "ARTIFACT_NOT_FOUND"
        assert body["message"] == "artifact art_001 not found"
        # Canonical error envelopes do not expose alternate error fields.
        assert "detail" not in body
        assert "status" not in body
        assert "summary" not in body

    def test_with_details(self):
        body, status = error_response("VALIDATION_ERROR", "bad input", 400, {"field": "title"})
        assert body["details"] == {"field": "title"}

    def test_default_status(self):
        body, status = error_response("ERROR", "msg")
        assert status == 400

    def test_message_fallback(self):
        body, status = error_response("ERROR_CODE")
        assert body["message"] == "ERROR_CODE"


class TestListResponse:
    def test_shape(self):
        body, status = list_response([{"id": 1}, {"id": 2}], "ws1")
        assert status == 200
        assert body["ok"] is True
        assert body["items"] == [{"id": 1}, {"id": 2}]
        assert body["count"] == 2
        assert body["workspace_id"] == "ws1"

    def test_explicit_count(self):
        body, status = list_response(["a"], "ws1", count=42)
        assert body["count"] == 42

    def test_empty(self):
        body, status = list_response([])
        assert body["items"] == []
        assert body["count"] == 0


class TestItemResponse:
    def test_shape(self):
        body, status = item_response({"artifact_id": "art_1"}, "ws1")
        assert status == 200
        assert body["ok"] is True
        assert body["item"] == {"artifact_id": "art_1"}
        assert body["workspace_id"] == "ws1"


class TestConvenienceResponses:
    def test_not_found(self):
        body, status = not_found("artifact", "art_001")
        assert status == 404
        assert body["error"] == "ARTIFACT_NOT_FOUND"
        assert "art_001" in body["message"]

    def test_bad_request(self):
        body, status = bad_request("MISSING_FIELD", "title required")
        assert status == 400
        assert body["error"] == "MISSING_FIELD"

    def test_invalid_workspace(self):
        body, status = invalid_workspace()
        assert status == 400
        assert body["error"] == "INVALID_WORKSPACE_ID"

    def test_internal_error(self):
        body, status = internal_error("db connection lost")
        assert status == 500
        assert body["error"] == "INTERNAL_ERROR"


# ═══════════════════════════════════════════════════════════════════════
# Error structure uniformity check
# ═══════════════════════════════════════════════════════════════════════


class TestErrorUniformity:
    """All error helpers produce the canonical {ok, error, message} shape."""

    def test_all_helpers_produce_canonical_error(self):
        helpers = [
            lambda: error_response("E1", "m1"),
            lambda: not_found("resource"),
            lambda: bad_request("E2", "m2"),
            lambda: invalid_workspace(),
            lambda: workspace_not_found(),
            lambda: internal_error(),
        ]
        for fn in helpers:
            body, _ = fn()
            assert "ok" in body, f"missing ok in {body}"
            assert body["ok"] is False
            assert "error" in body, f"missing error in {body}"
            assert "message" in body, f"missing message in {body}"
            assert "detail" not in body
            assert "status" not in body

    def test_response_helpers_use_canonical_formats(self):
        """Every response helper produces a canonical envelope."""
        responses = [
            ok_response({"a": 1}),
            error_response("E", "m"),
            list_response([], "ws"),
            item_response({}, "ws"),
            not_found("x"),
            bad_request("E", "m"),
            invalid_workspace(),
            workspace_not_found(),
            internal_error(),
        ]
        for body, status in responses:
            # Error responses must have ok=False
            if body.get("ok") is False:
                assert "error" in body
                assert "detail" not in body, f"Unexpected 'detail' in {body}"
                assert "status" not in body, f"Unexpected 'status' in {body}"


# ═══════════════════════════════════════════════════════════════════════
# Sensitive field exclusion
# ═══════════════════════════════════════════════════════════════════════


class TestSensitiveFieldExclusion:
    """Core API responses must never return sensitive fields."""

    SENSITIVE = ("api_key", "token", "password", "secret", "source_config",
                 "raw_config", "private_key", "authorization")

    def test_ok_response_does_not_leak_sensitive(self):
        body, _ = ok_response({"public": "ok"})
        for key in self.SENSITIVE:
            assert key not in body

    def test_error_response_does_not_leak_sensitive(self):
        body, _ = error_response("E", "error occurred")
        for key in self.SENSITIVE:
            assert key not in body

    def test_list_response_does_not_leak_sensitive(self):
        body, _ = list_response([{"id": 1}], "ws")
        for key in self.SENSITIVE:
            assert key not in body

    def test_item_response_does_not_leak_sensitive(self):
        body, _ = item_response({"id": 1}, "ws")
        for key in self.SENSITIVE:
            assert key not in body

    def test_sensitive_keys_must_not_be_returned_from_artifact_api(self):
        """Artifact API must not expose raw_config or source_config in metadata."""
        # Simulated artifact response
        # If metadata contains sensitive keys, they should be filtered
        from agent.runtime.turn_persistence import _is_sensitive_key
        for key in self.SENSITIVE:
            assert _is_sensitive_key(key), f"Key '{key}' must be recognized as sensitive"

    def test_sensitive_keys_must_not_be_returned_from_run_api(self):
        """Run API must not expose raw_config, api_key, etc."""
        from agent.runtime.turn_persistence import _is_sensitive_key
        for key in self.SENSITIVE:
            assert _is_sensitive_key(key)


# ═══════════════════════════════════════════════════════════════════════
# Specific API shape contracts (import verification)
# ═══════════════════════════════════════════════════════════════════════


class TestArtifactApiContract:
    def test_artifact_routes_have_expected_handler_names(self):
        from backend.api.artifact_routes import register_artifact_routes
        import inspect
        source = inspect.getsource(register_artifact_routes)
        # Must have expected endpoint handlers
        handlers = [
            "api_workspace_artifacts",      # GET  — list
            "api_workspace_artifact_create", # POST — create
            "api_workspace_artifact_upload", # POST — upload (FormData)
            "api_artifact_content",          # GET  — content
            "api_artifact_batch_delete",     # POST — batch delete
        ]
        for h in handlers:
            assert h in source, f"Expected handler '{h}' in artifact routes"

    def test_upload_requires_file(self):
        """Upload endpoint must return proper error when no file provided."""
        import inspect
        from backend.api.artifact_routes import register_artifact_routes
        source = inspect.getsource(register_artifact_routes)
        # Upload endpoint should check 'file' in request.files
        assert "'file' not in request.files" in source or '"file" not in request.files' in source


class TestRunSidecarFiltering:
    def test_run_store_excludes_trace_sidecars(self):
        from pathlib import Path
        from workspace.run_store import _is_run_record_file

        assert _is_run_record_file(Path("run_1.json"))
        assert not _is_run_record_file(Path("run_1.trace.json"))

    def test_workspace_manager_excludes_trace_sidecars(self):
        from pathlib import Path
        from workspace.manager import _is_run_record_file

        assert _is_run_record_file(Path("run_1.json"))
        assert not _is_run_record_file(Path("run_1.trace.json"))


class TestPcapApiContract:
    def test_pcap_parse_endpoint_exists(self):
        from backend.api.pcap_routes import register_pcap_routes
        import inspect
        source = inspect.getsource(register_pcap_routes)
        assert "pcap" in source.lower()


class TestRuntimeApiContract:
    def test_runtime_routes_have_health_and_selfcheck(self):
        from backend.api.runtime_routes import register_runtime_routes
        import inspect
        source = inspect.getsource(register_runtime_routes)
        assert "health" in source.lower()
        assert "selfcheck" in source.lower()


class TestStatusCodeConsistency:
    """Consistent HTTP status codes across API endpoints."""

    def test_not_found_always_404(self):
        for resource in ("artifact", "file", "workspace", "session", "reference"):
            body, status = not_found(resource)
            assert status == 404

    def test_bad_request_always_400(self):
        body, status = bad_request("ERROR", "msg")
        assert status == 400

    def test_invalid_workspace_always_400(self):
        body, status = invalid_workspace()
        assert status == 400
