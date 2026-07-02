"""
v4 Tool Truth Closure — single-source resolver tests.

The v4 contract ``ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE`` mandates
that every tool handler return value MUST pass through
``speg_engine.tool_runtime.resolve_tool_outcome`` before it lands in a
``ToolResult``. The previous v3.10 helper trio
(``_resolve_success_flag`` / ``_resolve_error_code`` / ``_resolve_error_message``)
is now a thin internal alias; new code MUST use the resolver.

These tests cover the full resolution matrix:

  * ``None`` → FAIL / NULL_RESULT / {}
  * ``{ok: False, error_code: X}`` → FAIL / X / dict
  * ``{ok: False}`` (no error_code) → FAIL / TOOL_RETURNED_NOT_OK / dict
  * ``{ok: True}`` → SUCCESS / None / dict
  * ``{success: True}`` (legacy) → SUCCESS / None / dict
  * ``{success: False}`` (legacy) → FAIL / TOOL_FAILED / dict
  * ``{success: False, error_code: X}`` (legacy) → FAIL / None / dict
    (asymmetric: legacy ``success`` does NOT propagate error_code)
  * bare dict (no ok / no success) → SUCCESS / None / dict
  * non-dict (str / int) → SUCCESS / None / value

The v3.10 v3.10 P0 test ``test_handler_structured_error_code_is_propagated``
was updated to use the modern ``ok`` key — the legacy ``success`` key is
a boolean verdict only and does not carry error_code through the resolver.
This is an explicit v4 contract change.
"""

from __future__ import annotations

import pytest

from speg_engine.tool_runtime import (
    extract_error,
    resolve_tool_outcome,
)
from speg_engine.runtime_contracts import ExecutionContract


# ── A: None handler result → FAIL / NULL_RESULT / {} ──────────────────


def test_none_result_is_fail_null_result():
    status, code, normalized = resolve_tool_outcome(None)
    assert status == "FAIL"
    assert code == "NULL_RESULT"
    assert normalized == {}
    assert isinstance(normalized, dict)


# ── B: ok=False with explicit error_code → preserve error_code ────────


def test_ok_false_with_error_code_preserves_code():
    raw = {"ok": False, "error_code": "AUTH_REQUIRED", "error": "no token"}
    status, code, normalized = resolve_tool_outcome(raw)
    assert status == "FAIL"
    assert code == "AUTH_REQUIRED"
    assert normalized is raw


# ── C: ok=False without error_code → default TOOL_RETURNED_NOT_OK ─────


def test_ok_false_without_error_code_uses_default():
    raw = {"ok": False, "error": "nope"}
    status, code, normalized = resolve_tool_outcome(raw)
    assert status == "FAIL"
    assert code == "TOOL_RETURNED_NOT_OK"
    assert normalized is raw


# ── D: ok=True → SUCCESS / None ───────────────────────────────────────


def test_ok_true_is_success_no_error_code():
    raw = {"ok": True, "data": [1, 2, 3]}
    status, code, normalized = resolve_tool_outcome(raw)
    assert status == "SUCCESS"
    assert code is None
    assert normalized is raw


# ── E: success=True (legacy) → SUCCESS / None ─────────────────────────


def test_legacy_success_true_is_success():
    raw = {"success": True, "result": "ok"}
    status, code, normalized = resolve_tool_outcome(raw)
    assert status == "SUCCESS"
    assert code is None


# ── F: success=False (legacy) → FAIL / None (no error_code) ──────────


def test_legacy_success_false_is_fail():
    """v4 contract: the legacy ``success`` key is a boolean verdict
    only. Per the v4 spec, error_code is ``None`` in BOTH the
    success and fail cases of the legacy branch — handlers that
    want a specific error_code must migrate to the modern ``ok``
    contract.
    """
    raw = {"success": False, "error": "boom"}
    status, code, normalized = resolve_tool_outcome(raw)
    assert status == "FAIL"
    assert code is None


def test_legacy_success_false_does_not_propagate_error_code():
    """A handler that uses the legacy ``success: False`` shape MUST
    NOT have its ``error_code`` carried into the resolver's
    second return value. The v4 spec explicitly returns ``None``
    for error_code in the legacy branch — the v3.10 behaviour of
    always reading ``error_code`` from the dict is a v4 contract
    violation.
    """
    raw = {"success": False, "error_code": "CRED_MISSING", "error": "no creds"}
    status, code, normalized = resolve_tool_outcome(raw)
    assert status == "FAIL"
    assert code is None
    # But the dict still carries the error_code — the engine can
    # read it from the normalized value if it wants to.
    assert normalized["error_code"] == "CRED_MISSING"


# ── G: bare dict with no ok / no success → SUCCESS (legacy default) ───


def test_bare_dict_is_success():
    raw = {"answer": 42, "summary": "ok"}
    status, code, normalized = resolve_tool_outcome(raw)
    assert status == "SUCCESS"
    assert code is None
    assert normalized is raw


# ── H: non-dict return (str / int) → SUCCESS / None / value ───────────


@pytest.mark.parametrize("scalar", ["hello", 42, 3.14, [1, 2, 3]])
def test_non_dict_return_is_success(scalar):
    status, code, normalized = resolve_tool_outcome(scalar)
    assert status == "SUCCESS"
    assert code is None
    assert normalized is scalar


# ── I: ok takes priority over success when both are present ──────────


def test_ok_false_overrides_legacy_success_true():
    """If a handler returns BOTH ``ok=False`` and ``success=True``,
    the modern ``ok`` signal wins. The legacy ``success`` field
    is ignored when ``ok`` is explicit.
    """
    raw = {"ok": False, "success": True, "error_code": "X"}
    status, code, normalized = resolve_tool_outcome(raw)
    assert status == "FAIL"
    assert code == "X"


# ── J: extract_error flattens errors list / dict / string / message ───


def test_extract_error_uses_error_field():
    assert extract_error({"error": "boom"}) == "boom"


def test_extract_error_joins_errors_list():
    assert extract_error({"errors": ["a", "b", "c"]}) == "a; b; c"


def test_extract_error_flattens_errors_dict_as_json():
    # extract_error uses json.dumps for dict errors so the result
    # is a stable string the LLM can read.
    text = extract_error({"errors": {"a": 1, "b": 2}})
    assert "a" in text and "b" in text


def test_extract_error_falls_back_to_message():
    assert extract_error({"message": "fallback"}) == "fallback"


def test_extract_error_uses_error_code_as_last_resort():
    assert extract_error({"error_code": "X_NO_INFO"}) == "X_NO_INFO"


def test_extract_error_returns_empty_for_no_error():
    assert extract_error({"ok": True, "data": [1, 2]}) == ""


def test_extract_error_returns_empty_for_non_dict():
    assert extract_error(None) == ""
    assert extract_error("hello") == ""
    assert extract_error(42) == ""


# ── K: contract assertion — TOOL_TRUTH_SINGLE_SOURCE is on ──────────


def test_tool_truth_contract_is_on():
    assert ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE is True